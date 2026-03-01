"""
app.py — FastAPI application factory and startup lifecycle.

This is the WSGI/ASGI application object imported by uvicorn.
It wires all services, registers routers, and runs startup initialization.

Usage (via launcher):
    python main.py

Usage (direct uvicorn):
    uvicorn app:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.controllers.allocation_controller import router as prediction_router
from backend.controllers.dashboard_controller import router as dashboard_router
from backend.repository.data_repository import DataRepository
from backend.services.auth_service import AuthService
from backend.services.dashboard_service import DashboardWorkflowService
from backend.services.matching_service import AllocationOptimizationService
from backend.services.prediction_service import AvailabilityPredictionService
from backend.services.simulation_service import SimulationService
from backend.utils.config import get_settings
from backend.utils.logger import get_logger


logger = get_logger(__name__)


def create_app() -> FastAPI:
    """
    Build and wire the FastAPI application.

    Instantiates all services with explicit dependency injection via app.state.
    No global singletons — every dependency is traceable from this function.
    """
    settings = get_settings()

    # --- Repository (single SQLite connection factory) ---
    repository = DataRepository(settings)

    # --- Services (business logic, no direct DB access) ---
    prediction_service = AvailabilityPredictionService(
        repository=repository,
        settings=settings,
    )
    matching_service = AllocationOptimizationService(
        repository=repository,
        settings=settings,
        prediction_service=prediction_service,
    )
    simulation_service = SimulationService(
        repository=repository,
        settings=settings,
        prediction_service=prediction_service,
    )
    auth_service = AuthService(settings=settings)
    dashboard_service = DashboardWorkflowService(
        repository=repository,
        prediction_service=prediction_service,
        matching_service=matching_service,
        simulation_service=simulation_service,
        settings=settings,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Run startup initialization before accepting requests."""
        _startup(app)
        yield

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )

    # --- Routers ---
    app.include_router(prediction_router)
    app.include_router(dashboard_router)

    # --- Inject services into app.state for dependency resolution ---
    app.state.repository = repository
    app.state.prediction_service = prediction_service
    app.state.matching_service = matching_service
    app.state.simulation_service = simulation_service
    app.state.auth_service = auth_service
    app.state.dashboard_service = dashboard_service

    return app


def _startup(app: FastAPI) -> None:
    """
    Idempotent startup sequence. Safe to re-run on server restarts.

    Order matters:
      1. Schema must exist before seeding.
      2. BookingHistory must be populated before model training.
      3. Demo requests are seeded before model training (not required, but logical order).
      4. Model trains last — requires BookingHistory rows.
    """
    repository: DataRepository = app.state.repository
    prediction_service: AvailabilityPredictionService = app.state.prediction_service

    logger.info("Startup: initializing database schema")
    repository.initialize_database()

    logger.info("Startup: seeding synthetic booking history")
    repository.seed_synthetic_data()

    logger.info("Startup: seeding demo allocation requests (skipped if Requests table not empty)")
    repository.seed_demo_requests_if_empty()

    logger.info("Startup: training availability prediction model")
    prediction_service.train_model()

    logger.info("Startup complete — system ready")


# Module-level app object for uvicorn
app = create_app()
