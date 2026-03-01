"""HTTP controller layer for availability prediction."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from backend.controllers.dependencies import get_dashboard_service, require_admin
from backend.services.matching_service import (
    AllocationOptimizationService,
    AllocationValidationError,
    SolverDependencyError,
)
from backend.services.prediction_service import (
    AvailabilityPredictionService,
    ModelNotReadyError,
    PredictionValidationError,
    RoomNotFoundError,
)
from backend.services.dashboard_service import DashboardValidationError, DashboardWorkflowService
from backend.services.simulation_service import SimulationValidationError
from backend.utils.config import get_settings
from backend.utils.logger import get_logger


logger = get_logger(__name__)
settings = get_settings()

router = APIRouter(tags=["prediction"])


class AvailabilityPredictionRequest(BaseModel):
    """Input DTO validated before entering service layer."""

    room_id: int = Field(gt=0)
    date: date
    time_slot: str = Field(pattern=settings.prediction_time_slot_regex)

    @field_validator("time_slot")
    @classmethod
    def validate_time_slot_boundaries(cls, value: str) -> str:
        start_hour, end_hour = (int(item) for item in value.split("-"))
        if start_hour >= end_hour:
            raise ValueError("time_slot start hour must be less than end hour")
        return value


class AvailabilityPredictionResponse(BaseModel):
    """Output DTO constrained to probability bounds."""

    idle_probability: float = Field(ge=0.0, le=1.0)
    confidence_score: float = Field(ge=0.0, le=1.0)


class AllocationDecisionResponse(BaseModel):
    request_id: int = Field(gt=0)
    room_id: int = Field(gt=0)
    score: float = Field(ge=0.0)


class OptimizeAllocationRequest(BaseModel):
    requested_date: date
    requested_time_slot: str = Field(pattern=settings.prediction_time_slot_regex)
    idle_probability_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    stakeholder_usage_cap: float | None = Field(default=None, gt=0.0, le=1.0)

    @field_validator("requested_time_slot")
    @classmethod
    def validate_requested_slot_boundaries(cls, value: str) -> str:
        start_hour, end_hour = (int(item) for item in value.split("-"))
        if start_hour >= end_hour:
            raise ValueError("requested_time_slot start hour must be less than end hour")
        return value


class OptimizeAllocationResponse(BaseModel):
    allocations: list[AllocationDecisionResponse]
    objective_value: float = Field(ge=0.0)
    fairness_metric: float = Field(ge=0.0, le=1.0)


class TemporaryConstraintsRequest(BaseModel):
    idle_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    stakeholder_cap: float | None = Field(default=None, gt=0.0, le=1.0)
    capacity_override: dict[int, int] | None = None
    priority_adjustment: dict[str, float] | None = None

    @field_validator("capacity_override")
    @classmethod
    def validate_capacity_override(cls, value: dict[int, int] | None) -> dict[int, int] | None:
        if value is None:
            return None
        for room_id, capacity in value.items():
            if room_id <= 0:
                raise ValueError("capacity_override room_id must be positive")
            if capacity <= 0:
                raise ValueError("capacity_override capacity must be > 0")
        return value

    @field_validator("priority_adjustment")
    @classmethod
    def validate_priority_adjustment(
        cls,
        value: dict[str, float] | None,
    ) -> dict[str, float] | None:
        if value is None:
            return None
        for stakeholder, weight in value.items():
            if not stakeholder.strip():
                raise ValueError("priority_adjustment stakeholder key must be non-empty")
            if weight <= 0.0:
                raise ValueError("priority_adjustment weight must be > 0")
        return value


class SimulateRequest(BaseModel):
    temporary_constraints: TemporaryConstraintsRequest = Field(
        default_factory=TemporaryConstraintsRequest
    )
    stakeholder_priority_weight: float | None = Field(default=None, gt=0.0)
    idle_probability_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    stakeholder_usage_cap: float | None = Field(default=None, gt=0.0, le=1.0)


class SimulationMetricsResponse(BaseModel):
    utilization_rate: float = Field(ge=0.0, le=1.0)
    requests_satisfied: int = Field(ge=0)
    objective_value: float = Field(ge=0.0)
    total_rooms_utilized: int = Field(ge=0)
    average_idle_probability_utilized: float = Field(ge=0.0, le=1.0)
    fairness_metric: float = Field(ge=0.0, le=1.0)


class SimulationDeltaResponse(BaseModel):
    utilization_change: float
    request_change: int
    objective_change: float
    total_rooms_utilized_change: int
    avg_idle_probability_change: float
    fairness_change: float


class SimulateResponse(BaseModel):
    baseline: SimulationMetricsResponse
    simulation: SimulationMetricsResponse
    delta: SimulationDeltaResponse


def get_prediction_service(request: Request) -> AvailabilityPredictionService:
    service = getattr(request.app.state, "prediction_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Prediction service is not initialized",
        )
    return service


def get_matching_service(request: Request) -> AllocationOptimizationService:
    service = getattr(request.app.state, "matching_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Matching service is not initialized",
        )
    return service


@router.post(
    "/predict_availability",
    response_model=AvailabilityPredictionResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_admin)],
)
async def predict_availability(
    payload: AvailabilityPredictionRequest,
    service: AvailabilityPredictionService = Depends(get_prediction_service),
) -> AvailabilityPredictionResponse:
    """Run inference only; model training lifecycle is managed at startup."""
    try:
        result = service.predict(
            room_id=payload.room_id,
            date=payload.date.isoformat(),
            time_slot=payload.time_slot,
        )
        return AvailabilityPredictionResponse(**result)
    except PredictionValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RoomNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ModelNotReadyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.exception("Unexpected inference failure")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate prediction",
        ) from exc


@router.post(
    "/optimize_allocation",
    response_model=OptimizeAllocationResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_admin)],
)
async def optimize_allocation(
    payload: OptimizeAllocationRequest,
    service: AllocationOptimizationService = Depends(get_matching_service),
) -> OptimizeAllocationResponse:
    """Run demand forecast and CP-SAT allocation optimization."""
    try:
        result = service.optimize_allocation(
            requested_date=payload.requested_date.isoformat(),
            requested_time_slot=payload.requested_time_slot,
            idle_probability_threshold=payload.idle_probability_threshold,
            stakeholder_usage_cap=payload.stakeholder_usage_cap,
        )
        return OptimizeAllocationResponse(
            allocations=[
                AllocationDecisionResponse(
                    request_id=item.request_id,
                    room_id=item.room_id,
                    score=item.score,
                )
                for item in result.allocations
            ],
            objective_value=result.objective_value,
            fairness_metric=result.fairness_metric,
        )
    except AllocationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except SolverDependencyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.exception("Unexpected optimization failure")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to optimize allocation",
        ) from exc


@router.post(
    "/simulate",
    response_model=SimulateResponse,
    status_code=status.HTTP_200_OK,
)
async def simulate(
    payload: SimulateRequest,
    workflow_service: DashboardWorkflowService = Depends(get_dashboard_service),
    _: None = Depends(require_admin),
) -> SimulateResponse:
    """Run an isolated in-memory what-if simulation."""
    try:
        effective_idle_threshold = (
            payload.idle_probability_threshold
            if payload.idle_probability_threshold is not None
            else payload.temporary_constraints.idle_threshold
        )
        effective_stakeholder_cap = (
            payload.stakeholder_usage_cap
            if payload.stakeholder_usage_cap is not None
            else payload.temporary_constraints.stakeholder_cap
        )
        result = workflow_service.run_simulation(
            idle_probability_threshold=effective_idle_threshold,
            stakeholder_usage_cap=effective_stakeholder_cap,
            stakeholder_priority_weight=payload.stakeholder_priority_weight,
            capacity_override=payload.temporary_constraints.capacity_override,
            priority_adjustment=payload.temporary_constraints.priority_adjustment,
        )
        return SimulateResponse(**result)
    except (SimulationValidationError, DashboardValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except AllocationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except SolverDependencyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.exception("Unexpected simulation failure")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to run simulation",
        ) from exc
