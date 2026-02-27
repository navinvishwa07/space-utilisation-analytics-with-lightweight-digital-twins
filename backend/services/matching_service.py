"""Demand forecasting and allocation optimization service using CP-SAT."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

try:
    from ortools.sat.python import cp_model
except ModuleNotFoundError:  # pragma: no cover - runtime dependency guard
    cp_model = None  # type: ignore[assignment]

from backend.domain.constraints import AllocationConfig, validate_allocation_config
from backend.domain.models import (
    AllocationDecision,
    AllocationRequest,
    DemandForecast,
    IdlePrediction,
    OptimizationResult,
    Room,
)
from backend.repository.data_repository import DataRepository
from backend.utils.config import Settings, get_settings
from backend.utils.logger import get_logger


logger = get_logger(__name__)


class AllocationValidationError(Exception):
    """Raised when optimization request inputs are invalid."""


class SolverDependencyError(Exception):
    """Raised when OR-Tools is unavailable in the runtime."""


@dataclass(frozen=True)
class BuildArtifacts:
    model: Any
    variables: dict[tuple[int, int], Any]
    objective_coefficients: dict[tuple[int, int], int]
    total_assigned_var: Any


def _ensure_solver_dependency() -> None:
    if cp_model is None:
        raise SolverDependencyError(
            "OR-Tools is not installed. Install 'ortools' to enable allocation optimization."
        )


def _validate_slot(slot: str) -> None:
    parts = slot.split("-")
    if len(parts) != 2:
        raise AllocationValidationError("time_slot must follow HH-HH format")
    if not all(part.isdigit() for part in parts):
        raise AllocationValidationError("time_slot must follow HH-HH format")
    start_hour, end_hour = (int(part) for part in parts)
    if not 0 <= start_hour <= 23 or not 0 <= end_hour <= 23 or start_hour >= end_hour:
        raise AllocationValidationError("time_slot boundaries are invalid")


def _validate_date(date_value: str) -> None:
    try:
        datetime.strptime(date_value, "%Y-%m-%d")
    except ValueError as exc:
        raise AllocationValidationError("date must follow YYYY-MM-DD format") from exc


def _validate_inputs(
    requested_date: str,
    requested_time_slot: str,
    config: AllocationConfig,
) -> None:
    _validate_date(requested_date)
    _validate_slot(requested_time_slot)
    validate_allocation_config(config)


def compute_fairness_metric(
    requests: list[AllocationRequest],
    allocations: list[AllocationDecision],
) -> float:
    if not allocations:
        return 0.0

    allocated_counts = Counter(decision.stakeholder_id for decision in allocations)
    stakeholders = sorted({request.stakeholder_id for request in requests})
    if not stakeholders:
        return 0.0

    values = [float(allocated_counts.get(stakeholder, 0)) for stakeholder in stakeholders]
    numerator = sum(values) ** 2
    denominator = len(values) * sum(value**2 for value in values)
    if denominator == 0.0:
        return 0.0
    return float(numerator / denominator)


def _compute_fairness_metric(
    requests: list[AllocationRequest],
    allocations: list[AllocationDecision],
) -> float:
    """Backward-compatible alias kept for internal call sites/tests."""
    return compute_fairness_metric(requests=requests, allocations=allocations)


def forecast_demand(
    requests: list[AllocationRequest],
    historical_counts_by_slot: dict[str, int],
) -> list[DemandForecast]:
    """Compute frequency-based demand intensity by time slot."""
    current_counts_by_slot = Counter(request.requested_time_slot for request in requests)
    all_slots = sorted(set(historical_counts_by_slot).union(current_counts_by_slot))
    if not all_slots:
        return []

    max_historical = max(historical_counts_by_slot.get(slot, 0) for slot in all_slots)
    forecasts: list[DemandForecast] = []
    for slot in all_slots:
        historical_count = historical_counts_by_slot.get(slot, 0)
        if max_historical > 0:
            demand_intensity = historical_count / max_historical
        else:
            demand_intensity = 0.0
        forecasts.append(
            DemandForecast(
                time_slot=slot,
                historical_count=historical_count,
                demand_intensity_score=float(demand_intensity),
            )
        )
    return forecasts


def build_model(
    *,
    rooms: list[Room],
    requests: list[AllocationRequest],
    predictions: list[IdlePrediction],
    config: AllocationConfig,
) -> BuildArtifacts:
    """Build CP-SAT assignment model and return model artifacts."""
    _ensure_solver_dependency()
    model = cp_model.CpModel()
    prediction_by_room = {prediction.room_id: prediction.idle_probability for prediction in predictions}
    variables: dict[tuple[int, int], cp_model.IntVar] = {}
    objective_coefficients: dict[tuple[int, int], int] = {}

    for room in rooms:
        idle_probability = prediction_by_room.get(room.room_id, 0.0)
        if idle_probability <= config.idle_probability_threshold:
            continue

        for request in requests:
            if room.capacity < request.requested_capacity:
                continue
            pair = (room.room_id, request.request_id)
            variables[pair] = model.NewBoolVar(f"x_room_{room.room_id}_req_{request.request_id}")
            coefficient = int(round(idle_probability * request.priority_weight * config.objective_scale))
            objective_coefficients[pair] = max(0, coefficient)

    for request in requests:
        request_vars = [
            var
            for (room_id, request_id), var in variables.items()
            if request_id == request.request_id
        ]
        if request_vars:
            model.Add(sum(request_vars) <= 1)

    for room in rooms:
        room_vars = [
            var
            for (room_id, _), var in variables.items()
            if room_id == room.room_id
        ]
        if room_vars:
            model.Add(sum(room_vars) <= 1)

    total_assigned = model.NewIntVar(0, len(requests), "total_assigned")
    if variables:
        model.Add(total_assigned == sum(variables.values()))
    else:
        model.Add(total_assigned == 0)

    stakeholder_to_vars: dict[str, list[cp_model.IntVar]] = defaultdict(list)
    stakeholder_by_request_id = {
        request.request_id: request.stakeholder_id for request in requests
    }
    for (room_id, request_id), var in variables.items():
        del room_id
        stakeholder = stakeholder_by_request_id[request_id]
        stakeholder_to_vars[stakeholder].append(var)

    cap_scaled = int(round(config.stakeholder_usage_cap * config.objective_scale))
    for stakeholder, stakeholder_vars in stakeholder_to_vars.items():
        if not stakeholder_vars:
            continue
        model.Add(sum(stakeholder_vars) * config.objective_scale <= cap_scaled * total_assigned)
        logger.debug(
            "Stakeholder cap constraint added | stakeholder_id=%s | cap=%.3f",
            stakeholder,
            config.stakeholder_usage_cap,
        )

    if variables:
        model.Maximize(
            sum(
                objective_coefficients[pair] * var
                for pair, var in variables.items()
            )
        )
    else:
        model.Maximize(0)

    return BuildArtifacts(
        model=model,
        variables=variables,
        objective_coefficients=objective_coefficients,
        total_assigned_var=total_assigned,
    )


def solve_model(
    *,
    artifacts: BuildArtifacts,
    rooms: list[Room],
    requests: list[AllocationRequest],
    predictions: list[IdlePrediction],
    config: AllocationConfig,
) -> OptimizationResult:
    """Solve CP-SAT model and return allocations, objective, fairness, and misses."""
    _ensure_solver_dependency()
    del rooms
    del predictions

    if not requests:
        return OptimizationResult(
            allocations=[],
            objective_value=0.0,
            fairness_metric=0.0,
            unassigned_request_ids=[],
        )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(config.solver_max_time_seconds)
    solver.parameters.num_search_workers = config.cp_sat_workers
    solver.parameters.random_seed = config.solver_random_seed

    status = solver.Solve(artifacts.model)
    status_name = solver.StatusName(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        logger.warning("Allocation solve failed | status=%s", status_name)
        return OptimizationResult(
            allocations=[],
            objective_value=0.0,
            fairness_metric=0.0,
            unassigned_request_ids=[request.request_id for request in requests],
        )

    request_lookup = {request.request_id: request for request in requests}
    allocations: list[AllocationDecision] = []
    for (room_id, request_id), var in artifacts.variables.items():
        if solver.Value(var) != 1:
            continue
        request = request_lookup[request_id]
        score = artifacts.objective_coefficients[(room_id, request_id)] / config.objective_scale
        allocations.append(
            AllocationDecision(
                request_id=request_id,
                room_id=room_id,
                score=score,
                stakeholder_id=request.stakeholder_id,
            )
        )

    allocated_ids = {allocation.request_id for allocation in allocations}
    unassigned = [
        request.request_id
        for request in requests
        if request.request_id not in allocated_ids
    ]
    objective_value = float(solver.ObjectiveValue()) / config.objective_scale
    fairness_metric = compute_fairness_metric(requests=requests, allocations=allocations)

    logger.info(
        (
            "Allocation solve completed | status=%s | objective_value=%.6f | "
            "fairness_metric=%.6f | allocations=%s | unassigned=%s"
        ),
        status_name,
        objective_value,
        fairness_metric,
        len(allocations),
        len(unassigned),
    )
    return OptimizationResult(
        allocations=allocations,
        objective_value=objective_value,
        fairness_metric=fairness_metric,
        unassigned_request_ids=unassigned,
    )


def persist_results(
    *,
    repository: DataRepository,
    requested_date: str,
    forecasts: list[DemandForecast],
    result: OptimizationResult,
) -> None:
    """Persist forecast and allocation results through repository layer."""
    repository.save_forecast_output(
        forecast_date=requested_date,
        forecasts=forecasts,
    )
    repository.save_allocation_logs(
        allocations=[
            (allocation.request_id, allocation.room_id, allocation.score)
            for allocation in result.allocations
        ]
    )
    repository.mark_requests_allocated(
        [allocation.request_id for allocation in result.allocations]
    )


class AllocationOptimizationService:
    """Business logic orchestration for forecast + CP-SAT room allocation."""

    def __init__(
        self,
        repository: Optional[DataRepository] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._repository = repository or DataRepository(self._settings)

    def optimize_allocation(
        self,
        *,
        requested_date: str,
        requested_time_slot: str,
        idle_probability_threshold: Optional[float] = None,
        stakeholder_usage_cap: Optional[float] = None,
    ) -> OptimizationResult:
        config = AllocationConfig(
            idle_probability_threshold=(
                idle_probability_threshold
                if idle_probability_threshold is not None
                else self._settings.allocation_idle_probability_threshold
            ),
            stakeholder_usage_cap=(
                stakeholder_usage_cap
                if stakeholder_usage_cap is not None
                else self._settings.allocation_stakeholder_usage_cap
            ),
            solver_max_time_seconds=self._settings.allocation_solver_max_time_seconds,
            solver_random_seed=self._settings.allocation_solver_random_seed,
            objective_scale=self._settings.allocation_objective_scale,
            cp_sat_workers=self._settings.allocation_cp_sat_workers,
        )
        _validate_inputs(
            requested_date=requested_date,
            requested_time_slot=requested_time_slot,
            config=config,
        )
        _ensure_solver_dependency()

        rooms = self._repository.list_rooms_for_allocation()
        requests = self._repository.list_pending_requests(
            requested_date=requested_date,
            requested_time_slot=requested_time_slot,
        )
        predictions = self._repository.list_idle_predictions(
            requested_date=requested_date,
            requested_time_slot=requested_time_slot,
        )

        historical_counts = self._repository.get_historical_request_counts_by_time_slot(
            lookback_days=self._settings.allocation_forecast_history_days,
            target_date=requested_date,
        )
        forecasts = forecast_demand(
            requests=requests,
            historical_counts_by_slot=historical_counts,
        )

        if not rooms or not requests:
            result = OptimizationResult(
                allocations=[],
                objective_value=0.0,
                fairness_metric=0.0,
                unassigned_request_ids=[request.request_id for request in requests],
            )
            persist_results(
                repository=self._repository,
                requested_date=requested_date,
                forecasts=forecasts,
                result=result,
            )
            logger.info(
                "Allocation skipped due to empty inputs | rooms=%s | requests=%s",
                len(rooms),
                len(requests),
            )
            return result

        artifacts = build_model(
            rooms=rooms,
            requests=requests,
            predictions=predictions,
            config=config,
        )
        result = solve_model(
            artifacts=artifacts,
            rooms=rooms,
            requests=requests,
            predictions=predictions,
            config=config,
        )
        persist_results(
            repository=self._repository,
            requested_date=requested_date,
            forecasts=forecasts,
            result=result,
        )
        logger.info(
            (
                "Optimization completed | objective_value=%.6f | fairness_metric=%.6f | "
                "unassigned_requests=%s"
            ),
            result.objective_value,
            result.fairness_metric,
            result.unassigned_request_ids,
        )
        return result
