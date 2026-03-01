from __future__ import annotations

from dataclasses import replace

from backend.repository.data_repository import DataRepository
from backend.services.matching_service import AllocationOptimizationService
from backend.services.prediction_service import AvailabilityPredictionService
from backend.utils.config import get_settings


def _build_test_settings(tmp_path, filename: str):
    base = get_settings()
    return replace(
        base,
        database_path=tmp_path / filename,
        prediction_min_training_rows=1,
        allocation_solver_max_time_seconds=5,
        allocation_cp_sat_workers=1,
        allocation_idle_probability_threshold=0.5,
        allocation_stakeholder_usage_cap=0.7,
    )


def _seed_requests(repository: DataRepository, target_date: str, target_slot: str) -> None:
    repository.create_request(18, target_date, target_slot, 1.8, "dept_a")
    repository.create_request(28, target_date, target_slot, 1.6, "dept_b")
    repository.create_request(12, target_date, target_slot, 1.2, "dept_c")


def test_greedy_fallback_runs_when_cp_sat_unavailable(monkeypatch, tmp_path):
    settings = _build_test_settings(tmp_path, "greedy_fallback.db")
    repository = DataRepository(settings)
    repository.initialize_database()
    repository.seed_synthetic_data()

    target_date = "2026-02-24"
    target_slot = "09-11"
    _seed_requests(repository, target_date, target_slot)
    for room_id in range(1, 11):
        repository.save_prediction(
            room_id=room_id,
            date=target_date,
            time_slot=target_slot,
            idle_probability=0.9 if room_id <= 6 else 0.2,
        )

    monkeypatch.setattr("backend.services.matching_service.cp_model", None)
    service = AllocationOptimizationService(repository=repository, settings=settings)

    first = service.optimize_allocation(
        requested_date=target_date,
        requested_time_slot=target_slot,
        persist_outputs=False,
    )
    second = service.optimize_allocation(
        requested_date=target_date,
        requested_time_slot=target_slot,
        persist_outputs=False,
    )

    assert first.allocations
    assert first == second


def test_optimize_allocation_auto_generates_predictions(tmp_path):
    settings = _build_test_settings(tmp_path, "auto_predictions.db")
    repository = DataRepository(settings)
    repository.initialize_database()
    repository.seed_synthetic_data()

    target_date = "2026-02-25"
    target_slot = "11-13"
    _seed_requests(repository, target_date, target_slot)

    prediction_service = AvailabilityPredictionService(repository=repository, settings=settings)
    prediction_service.train_model()
    service = AllocationOptimizationService(
        repository=repository,
        settings=settings,
        prediction_service=prediction_service,
    )

    before_prediction_count = repository.count_predictions()
    result = service.optimize_allocation(
        requested_date=target_date,
        requested_time_slot=target_slot,
        persist_outputs=False,
    )

    after_prediction_count = repository.count_predictions()
    assert after_prediction_count >= before_prediction_count + 10
    assert result.allocations or result.unassigned_request_ids
