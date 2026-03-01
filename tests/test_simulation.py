from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytest.importorskip("ortools")

from backend.controllers.allocation_controller import router
from backend.repository.data_repository import DataRepository
from backend.services.prediction_service import AvailabilityPredictionService
from backend.services.simulation_service import SimulationService, TemporaryConstraints
from backend.utils.config import get_settings


def _build_test_settings(tmp_path, filename: str):
    base = get_settings()
    return replace(
        base,
        database_path=tmp_path / filename,
        prediction_min_training_rows=1,
        allocation_solver_max_time_seconds=5,
        simulation_cp_sat_workers=1,
        simulation_solver_random_seed=123,
    )


def _seed_predictions(repository: DataRepository, target_date: str, target_slot: str) -> None:
    for room_id in range(1, 11):
        repository.save_prediction(
            room_id=room_id,
            date=target_date,
            time_slot=target_slot,
            idle_probability=0.85 if room_id <= 6 else 0.40,
        )


def _seed_requests(repository: DataRepository, target_date: str, target_slot: str) -> list[int]:
    return [
        repository.create_request(18, target_date, target_slot, 1.4, "dept_a"),
        repository.create_request(22, target_date, target_slot, 1.1, "dept_b"),
        repository.create_request(10, target_date, target_slot, 0.9, "dept_a"),
    ]


def _build_simulation_service(
    repository: DataRepository,
    settings,
) -> SimulationService:
    prediction_service = AvailabilityPredictionService(
        repository=repository,
        settings=settings,
    )
    prediction_service.train_model()
    return SimulationService(
        repository=repository,
        settings=settings,
        prediction_service=prediction_service,
    )


def test_simulation_service_does_not_persist_allocation_side_effects(tmp_path):
    settings = _build_test_settings(tmp_path, "simulation_service.db")
    repository = DataRepository(settings)
    repository.initialize_database()
    repository.seed_synthetic_data()

    target_date = "2026-02-25"
    target_slot = "09-11"
    _seed_predictions(repository, target_date, target_slot)
    request_ids = _seed_requests(repository, target_date, target_slot)

    service = _build_simulation_service(repository, settings)

    before_allocation_logs = repository.count_allocation_logs()
    before_forecast_logs = repository.count_forecast_logs()
    before_prediction_logs = repository.count_predictions()

    result = service.run_simulation(
        TemporaryConstraints(
            idle_threshold=0.55,
            stakeholder_cap=0.70,
            capacity_override={1: 35, 2: 55},
            priority_adjustment={"dept_a": 1.2},
        )
    )

    assert "baseline" in result
    assert "simulation" in result
    assert "delta" in result
    assert repository.count_allocation_logs() == before_allocation_logs
    assert repository.count_forecast_logs() == before_forecast_logs
    assert repository.count_predictions() == before_prediction_logs
    for request_id in request_ids:
        assert repository.get_request_status(request_id) == "PENDING"


def test_simulation_service_is_deterministic_for_same_inputs(tmp_path):
    settings = _build_test_settings(tmp_path, "simulation_deterministic.db")
    repository = DataRepository(settings)
    repository.initialize_database()
    repository.seed_synthetic_data()

    target_date = "2026-02-26"
    target_slot = "11-13"
    _seed_predictions(repository, target_date, target_slot)
    _seed_requests(repository, target_date, target_slot)

    service = _build_simulation_service(repository, settings)
    constraints = TemporaryConstraints(
        idle_threshold=0.60,
        stakeholder_cap=0.65,
        capacity_override={3: 50},
        priority_adjustment={"dept_b": 1.5},
    )

    first = service.run_simulation(constraints)
    second = service.run_simulation(constraints)

    assert first == second


def test_simulate_endpoint_validates_unknown_capacity_override_room(tmp_path):
    settings = _build_test_settings(tmp_path, "simulation_endpoint.db")
    repository = DataRepository(settings)
    repository.initialize_database()
    repository.seed_synthetic_data()

    target_date = "2026-02-27"
    target_slot = "14-16"
    _seed_predictions(repository, target_date, target_slot)
    _seed_requests(repository, target_date, target_slot)

    simulation_service = _build_simulation_service(repository, settings)

    app = FastAPI()
    app.include_router(router)
    app.state.repository = repository
    app.state.prediction_service = None
    app.state.matching_service = None
    app.state.simulation_service = simulation_service

    client = TestClient(app)
    response = client.post(
        "/simulate",
        json={
            "temporary_constraints": {
                "capacity_override": {"9999": 25}
            }
        },
        headers={"Authorization": "Bearer admin-token"},
    )

    assert response.status_code == 400
    assert "unknown room_id" in response.json()["detail"]
