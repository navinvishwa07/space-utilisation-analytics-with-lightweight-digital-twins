"""FastAPI application bootstrap and lifecycle wiring."""

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
    """Build the app with explicit startup lifecycle dependencies."""
    settings = get_settings()
    repository = DataRepository(settings)
    prediction_service = AvailabilityPredictionService(
        repository=repository,
        settings=settings,
    )
    matching_service = AllocationOptimizationService(
        repository=repository,
        settings=settings,
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
        startup(app)
        yield

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )
    app.include_router(prediction_router)
    app.include_router(dashboard_router)

    app.state.repository = repository
    app.state.prediction_service = prediction_service
    app.state.matching_service = matching_service
    app.state.simulation_service = simulation_service
    app.state.auth_service = auth_service
    app.state.dashboard_service = dashboard_service

    return app


def startup(app: FastAPI | None = None) -> None:
    """Initialize schema, seed data, and train prediction model once."""
    target_app = app or create_app()
    repository: DataRepository = target_app.state.repository
    prediction_service: AvailabilityPredictionService = target_app.state.prediction_service

    repository.initialize_database()
    repository.seed_synthetic_data()
    prediction_service.train_model()
    logger.info("System startup completed")


app = create_app()


if __name__ == "__main__":
    startup(app)
