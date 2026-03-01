from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytest.importorskip("ortools")

from backend.controllers.allocation_controller import router as allocation_router
from backend.controllers.dashboard_controller import router as dashboard_router
from backend.repository.data_repository import DataRepository
from backend.services.auth_service import AuthService
from backend.services.dashboard_service import DashboardWorkflowService
from backend.services.matching_service import AllocationOptimizationService
from backend.services.prediction_service import AvailabilityPredictionService
from backend.services.simulation_service import SimulationService
from backend.utils.config import get_settings


def _build_test_settings(tmp_path, filename: str, admin_token: str):
    get_settings.cache_clear()
    base = get_settings()
    return replace(
        base,
        database_path=tmp_path / filename,
        prediction_min_training_rows=1,
        allocation_solver_max_time_seconds=5,
        allocation_cp_sat_workers=2,
        simulation_cp_sat_workers=1,
        simulation_solver_random_seed=42,
        admin_token=admin_token,
    )


def _build_test_app(tmp_path, admin_token: str) -> tuple[FastAPI, DataRepository]:
    settings = _build_test_settings(tmp_path, "dashboard_flow.db", admin_token)
    repository = DataRepository(settings)
    repository.initialize_database()
    repository.seed_synthetic_data()

    prediction_service = AvailabilityPredictionService(repository=repository, settings=settings)
    prediction_service.train_model()
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

    app = FastAPI()
    app.include_router(allocation_router)
    app.include_router(dashboard_router)
    app.state.repository = repository
    app.state.prediction_service = prediction_service
    app.state.matching_service = matching_service
    app.state.simulation_service = simulation_service
    app.state.auth_service = auth_service
    app.state.dashboard_service = dashboard_service
    return app, repository


def test_dashboard_end_to_end_flow(tmp_path):
    admin_token = "secret-admin-token"
    app, repository = _build_test_app(tmp_path, admin_token)

    target_date = "2026-02-28"
    target_slot = "09-11"
    repository.create_request(18, target_date, target_slot, 1.4, "dept_a")
    repository.create_request(22, target_date, target_slot, 1.1, "dept_b")
    repository.create_request(10, target_date, target_slot, 0.9, "dept_a")

    client = TestClient(app)

    unauth_predict = client.post(
        "/predict",
        json={"date": target_date, "time_slot": target_slot},
    )
    assert unauth_predict.status_code == 401

    demo_context_response = client.get("/demo_context")
    assert demo_context_response.status_code == 200
    demo_context = demo_context_response.json()
    assert "pending_windows" in demo_context

    login_response = client.post(
        "/login",
        json={"admin_token": admin_token},
    )
    assert login_response.status_code == 200
    access_token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    predict_response = client.post(
        "/predict",
        json={"date": target_date, "time_slot": target_slot},
        headers=headers,
    )
    assert predict_response.status_code == 200
    predict_payload = predict_response.json()
    assert len(predict_payload["predictions"]) == 10

    before_logs = repository.count_allocation_logs()
    allocate_response = client.post(
        "/allocate",
        json={
            "requested_date": target_date,
            "requested_time_slot": target_slot,
            "idle_probability_threshold": 0.5,
            "stakeholder_usage_cap": 0.7,
        },
        headers=headers,
    )
    assert allocate_response.status_code == 200
    allocate_payload = allocate_response.json()
    assert "allocations" in allocate_payload
    assert repository.count_allocation_logs() == before_logs

    simulate_response = client.post(
        "/simulate",
        json={
            "stakeholder_priority_weight": 1.2,
            "idle_probability_threshold": 0.55,
            "stakeholder_usage_cap": 0.75,
        },
        headers=headers,
    )
    assert simulate_response.status_code == 200
    assert "baseline" in simulate_response.json()

    metrics_response = client.get("/metrics", headers=headers)
    assert metrics_response.status_code == 200
    metrics_payload = metrics_response.json()
    assert "baseline_idle_activation_rate" in metrics_payload
    assert "simulated_idle_activation_rate" in metrics_payload
    assert "allocation_efficiency_score" in metrics_payload
    assert "utilization_delta_percentage" in metrics_payload

    approve_response = client.post("/approve", headers=headers)
    assert approve_response.status_code == 200
    approve_payload = approve_response.json()
    assert approve_payload["status"] == "APPROVED"
    assert repository.count_allocation_logs() >= before_logs + approve_payload["approved_allocations_count"]


def test_login_rejects_invalid_admin_token(tmp_path):
    app, _ = _build_test_app(tmp_path, "real-admin-token")
    client = TestClient(app)
    response = client.post("/login", json={"admin_token": "wrong-token"})
    assert response.status_code == 401
