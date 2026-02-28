"""Dashboard orchestration service for auth-protected operator workflow."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any, Optional

from backend.repository.data_repository import DataRepository
from backend.services.matching_service import AllocationOptimizationService
from backend.services.prediction_service import AvailabilityPredictionService
from backend.services.simulation_service import SimulationService, TemporaryConstraints
from backend.utils.config import Settings, get_settings


class DashboardValidationError(Exception):
    """Raised when dashboard workflow inputs are invalid."""


class AllocationDraftNotFoundError(DashboardValidationError):
    """Raised when approve is called before allocate preview."""


@dataclass(frozen=True)
class AllocationDraft:
    requested_date: str
    requested_time_slot: str
    idle_probability_threshold: float | None
    stakeholder_usage_cap: float | None


class DashboardWorkflowService:
    """Coordinates predict -> allocate -> simulate -> approve flow."""

    def __init__(
        self,
        repository: Optional[DataRepository] = None,
        prediction_service: Optional[AvailabilityPredictionService] = None,
        matching_service: Optional[AllocationOptimizationService] = None,
        simulation_service: Optional[SimulationService] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._repository = repository or DataRepository(self._settings)
        self._prediction_service = prediction_service or AvailabilityPredictionService(
            repository=self._repository,
            settings=self._settings,
        )
        self._matching_service = matching_service or AllocationOptimizationService(
            repository=self._repository,
            settings=self._settings,
        )
        self._simulation_service = simulation_service or SimulationService(
            repository=self._repository,
            settings=self._settings,
            prediction_service=self._prediction_service,
        )
        self._lock = RLock()
        self._latest_metrics: dict[str, float] | None = None
        self._pending_allocation_draft: AllocationDraft | None = None

    def predict_idle_probabilities(
        self,
        *,
        target_date: str,
        target_time_slot: str,
        room_ids: list[int] | None,
    ) -> dict[str, list[dict[str, float | int | str]]]:
        if room_ids:
            unique_room_ids = sorted({int(room_id) for room_id in room_ids})
        else:
            unique_room_ids = [room.room_id for room in self._repository.list_rooms_for_allocation()]

        prediction_rows: list[dict[str, float | int | str]] = []
        for room_id in unique_room_ids:
            prediction = self._prediction_service.predict(
                room_id=room_id,
                date=target_date,
                time_slot=target_time_slot,
                persist=True,
            )
            prediction_rows.append(
                {
                    "room_id": room_id,
                    "date": target_date,
                    "time_slot": target_time_slot,
                    "predicted_idle_probability": float(prediction["idle_probability"]),
                    "confidence_score": float(prediction["confidence_score"]),
                }
            )

        return {"predictions": prediction_rows}

    def preview_allocation(
        self,
        *,
        requested_date: str,
        requested_time_slot: str,
        idle_probability_threshold: float | None,
        stakeholder_usage_cap: float | None,
    ) -> dict[str, Any]:
        result = self._matching_service.optimize_allocation(
            requested_date=requested_date,
            requested_time_slot=requested_time_slot,
            idle_probability_threshold=idle_probability_threshold,
            stakeholder_usage_cap=stakeholder_usage_cap,
            persist_outputs=False,
        )
        requests = self._repository.list_pending_requests(
            requested_date=requested_date,
            requested_time_slot=requested_time_slot,
        )
        request_by_id = {request.request_id: request for request in requests}

        rows: list[dict[str, str | int | float | None]] = []
        for item in result.allocations:
            request = request_by_id.get(item.request_id)
            if request is None:
                continue
            rows.append(
                {
                    "room_id": item.room_id,
                    "stakeholder": request.stakeholder_id,
                    "time_slot": request.requested_time_slot,
                    "allocation_score": float(item.score),
                    "priority_weight": float(request.priority_weight),
                    "constraint_status": "SATISFIED",
                }
            )

        for request_id in result.unassigned_request_ids:
            request = request_by_id.get(request_id)
            if request is None:
                continue
            rows.append(
                {
                    "room_id": None,
                    "stakeholder": request.stakeholder_id,
                    "time_slot": request.requested_time_slot,
                    "allocation_score": 0.0,
                    "priority_weight": float(request.priority_weight),
                    "constraint_status": "UNASSIGNED",
                }
            )

        with self._lock:
            self._pending_allocation_draft = AllocationDraft(
                requested_date=requested_date,
                requested_time_slot=requested_time_slot,
                idle_probability_threshold=idle_probability_threshold,
                stakeholder_usage_cap=stakeholder_usage_cap,
            )

        return {
            "allocations": rows,
            "objective_value": float(result.objective_value),
            "fairness_metric": float(result.fairness_metric),
            "unassigned_request_ids": list(result.unassigned_request_ids),
        }

    def _build_priority_adjustment(
        self,
        stakeholder_priority_weight: float | None,
        explicit_priority_adjustment: dict[str, float] | None,
    ) -> dict[str, float] | None:
        adjustments = dict(explicit_priority_adjustment or {})
        if stakeholder_priority_weight is not None:
            if stakeholder_priority_weight <= 0.0:
                raise DashboardValidationError("stakeholder_priority_weight must be > 0")
            stakeholders = sorted(
                {
                    request.stakeholder_id
                    for request in self._repository.list_all_pending_requests()
                }
            )
            for stakeholder in stakeholders:
                current = adjustments.get(stakeholder, 1.0)
                adjustments[stakeholder] = float(current * stakeholder_priority_weight)
        return adjustments or None

    def _to_metrics_payload(self, simulation_result: dict[str, Any]) -> dict[str, float]:
        baseline = simulation_result["baseline"]
        simulation = simulation_result["simulation"]
        delta = simulation_result["delta"]
        return {
            "baseline_idle_activation_rate": float(baseline["utilization_rate"]),
            "simulated_idle_activation_rate": float(simulation["utilization_rate"]),
            "allocation_efficiency_score": float(simulation["objective_value"]),
            "utilization_delta_percentage": float(delta["utilization_change"]) * 100.0,
        }

    def run_simulation(
        self,
        *,
        idle_probability_threshold: float | None,
        stakeholder_usage_cap: float | None,
        stakeholder_priority_weight: float | None,
        capacity_override: dict[int, int] | None,
        priority_adjustment: dict[str, float] | None,
    ) -> dict[str, Any]:
        effective_priority_adjustment = self._build_priority_adjustment(
            stakeholder_priority_weight=stakeholder_priority_weight,
            explicit_priority_adjustment=priority_adjustment,
        )
        result = self._simulation_service.run_simulation(
            TemporaryConstraints(
                idle_threshold=idle_probability_threshold,
                stakeholder_cap=stakeholder_usage_cap,
                capacity_override=capacity_override,
                priority_adjustment=effective_priority_adjustment,
            )
        )
        metrics_payload = self._to_metrics_payload(result)
        with self._lock:
            self._latest_metrics = metrics_payload
        return {
            "baseline": result["baseline"],
            "simulation": result["simulation"],
            "delta": result["delta"],
            "metrics": metrics_payload,
        }

    def approve_latest_allocation(self) -> dict[str, Any]:
        with self._lock:
            draft = self._pending_allocation_draft
        if draft is None:
            raise AllocationDraftNotFoundError(
                "No allocation draft found. Run /allocate before /approve."
            )

        result = self._matching_service.optimize_allocation(
            requested_date=draft.requested_date,
            requested_time_slot=draft.requested_time_slot,
            idle_probability_threshold=draft.idle_probability_threshold,
            stakeholder_usage_cap=draft.stakeholder_usage_cap,
            persist_outputs=True,
        )
        with self._lock:
            self._pending_allocation_draft = None
        return {
            "status": "APPROVED",
            "approved_allocations_count": len(result.allocations),
            "objective_value": float(result.objective_value),
            "fairness_metric": float(result.fairness_metric),
        }

    def get_metrics(self) -> dict[str, float]:
        with self._lock:
            if self._latest_metrics is not None:
                return dict(self._latest_metrics)
        simulation_result = self.run_simulation(
            idle_probability_threshold=None,
            stakeholder_usage_cap=None,
            stakeholder_priority_weight=None,
            capacity_override=None,
            priority_adjustment=None,
        )
        return dict(simulation_result["metrics"])
