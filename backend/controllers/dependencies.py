"""Shared FastAPI dependency providers for controller layer."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.services.auth_service import (
    AdminTokenNotConfiguredError,
    AuthService,
    InvalidAdminTokenError,
)
from backend.services.dashboard_service import DashboardWorkflowService
from backend.utils.config import get_settings


bearer_scheme = HTTPBearer(auto_error=False)


def get_auth_service(request: Request) -> AuthService:
    service = getattr(request.app.state, "auth_service", None)
    if service is None:
        service = AuthService(settings=get_settings())
        request.app.state.auth_service = service
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth service is not initialized",
        )
    return service


def get_dashboard_service(request: Request) -> DashboardWorkflowService:
    service = getattr(request.app.state, "dashboard_service", None)
    if service is None:
        repository = getattr(request.app.state, "repository", None)
        prediction_service = getattr(request.app.state, "prediction_service", None)
        matching_service = getattr(request.app.state, "matching_service", None)
        simulation_service = getattr(request.app.state, "simulation_service", None)
        if (
            repository is not None
            and prediction_service is not None
            and matching_service is not None
            and simulation_service is not None
        ):
            service = DashboardWorkflowService(
                repository=repository,
                prediction_service=prediction_service,
                matching_service=matching_service,
                simulation_service=simulation_service,
                settings=get_settings(),
            )
            request.app.state.dashboard_service = service
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dashboard service is not initialized",
        )
    return service


async def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    auth_service: AuthService = Depends(get_auth_service),
) -> None:
    if not auth_service.auth_enabled:
        return
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header with Bearer token is required",
        )
    try:
        auth_service.validate_bearer_token(credentials.credentials)
    except (AdminTokenNotConfiguredError, InvalidAdminTokenError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
