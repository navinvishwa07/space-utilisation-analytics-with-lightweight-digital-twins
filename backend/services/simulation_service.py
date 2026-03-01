"""What-if simulation service isolated from production persistence.

This module intentionally avoids any repository writes. The simulation endpoint
must allow operators to evaluate temporary constraints without mutating
`Requests`, `Predictions`, `AllocationLogs`, or any other production table.
"""

from __future__ import annotations

import copy
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Optional
from uuid import uuid4

from backend.domain.constraints import AllocationConfig, validate_allocation_config
from backend.domain.models import AllocationDecision, AllocationRequest, IdlePrediction, Room
from backend.repository.data_repository import DataRepository
from backend.services.matching_service import (
    compute_fairness_metric,
    optimize_with_fallback,
)
from backend.services.prediction_service import (
    AvailabilityPredictionService,
    ModelNotReadyError,
    PredictionValidationError,
    RoomNotFoundError,
)
from backend.utils.config import Settings, get_settings
from backend.utils.logger import get_logger


logger = get_logger(__name__)


class SimulationValidationError(Exception):
    """Raised when temporary simulation constraints are invalid."""


@dataclass(frozen=True)
class TemporaryConstraints:
    idle_threshold: Optional[float] = None
    stakeholder_cap: Optional[float] = None
    capacity_override: dict[int, int] | None = None
    priority_adjustment: dict[str, float] | None = None


@dataclass(frozen=True)
class ScenarioDataset:
    rooms: list[Room]
    requests_by_slot: dict[tuple[str, str], list[AllocationRequest]]
    predictions_by_slot: dict[tuple[str, str], list[IdlePrediction]]

    @property
    def requests(self) -> list[AllocationRequest]:
        aggregated: list[AllocationRequest] = []
        for key in sorted(self.requests_by_slot):
            aggregated.extend(self.requests_by_slot[key])
        return aggregated


@dataclass(frozen=True)
class SimulatedAllocation:
    request_id: int
    room_id: int
    stakeholder_id: str
    score: float
    requested_date: str
    requested_time_slot: str


@dataclass(frozen=True)
class SimulationRunResult:
    allocations: list[SimulatedAllocation]
    objective_value: float
    fairness_metric: float
    unassigned_request_ids: list[int]


@dataclass(frozen=True)
class SimulationMetrics:
    utilization_rate: float
    requests_satisfied: int
    objective_value: float
    total_rooms_utilized: int
    average_idle_probability_utilized: float
    fairness_metric: float

    def to_api_dict(self) -> dict[str, float | int]:
        return {
            "utilization_rate": self.utilization_rate,
            "requests_satisfied": self.requests_satisfied,
            "objective_value": self.objective_value,
            "total_rooms_utilized": self.total_rooms_utilized,
            "average_idle_probability_utilized": self.average_idle_probability_utilized,
            "fairness_metric": self.fairness_metric,
        }


