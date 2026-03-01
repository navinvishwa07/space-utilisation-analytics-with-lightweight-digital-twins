from __future__ import annotations

import csv
import sqlite3
from dataclasses import replace

from backend.repository.data_repository import DataRepository
from backend.utils.config import get_settings


def _build_test_settings(tmp_path, filename: str):
    base = get_settings()
    return replace(
        base,
        database_path=tmp_path / filename,
        synthetic_dataset_filename="synthetic_dataset.csv",
        synthetic_reference_end_date="2026-02-21",
        synthetic_random_seed=42,
    )


def _table_count(db_path, table_name: str) -> int:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM {table_name};")
        return int(cursor.fetchone()[0])


def test_seed_synthetic_data_generates_csv_and_expected_rows(tmp_path):
    settings = _build_test_settings(tmp_path, "seed_generation.db")
    repository = DataRepository(settings)
    repository.initialize_database()

    assert not repository.synthetic_dataset_path.exists()
    repository.seed_synthetic_data()

    assert repository.synthetic_dataset_path.exists()
    with repository.synthetic_dataset_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == ["room_id", "date", "time_slot", "occupied"]
        rows = list(reader)

    expected_rows = 10 * 21 * 4
    assert len(rows) == expected_rows
    assert all(
        row["room_id"] and row["date"] and row["time_slot"] and row["occupied"]
        for row in rows
    )
    assert _table_count(settings.database_path, "Rooms") == 10
    assert _table_count(settings.database_path, "BookingHistory") == expected_rows


def test_seed_synthetic_data_is_idempotent_and_reuses_existing_csv(tmp_path):
    settings = _build_test_settings(tmp_path, "seed_idempotent.db")
    repository = DataRepository(settings)
    repository.initialize_database()
    repository.seed_synthetic_data()

    expected_rows = 10 * 21 * 4
    original_mtime = repository.synthetic_dataset_path.stat().st_mtime_ns

    repository.seed_synthetic_data()
    assert repository.synthetic_dataset_path.stat().st_mtime_ns == original_mtime
    assert _table_count(settings.database_path, "BookingHistory") == expected_rows

    with sqlite3.connect(settings.database_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT room_id, date, time_slot
                FROM BookingHistory
                GROUP BY room_id, date, time_slot
            ) AS grouped_rows;
            """
        )
        unique_rows = int(cursor.fetchone()[0])
    assert unique_rows == expected_rows


def test_seed_demo_requests_if_empty_is_idempotent(tmp_path):
    settings = _build_test_settings(tmp_path, "demo_requests.db")
    repository = DataRepository(settings)
    repository.initialize_database()
    repository.seed_synthetic_data()

    assert repository.count_requests() == 0
    inserted = repository.seed_demo_requests_if_empty()
    assert 5 <= inserted <= 10
    assert repository.count_requests() == inserted

    inserted_again = repository.seed_demo_requests_if_empty()
    assert inserted_again == 0
    assert repository.count_requests() == inserted

    pending_windows = repository.list_pending_request_windows()
    assert pending_windows
