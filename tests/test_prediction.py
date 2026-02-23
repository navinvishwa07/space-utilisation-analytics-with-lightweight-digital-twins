from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.conrollers.allocation_controller import router
from backend.repository.data_repository import DataRepository
from backend.services.prediction_service import AvailabilityPredictionService
from backend.utils.config import get_settings


def _build_test_settings(tmp_path, filename: str):
    base = get_settings()
    return replace(
        base,
        database_path=tmp_path / filename,
        prediction_min_training_rows=1,
    )


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
    app.state.prediction_service = service

    client = TestClient(app)
    response = client.post(
        "/predict_availability",
        json={
            "room_id": 1,
            "date": datetime.now(timezone.utc).date().isoformat(),
            "time_slot": "11-13",
        },
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
    app.state.prediction_service = service

    client = TestClient(app)
    response = client.post(
        "/predict_availability",
        json={
            "room_id": 9999,
            "date": datetime.now(timezone.utc).date().isoformat(),
            "time_slot": "14-16",
        },
    )

    assert response.status_code == 404