class SimulationService:
    """Runs deterministic baseline vs what-if comparisons in memory.

    WHY this service is isolated:
    - Production optimization writes allocation/forecast logs and mutates request
      status; simulation must not mutate any persisted state.
    - Using deep-copied, in-memory datasets ensures temporary constraints are
      discarded after the request, preserving production integrity.
    """

    def __init__(
        self,
        repository: Optional[DataRepository] = None,
        settings: Optional[Settings] = None,
        prediction_service: Optional[AvailabilityPredictionService] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._repository = repository or DataRepository(self._settings)
        self._prediction_service = prediction_service

    def _build_simulation_config(
        self,
        *,
        idle_threshold: Optional[float] = None,
        stakeholder_cap: Optional[float] = None,
    ) -> AllocationConfig:
        config = AllocationConfig(
            idle_probability_threshold=(
                idle_threshold
                if idle_threshold is not None
                else self._settings.allocation_idle_probability_threshold
            ),
            stakeholder_usage_cap=(
                stakeholder_cap
                if stakeholder_cap is not None
                else self._settings.allocation_stakeholder_usage_cap
            ),
            solver_max_time_seconds=self._settings.allocation_solver_max_time_seconds,
            solver_random_seed=self._settings.simulation_solver_random_seed,
            objective_scale=self._settings.allocation_objective_scale,
            cp_sat_workers=self._settings.simulation_cp_sat_workers,
        )
        validate_allocation_config(config)
        return config

    def _validate_temporary_constraints(
        self,
        constraints: TemporaryConstraints,
        dataset: ScenarioDataset,
    ) -> None:
        if constraints.idle_threshold is not None and not 0.0 <= constraints.idle_threshold <= 1.0:
            raise SimulationValidationError("idle_threshold must be between 0 and 1")
        if constraints.stakeholder_cap is not None and not 0.0 < constraints.stakeholder_cap <= 1.0:
            raise SimulationValidationError("stakeholder_cap must be in (0, 1]")

        room_ids = {room.room_id for room in dataset.rooms}
        capacity_override = constraints.capacity_override or {}
        for room_id, new_capacity in capacity_override.items():
            if room_id not in room_ids:
                raise SimulationValidationError(
                    f"capacity_override references unknown room_id={room_id}"
                )
            if new_capacity <= 0:
                raise SimulationValidationError(
                    f"capacity_override for room_id={room_id} must be > 0"
                )

        stakeholder_ids = {request.stakeholder_id for request in dataset.requests}
        priority_adjustment = constraints.priority_adjustment or {}
        for stakeholder_id, weight in priority_adjustment.items():
            if stakeholder_id not in stakeholder_ids:
                raise SimulationValidationError(
                    f"priority_adjustment references unknown stakeholder='{stakeholder_id}'"
                )
            if weight <= 0.0:
                raise SimulationValidationError(
                    f"priority_adjustment for stakeholder='{stakeholder_id}' must be > 0"
                )

    def _load_dataset(self) -> ScenarioDataset:
        rooms = self._repository.list_rooms_for_allocation()
        all_pending_requests = self._repository.list_all_pending_requests()

        requests_by_slot: dict[tuple[str, str], list[AllocationRequest]] = defaultdict(list)
        for request in all_pending_requests:
            key = (request.requested_date, request.requested_time_slot)
            requests_by_slot[key].append(request)

        room_ids = sorted(room.room_id for room in rooms)
        predictions_by_slot: dict[tuple[str, str], list[IdlePrediction]] = {}
        fallback_idle_probability = 1.0 - self._settings.prediction_default_occupancy_probability
        for requested_date, requested_time_slot in sorted(requests_by_slot):
            persisted_predictions = self._repository.list_idle_predictions(
                requested_date=requested_date,
                requested_time_slot=requested_time_slot,
            )
            prediction_by_room = {prediction.room_id: prediction for prediction in persisted_predictions}
            missing_room_ids = [
                room_id
                for room_id in room_ids
                if room_id not in prediction_by_room
            ]
            if missing_room_ids:
                logger.info(
                    (
                        "Simulation prediction gap detected | date=%s | time_slot=%s | "
                        "missing_rooms=%s"
                    ),
                    requested_date,
                    requested_time_slot,
                    missing_room_ids,
                )
                for room_id in missing_room_ids:
                    generated_prediction = self._predict_idle_probability(
                        room_id=room_id,
                        requested_date=requested_date,
                        requested_time_slot=requested_time_slot,
                        fallback_idle_probability=fallback_idle_probability,
                    )
                    prediction_by_room[room_id] = generated_prediction

            predictions_by_slot[(requested_date, requested_time_slot)] = [
                prediction_by_room[room_id]
                for room_id in sorted(prediction_by_room)
            ]

        return ScenarioDataset(
            rooms=rooms,
            requests_by_slot=dict(sorted(requests_by_slot.items())),
            predictions_by_slot=predictions_by_slot,
        )

    def _predict_idle_probability(
        self,
        *,
        room_id: int,
        requested_date: str,
        requested_time_slot: str,
        fallback_idle_probability: float,
    ) -> IdlePrediction:
        if self._prediction_service is None:
            return IdlePrediction(
                room_id=room_id,
                date=requested_date,
                time_slot=requested_time_slot,
                idle_probability=fallback_idle_probability,
            )
        try:
            prediction = self._prediction_service.predict(
                room_id=room_id,
                date=requested_date,
                time_slot=requested_time_slot,
                persist=False,
            )
            return IdlePrediction(
                room_id=room_id,
                date=requested_date,
                time_slot=requested_time_slot,
                idle_probability=float(prediction["idle_probability"]),
            )
        except (ModelNotReadyError, PredictionValidationError, RoomNotFoundError):
            logger.warning(
                (
                    "Simulation fallback prediction applied | room_id=%s | date=%s | "
                    "time_slot=%s"
                ),
                room_id,
                requested_date,
                requested_time_slot,
            )
            return IdlePrediction(
                room_id=room_id,
                date=requested_date,
                time_slot=requested_time_slot,
                idle_probability=fallback_idle_probability,
            )

    def _optimize_dataset(
        self,
        *,
        dataset: ScenarioDataset,
        config: AllocationConfig,
    ) -> SimulationRunResult:
        if not dataset.rooms or not dataset.requests:
            return SimulationRunResult(
                allocations=[],
                objective_value=0.0,
                fairness_metric=0.0,
                unassigned_request_ids=[request.request_id for request in dataset.requests],
            )

        allocations: list[SimulatedAllocation] = []
        objective_value = 0.0
        unassigned_request_ids: list[int] = []

        for key in sorted(dataset.requests_by_slot):
            requested_date, requested_time_slot = key
            slot_requests = dataset.requests_by_slot[key]
            slot_predictions = dataset.predictions_by_slot.get(key, [])

            if not slot_requests:
                continue

            if not slot_predictions:
                unassigned_request_ids.extend(request.request_id for request in slot_requests)
                continue

            slot_result = optimize_with_fallback(
                rooms=dataset.rooms,
                requests=slot_requests,
                predictions=slot_predictions,
                config=config,
            )
            objective_value += slot_result.objective_value
            unassigned_request_ids.extend(slot_result.unassigned_request_ids)

            request_by_id = {request.request_id: request for request in slot_requests}
            for decision in slot_result.allocations:
                request = request_by_id[decision.request_id]
                allocations.append(
                    SimulatedAllocation(
                        request_id=decision.request_id,
                        room_id=decision.room_id,
                        stakeholder_id=request.stakeholder_id,
                        score=decision.score,
                        requested_date=requested_date,
                        requested_time_slot=requested_time_slot,
                    )
                )

        fairness_metric = compute_fairness_metric(
            requests=dataset.requests,
            allocations=[
                AllocationDecision(
                    request_id=allocation.request_id,
                    room_id=allocation.room_id,
                    score=allocation.score,
                    stakeholder_id=allocation.stakeholder_id,
                )
                for allocation in allocations
            ],
        )
        return SimulationRunResult(
            allocations=allocations,
            objective_value=objective_value,
            fairness_metric=fairness_metric,
            unassigned_request_ids=sorted(unassigned_request_ids),
        )

    def compute_baseline(self, dataset: ScenarioDataset) -> SimulationRunResult:
        baseline_config = self._build_simulation_config()
        return self._optimize_dataset(dataset=dataset, config=baseline_config)

    def apply_temporary_constraints(
        self,
        dataset: ScenarioDataset,
        constraints: TemporaryConstraints,
    ) -> tuple[ScenarioDataset, AllocationConfig]:
        """Apply temporary what-if constraints in memory only.

        WHY deep copy:
        - Baseline and simulated paths must be fully independent so simulation
          does not leak temporary overrides into baseline references.
        """

        self._validate_temporary_constraints(constraints=constraints, dataset=dataset)
        mutated_dataset = copy.deepcopy(dataset)

        if constraints.capacity_override:
            room_by_id = {room.room_id: room for room in mutated_dataset.rooms}
            for room_id, new_capacity in constraints.capacity_override.items():
                room_by_id[room_id] = replace(room_by_id[room_id], capacity=int(new_capacity))
            mutated_dataset = replace(
                mutated_dataset,
                rooms=[room_by_id[room_id] for room_id in sorted(room_by_id)],
            )

        if constraints.priority_adjustment:
            adjusted_requests_by_slot: dict[tuple[str, str], list[AllocationRequest]] = {}
            for key in sorted(mutated_dataset.requests_by_slot):
                adjusted_requests_by_slot[key] = []
                for request in mutated_dataset.requests_by_slot[key]:
                    weight = constraints.priority_adjustment.get(request.stakeholder_id, 1.0)
                    adjusted_requests_by_slot[key].append(
                        replace(
                            request,
                            priority_weight=float(request.priority_weight * weight),
                        )
                    )
            mutated_dataset = replace(
                mutated_dataset,
                requests_by_slot=adjusted_requests_by_slot,
            )

        simulation_config = self._build_simulation_config(
            idle_threshold=constraints.idle_threshold,
            stakeholder_cap=constraints.stakeholder_cap,
        )
        return mutated_dataset, simulation_config

    def compute_metrics(
        self,
        dataset: ScenarioDataset,
        result: SimulationRunResult,
    ) -> SimulationMetrics:
        total_rooms = len(dataset.rooms)
        utilized_room_ids = {allocation.room_id for allocation in result.allocations}
        total_rooms_utilized = len(utilized_room_ids)
        utilization_rate = float(total_rooms_utilized / total_rooms) if total_rooms else 0.0

        prediction_lookup: dict[tuple[str, str, int], float] = {}
        for (requested_date, requested_time_slot), predictions in dataset.predictions_by_slot.items():
            for prediction in predictions:
                prediction_lookup[(requested_date, requested_time_slot, prediction.room_id)] = (
                    prediction.idle_probability
                )

        idle_values = [
            prediction_lookup.get(
                (
                    allocation.requested_date,
                    allocation.requested_time_slot,
                    allocation.room_id,
                ),
                0.0,
            )
            for allocation in result.allocations
        ]
        average_idle_probability_utilized = (
            float(sum(idle_values) / len(idle_values))
            if idle_values
            else 0.0
        )

        return SimulationMetrics(
            utilization_rate=utilization_rate,
            requests_satisfied=len(result.allocations),
            objective_value=float(result.objective_value),
            total_rooms_utilized=total_rooms_utilized,
            average_idle_probability_utilized=average_idle_probability_utilized,
            fairness_metric=float(result.fairness_metric),
        )

    def compare_results(
        self,
        baseline: SimulationMetrics,
        simulation: SimulationMetrics,
    ) -> dict[str, float | int]:
        return {
            "utilization_change": simulation.utilization_rate - baseline.utilization_rate,
            "request_change": simulation.requests_satisfied - baseline.requests_satisfied,
            "objective_change": simulation.objective_value - baseline.objective_value,
            "total_rooms_utilized_change": simulation.total_rooms_utilized - baseline.total_rooms_utilized,
            "avg_idle_probability_change": (
                simulation.average_idle_probability_utilized
                - baseline.average_idle_probability_utilized
            ),
            "fairness_change": simulation.fairness_metric - baseline.fairness_metric,
        }

    def run_simulation(
        self,
        constraints: TemporaryConstraints,
    ) -> dict[str, dict[str, float | int]]:
        run_id = str(uuid4())
        logger.info(
            (
                "Simulation run started | run_id=%s | idle_threshold=%s | "
                "stakeholder_cap=%s | capacity_override=%s | priority_adjustment=%s"
            ),
            run_id,
            constraints.idle_threshold,
            constraints.stakeholder_cap,
            constraints.capacity_override or {},
            constraints.priority_adjustment or {},
        )

        dataset = self._load_dataset()
        baseline_result = self.compute_baseline(dataset)
        baseline_metrics = self.compute_metrics(dataset, baseline_result)

        constrained_dataset, simulation_config = self.apply_temporary_constraints(
            dataset=dataset,
            constraints=constraints,
        )
        simulation_result = self._optimize_dataset(
            dataset=constrained_dataset,
            config=simulation_config,
        )
        simulation_metrics = self.compute_metrics(constrained_dataset, simulation_result)
        delta = self.compare_results(
            baseline=baseline_metrics,
            simulation=simulation_metrics,
        )

        logger.info(
            (
                "Simulation run completed | run_id=%s | baseline_obj=%.6f | "
                "simulation_obj=%.6f | request_delta=%s | utilization_delta=%.6f"
            ),
            run_id,
            baseline_metrics.objective_value,
            simulation_metrics.objective_value,
            delta["request_change"],
            float(delta["utilization_change"]),
        )
        return {
            "baseline": baseline_metrics.to_api_dict(),
            "simulation": simulation_metrics.to_api_dict(),
            "delta": delta,
        }
