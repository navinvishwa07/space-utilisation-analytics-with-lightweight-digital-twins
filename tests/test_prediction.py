from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.controllers.allocation_controller import router
from backend.controllers.dashboard_controller import router as dashboard_router
from backend.repository.data_repository import DataRepository
from backend.services.auth_service import AuthService
from backend.services.prediction_service import AvailabilityPredictionService
from backend.utils.config import get_settings


def _build_test_settings(tmp_path, filename: str):
    base = get_settings()
    return replace(
        base,
        database_path=tmp_path / filename,
        prediction_min_training_rows=1,
    )


def _login(client: TestClient, admin_token: str = "admin-token") -> dict[str, str]:
    response = client.post("/login", json={"admin_token": admin_token})
    assert response.status_code == 200
    access_token = response.json()["access_token"]
    return {"Authorization": f"Bearer {access_token}"}


def test_prediction_service_returns_probabilities_and_persists(tmp_path):
    settings = _build_test_settings(tmp_path, "service_test.db")
    repository = DataRepository(settings)
    repository.initialize_database()
    repository.seed_synthetic_data()

    service = AvailabilityPredictionService(repository=repository, settings=settings)
    service.train_model()

    result = service.predict(
        room_id=1,
        date=datetime.now(timezone.utc).date().isoformat(),
        time_slot="09-11",
    )

    assert 0.0 <= result["idle_probability"] <= 1.0
    assert 0.0 <= result["confidence_score"] <= 1.0
    assert repository.count_predictions() == 1


def test_predict_availability_endpoint_success(tmp_path):
    settings = _build_test_settings(tmp_path, "api_test.db")
    repository = DataRepository(settings)
    repository.initialize_database()
    repository.seed_synthetic_data()
    service = AvailabilityPredictionService(repository=repository, settings=settings)
    service.train_model()

    app = FastAPI()
    app.include_router(router)
    app.include_router(dashboard_router)
    app.state.prediction_service = service
    app.state.auth_service = AuthService(settings=settings)

    client = TestClient(app)
    headers = _login(client)
    response = client.post(
        "/predict_availability",
        json={
            "room_id": 1,
            "date": datetime.now(timezone.utc).date().isoformat(),
            "time_slot": "11-13",
        },
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert 0.0 <= body["idle_probability"] <= 1.0
    assert 0.0 <= body["confidence_score"] <= 1.0


def test_predict_availability_endpoint_room_not_found(tmp_path):
    settings = _build_test_settings(tmp_path, "api_404_test.db")
    repository = DataRepository(settings)
    repository.initialize_database()
    repository.seed_synthetic_data()
    service = AvailabilityPredictionService(repository=repository, settings=settings)
    service.train_model()

    app = FastAPI()
    app.include_router(router)
    app.include_router(dashboard_router)
    app.state.prediction_service = service
    app.state.auth_service = AuthService(settings=settings)

    client = TestClient(app)
    headers = _login(client)
    response = client.post(
        "/predict_availability",
        json={
            "room_id": 9999,
            "date": datetime.now(timezone.utc).date().isoformat(),
            "time_slot": "14-16",
        },
        headers=headers,
    )

    assert response.status_code == 404


def test_model_metadata_is_persisted_on_training(tmp_path):
    settings = _build_test_settings(tmp_path, "model_metadata_test.db")
    repository = DataRepository(settings)
    repository.initialize_database()
    repository.seed_synthetic_data()
    service = AvailabilityPredictionService(repository=repository, settings=settings)

    service.train_model()
    metadata = service.get_model_metadata()
    persisted = repository.get_model_metadata()

    assert metadata["model_version"] == settings.prediction_model_version
    assert metadata["model_type"] in {"logistic_regression", "dummy_most_frequent"}
    assert "trained_at" in metadata
    assert isinstance(metadata["training_rows"], int)
    assert metadata["training_rows"] > 0
    assert persisted is not None
    assert persisted["model_version"] == settings.prediction_model_version
