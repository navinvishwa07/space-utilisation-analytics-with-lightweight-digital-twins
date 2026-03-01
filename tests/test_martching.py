from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytest.importorskip("ortools")

from backend.controllers.allocation_controller import router
from backend.repository.data_repository import DataRepository
from backend.services.matching_service import AllocationOptimizationService
from backend.utils.config import get_settings


def _build_test_settings(tmp_path, filename: str):
    base = get_settings()
    return replace(
        base,
        database_path=tmp_path / filename,
        allocation_solver_max_time_seconds=5,
        allocation_cp_sat_workers=2,
        allocation_idle_probability_threshold=0.5,
        allocation_stakeholder_usage_cap=0.6,
    )


def _seed_predictions(repository: DataRepository, target_date: str, target_slot: str) -> None:
    for room_id in range(1, 11):
        repository.save_prediction(
            room_id=room_id,
            date=target_date,
            time_slot=target_slot,
            idle_probability=0.9 if room_id <= 5 else 0.3,
        )


def test_optimize_allocation_service_persists_results(tmp_path):
    settings = _build_test_settings(tmp_path, "matching_service.db")
    repository = DataRepository(settings)
    repository.initialize_database()
    repository.seed_synthetic_data()

    target_date = "2026-02-23"
    target_slot = "09-11"
    _seed_predictions(repository, target_date, target_slot)

    request_ids = [
        repository.create_request(20, target_date, target_slot, 2.0, "dept_a"),
        repository.create_request(15, target_date, target_slot, 1.5, "dept_b"),
        repository.create_request(10, target_date, target_slot, 1.0, "dept_a"),
    ]
    repository.create_request(25, "2026-02-20", target_slot, 1.0, "dept_a")
    repository.create_request(30, "2026-02-21", target_slot, 1.0, "dept_b")

    service = AllocationOptimizationService(repository=repository, settings=settings)
    result = service.optimize_allocation(
        requested_date=target_date,
        requested_time_slot=target_slot,
    )

    assert result.objective_value >= 0.0
    assert 0.0 <= result.fairness_metric <= 1.0
    assert repository.count_forecast_logs() >= 1
    assert repository.count_allocation_logs() == len(result.allocations)
    for request_id in request_ids:
        status = repository.get_request_status(request_id)
        if request_id in {item.request_id for item in result.allocations}:
            assert status == "ALLOCATED"
        else:
            assert status == "PENDING"


def test_optimize_allocation_service_zero_idle_rooms(tmp_path):
    settings = _build_test_settings(tmp_path, "matching_zero_idle.db")
    repository = DataRepository(settings)
    repository.initialize_database()
    repository.seed_synthetic_data()

    target_date = "2026-02-23"
    target_slot = "11-13"
    for room_id in range(1, 11):
        repository.save_prediction(
            room_id=room_id,
            date=target_date,
            time_slot=target_slot,
            idle_probability=0.2,
        )
    first_request_id = repository.create_request(10, target_date, target_slot, 1.0, "dept_x")
    second_request_id = repository.create_request(15, target_date, target_slot, 1.0, "dept_y")

    service = AllocationOptimizationService(repository=repository, settings=settings)
    result = service.optimize_allocation(
        requested_date=target_date,
        requested_time_slot=target_slot,
        idle_probability_threshold=0.8,
    )

    assert result.allocations == []
    assert result.objective_value == 0.0
    assert set(result.unassigned_request_ids) == {first_request_id, second_request_id}
    assert repository.count_allocation_logs() == 0


def test_optimize_allocation_endpoint_success(tmp_path):
    settings = _build_test_settings(tmp_path, "matching_endpoint.db")
    repository = DataRepository(settings)
    repository.initialize_database()
    repository.seed_synthetic_data()

    target_date = "2026-02-24"
    target_slot = "14-16"
    _seed_predictions(repository, target_date, target_slot)

    repository.create_request(12, target_date, target_slot, 1.2, "stakeholder_1")
    repository.create_request(18, target_date, target_slot, 1.0, "stakeholder_2")

    service = AllocationOptimizationService(repository=repository, settings=settings)
    app = FastAPI()
    app.include_router(router)
    app.state.matching_service = service
    app.state.prediction_service = None

    client = TestClient(app)
    response = client.post(
        "/optimize_allocation",
        json={
            "requested_date": target_date,
            "requested_time_slot": target_slot,
            "idle_probability_threshold": 0.5,
            "stakeholder_usage_cap": 0.7,
        },
        headers={"Authorization": "Bearer admin-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "allocations" in body
    assert "objective_value" in body
    assert "fairness_metric" in body
    assert body["objective_value"] >= 0.0
    assert 0.0 <= body["fairness_metric"] <= 1.0


def test_optimize_allocation_single_stakeholder_cap_still_allocates(tmp_path):
    settings = _build_test_settings(tmp_path, "matching_single_stakeholder.db")
    repository = DataRepository(settings)
    repository.initialize_database()
    repository.seed_synthetic_data()

    target_date = "2026-02-24"
    target_slot = "16-18"
    _seed_predictions(repository, target_date, target_slot)

    repository.create_request(10, target_date, target_slot, 1.2, "dept_only")
    repository.create_request(12, target_date, target_slot, 1.0, "dept_only")

    service = AllocationOptimizationService(repository=repository, settings=settings)
    result = service.optimize_allocation(
        requested_date=target_date,
        requested_time_slot=target_slot,
        stakeholder_usage_cap=0.5,
    )

    assert len(result.allocations) == 1
    assert len(result.unassigned_request_ids) == 1
