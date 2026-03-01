"""Controller layer for admin dashboard workflow endpoints."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from backend.controllers.dependencies import get_auth_service, get_dashboard_service, require_admin
from backend.services.auth_service import (
    AdminTokenNotConfiguredError,
    AuthService,
    InvalidAdminTokenError,
)
from backend.services.dashboard_service import (
    AllocationDraftNotFoundError,
    DashboardValidationError,
    DashboardWorkflowService,
)
from backend.services.matching_service import AllocationValidationError, SolverDependencyError
from backend.services.prediction_service import (
    ModelNotReadyError,
    PredictionValidationError,
    RoomNotFoundError,
)
from backend.services.simulation_service import SimulationValidationError
from backend.utils.config import get_settings
from backend.utils.logger import get_logger


logger = get_logger(__name__)
settings = get_settings()

router = APIRouter(tags=["dashboard"])


class LoginRequest(BaseModel):
    admin_token: str = Field(min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class PredictRequest(BaseModel):
    date: date
    time_slot: str = Field(pattern=settings.prediction_time_slot_regex)
    room_ids: Optional[list[int]] = None

    @field_validator("room_ids")
    @classmethod
    def validate_room_ids(cls, value: Optional[list[int]]) -> Optional[list[int]]:
        if value is None:
            return None
        if not value:
            raise ValueError("room_ids must contain at least one room id when provided")
        for room_id in value:
            if room_id <= 0:
                raise ValueError("room_ids values must be positive integers")
        return value


class PredictRow(BaseModel):
    room_id: int = Field(gt=0)
    date: date
    time_slot: str = Field(pattern=settings.prediction_time_slot_regex)
    predicted_idle_probability: float = Field(ge=0.0, le=1.0)
    confidence_score: float = Field(ge=0.0, le=1.0)


class PredictResponse(BaseModel):
    predictions: list[PredictRow]


class AllocateRequest(BaseModel):
    requested_date: date
    requested_time_slot: str = Field(pattern=settings.prediction_time_slot_regex)
    idle_probability_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    stakeholder_usage_cap: float | None = Field(default=None, gt=0.0, le=1.0)


class AllocationRow(BaseModel):
    room_id: int | None = Field(default=None, gt=0)
    stakeholder: str = Field(min_length=1)
    time_slot: str = Field(pattern=settings.prediction_time_slot_regex)
    allocation_score: float = Field(ge=0.0)
    priority_weight: float = Field(gt=0.0)
    constraint_status: str = Field(min_length=1)


class AllocateResponse(BaseModel):
    allocations: list[AllocationRow]
    objective_value: float = Field(ge=0.0)
    fairness_metric: float = Field(ge=0.0, le=1.0)
    unassigned_request_ids: list[int]


class ApproveResponse(BaseModel):
    status: str
    approved_allocations_count: int = Field(ge=0)
    objective_value: float = Field(ge=0.0)
    fairness_metric: float = Field(ge=0.0, le=1.0)


class MetricsResponse(BaseModel):
    baseline_idle_activation_rate: float
    simulated_idle_activation_rate: float
    allocation_efficiency_score: float
    utilization_delta_percentage: float


class PendingWindowResponse(BaseModel):
    requested_date: date
    requested_time_slot: str = Field(pattern=settings.prediction_time_slot_regex)
    request_count: int = Field(ge=0)


class DemoContextResponse(BaseModel):
    default_date: date | None = None
    default_time_slot: str | None = Field(
        default=None,
        pattern=settings.prediction_time_slot_regex,
    )
    pending_windows: list[PendingWindowResponse]
    pending_request_count: int = Field(ge=0)


@router.get("/", include_in_schema=False)
async def dashboard_home() -> FileResponse:
    project_root = Path(__file__).resolve().parents[2]
    dashboard_file = project_root / "dashboard" / "index.html"
    return FileResponse(path=dashboard_file)


@router.get("/dashboard", include_in_schema=False)
async def dashboard_page() -> FileResponse:
    return await dashboard_home()


@router.get("/demo_context", response_model=DemoContextResponse, status_code=status.HTTP_200_OK)
async def demo_context(
    workflow_service: DashboardWorkflowService = Depends(get_dashboard_service),
) -> DemoContextResponse:
    try:
        result = workflow_service.get_demo_context()
        return DemoContextResponse(**result)
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.exception("Unexpected demo context failure")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load demo context",
        ) from exc


@router.post("/login", response_model=LoginResponse, status_code=status.HTTP_200_OK)
async def login(
    payload: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> LoginResponse:
    try:
        bearer = auth_service.login(payload.admin_token)
        return LoginResponse(access_token=bearer)
    except (AdminTokenNotConfiguredError, InvalidAdminTokenError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.exception("Unexpected login failure")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to login",
        ) from exc


@router.post(
    "/predict",
    response_model=PredictResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_admin)],
)
async def predict(
    payload: PredictRequest,
    workflow_service: DashboardWorkflowService = Depends(get_dashboard_service),
) -> PredictResponse:
    try:
        result = workflow_service.predict_idle_probabilities(
            target_date=payload.date.isoformat(),
            target_time_slot=payload.time_slot,
            room_ids=payload.room_ids,
        )
        return PredictResponse(**result)
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
        logger.exception("Unexpected dashboard prediction failure")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to run prediction workflow",
        ) from exc


@router.post(
    "/allocate",
    response_model=AllocateResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_admin)],
)
async def allocate(
    payload: AllocateRequest,
    workflow_service: DashboardWorkflowService = Depends(get_dashboard_service),
) -> AllocateResponse:
    try:
        result = workflow_service.preview_allocation(
            requested_date=payload.requested_date.isoformat(),
            requested_time_slot=payload.requested_time_slot,
            idle_probability_threshold=payload.idle_probability_threshold,
            stakeholder_usage_cap=payload.stakeholder_usage_cap,
        )
        return AllocateResponse(**result)
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
        logger.exception("Unexpected dashboard allocation failure")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to run allocation workflow",
        ) from exc


@router.post(
    "/approve",
    response_model=ApproveResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_admin)],
)
async def approve(
    workflow_service: DashboardWorkflowService = Depends(get_dashboard_service),
) -> ApproveResponse:
    try:
        result = workflow_service.approve_latest_allocation()
        return ApproveResponse(**result)
    except AllocationDraftNotFoundError as exc:
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
        logger.exception("Unexpected dashboard approval failure")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to approve allocation",
        ) from exc


@router.get(
    "/metrics",
    response_model=MetricsResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_admin)],
)
async def get_metrics(
    workflow_service: DashboardWorkflowService = Depends(get_dashboard_service),
) -> MetricsResponse:
    try:
        result = workflow_service.get_metrics()
        return MetricsResponse(**result)
    except (DashboardValidationError, SimulationValidationError) as exc:
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
        logger.exception("Unexpected dashboard metrics failure")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to compute metrics",
        ) from exc
