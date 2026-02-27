"""Repository layer responsible for all database access."""

from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from backend.domain.models import AllocationRequest, DemandForecast, IdlePrediction, Room
from backend.utils.config import Settings, get_settings
from backend.utils.logger import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True)
class RoomRecord:
    """Room projection used by service layer."""

    room_id: int
    room_type: str


@dataclass(frozen=True)
class BookingRecord:
    """Joined booking projection for model training."""

    room_id: int
    date: str
    time_slot: str
    occupied: int
    room_type: str


class DataRepository:
    """Encapsulates SQLite access so business logic stays storage-agnostic."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()
        self._db_path = Path(self._settings.database_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def database_path(self) -> Path:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON;")
        return connection

    def initialize_database(self) -> None:
        """Create all persistence artifacts before API startup."""
        try:
            with self._connect() as conn:
                cursor = conn.cursor()

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS Rooms (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        capacity INTEGER NOT NULL CHECK (capacity > 0),
                        room_type TEXT NOT NULL,
                        location TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS BookingHistory (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        room_id INTEGER NOT NULL,
                        date TEXT NOT NULL,
                        time_slot TEXT NOT NULL,
                        occupied INTEGER NOT NULL CHECK (occupied IN (0,1)),
                        FOREIGN KEY (room_id) REFERENCES Rooms(id)
                    );
                    """
                )

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS Requests (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        requested_capacity INTEGER NOT NULL CHECK (requested_capacity > 0),
                        requested_date TEXT NOT NULL,
                        requested_time_slot TEXT NOT NULL,
                        stakeholder_id TEXT NOT NULL DEFAULT 'UNKNOWN',
                        priority_weight REAL NOT NULL DEFAULT 1.0,
                        status TEXT NOT NULL DEFAULT 'PENDING'
                    );
                    """
                )

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS AllocationLogs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        request_id INTEGER NOT NULL,
                        room_id INTEGER NOT NULL,
                        allocation_score REAL,
                        allocated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (request_id) REFERENCES Requests(id),
                        FOREIGN KEY (room_id) REFERENCES Rooms(id)
                    );
                    """
                )

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS Predictions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        room_id INTEGER NOT NULL,
                        date TEXT NOT NULL,
                        time_slot TEXT NOT NULL,
                        idle_probability REAL NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (room_id) REFERENCES Rooms(id)
                    );
                    """
                )

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS DemandForecastLogs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        forecast_date TEXT NOT NULL,
                        time_slot TEXT NOT NULL,
                        historical_count INTEGER NOT NULL,
                        demand_intensity_score REAL NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )

                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_requests_date_slot_status
                    ON Requests(requested_date, requested_time_slot, status);
                    """
                )

                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_booking_room_slot_date
                    ON BookingHistory(room_id, time_slot, date);
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_predictions_room_date_slot
                    ON Predictions(room_id, date, time_slot);
                    """
                )

                cursor.execute("PRAGMA table_info(Requests);")
                request_columns = {
                    str(row["name"]) for row in cursor.fetchall()
                }
                if "stakeholder_id" not in request_columns:
                    cursor.execute(
                        """
                        ALTER TABLE Requests
                        ADD COLUMN stakeholder_id TEXT NOT NULL DEFAULT 'UNKNOWN';
                        """
                    )
                conn.commit()
            logger.info("Database initialized at %s", self._db_path)
        except sqlite3.Error as exc:
            raise RuntimeError(f"Database initialization failed: {exc}") from exc

    def seed_synthetic_data(self) -> None:
        """Seed deterministic synthetic history only when tables are empty."""
        random.seed(self._settings.synthetic_random_seed)
        try:
            with self._connect() as conn:
                cursor = conn.cursor()

                cursor.execute("SELECT COUNT(*) AS count FROM Rooms;")
                room_count = int(cursor.fetchone()["count"])
                if room_count > 0:
                    logger.info("Synthetic data already present; skipping seed")
                    return

                rooms = [
                    ("Room A", 30, "Classroom", "Block 1"),
                    ("Room B", 50, "Auditorium", "Block 1"),
                    ("Room C", 20, "Lab", "Block 2"),
                    ("Room D", 40, "Classroom", "Block 2"),
                    ("Room E", 25, "Seminar", "Block 3"),
                    ("Room F", 60, "Auditorium", "Block 3"),
                    ("Room G", 35, "Classroom", "Block 4"),
                    ("Room H", 45, "Lab", "Block 4"),
                    ("Room I", 30, "Seminar", "Block 5"),
                    ("Room J", 55, "Auditorium", "Block 5"),
                ]
                cursor.executemany(
                    """
                    INSERT INTO Rooms (name, capacity, room_type, location)
                    VALUES (?, ?, ?, ?);
                    """,
                    rooms,
                )

                cursor.execute("SELECT id FROM Rooms ORDER BY id ASC;")
                room_ids = [int(row["id"]) for row in cursor.fetchall()]
                start_date = datetime.now(timezone.utc).date() - timedelta(
                    days=self._settings.synthetic_seed_days
                )

                booking_entries = []
                for day in range(self._settings.synthetic_seed_days):
                    current_day = start_date + timedelta(days=day)
                    weekday = current_day.weekday()
                    occupied_probability = (
                        self._settings.synthetic_weekday_occupied_probability
                        if weekday < 5
                        else self._settings.synthetic_weekend_occupied_probability
                    )
                    for room_id in room_ids:
                        for slot in self._settings.synthetic_time_slots:
                            occupied = 1 if random.random() < occupied_probability else 0
                            booking_entries.append(
                                (room_id, current_day.isoformat(), slot, occupied)
                            )

                cursor.executemany(
                    """
                    INSERT INTO BookingHistory (room_id, date, time_slot, occupied)
                    VALUES (?, ?, ?, ?);
                    """,
                    booking_entries,
                )
                conn.commit()
            logger.info(
                "Synthetic seed completed with %s records",
                len(booking_entries),
            )
        except sqlite3.Error as exc:
            raise RuntimeError(f"Synthetic data seeding failed: {exc}") from exc

    def get_room(self, room_id: int) -> Optional[RoomRecord]:
        """Fetch room metadata for validation and feature enrichment."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, room_type FROM Rooms WHERE id = ?;",
                (room_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return RoomRecord(room_id=int(row["id"]), room_type=str(row["room_type"]))

    def get_booking_history_for_training(self) -> List[BookingRecord]:
        """Load historical occupancy joined with room_type for model training."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    bh.room_id,
                    bh.date,
                    bh.time_slot,
                    bh.occupied,
                    r.room_type
                FROM BookingHistory AS bh
                INNER JOIN Rooms AS r ON r.id = bh.room_id
                ORDER BY bh.date ASC, bh.room_id ASC, bh.time_slot ASC;
                """
            )
            return [
                BookingRecord(
                    room_id=int(row["room_id"]),
                    date=str(row["date"]),
                    time_slot=str(row["time_slot"]),
                    occupied=int(row["occupied"]),
                    room_type=str(row["room_type"]),
                )
                for row in cursor.fetchall()
            ]

    def get_historical_occupancy_frequency(
        self,
        room_id: int,
        time_slot: str,
    ) -> Optional[float]:
        """Return long-run occupancy frequency for room/slot pair."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT AVG(occupied) AS avg_occupied
                FROM BookingHistory
                WHERE room_id = ? AND time_slot = ?;
                """,
                (room_id, time_slot),
            )
            row = cursor.fetchone()
            if row is None or row["avg_occupied"] is None:
                return None
            return float(row["avg_occupied"])

    def get_rolling_occupancy_average(
        self,
        room_id: int,
        time_slot: str,
        target_date: str,
        window_days: int,
    ) -> Optional[float]:
        """Return the mean occupancy of the trailing `window_days` period."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT AVG(occupied) AS rolling_avg
                FROM BookingHistory
                WHERE room_id = ?
                  AND time_slot = ?
                  AND date < ?
                  AND date >= date(?, ?);
                """,
                (room_id, time_slot, target_date, target_date, f"-{window_days} day"),
            )
            row = cursor.fetchone()
            if row is None or row["rolling_avg"] is None:
                return None
            return float(row["rolling_avg"])

    def get_global_occupancy_frequency(self) -> float:
        """Return system-wide occupancy baseline for sparse-history fallback."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT AVG(occupied) AS avg_occupied FROM BookingHistory;")
            row = cursor.fetchone()
            if row is None or row["avg_occupied"] is None:
                return self._settings.prediction_default_occupancy_probability
            return float(row["avg_occupied"])

    def list_known_time_slots(self) -> Sequence[str]:
        """Return configured or historical slots to support input validation."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT time_slot FROM BookingHistory;")
            slots = [str(row["time_slot"]) for row in cursor.fetchall()]
        if slots:
            return tuple(sorted(slots))
        return self._settings.synthetic_time_slots

    def save_prediction(
        self,
        room_id: int,
        date: str,
        time_slot: str,
        idle_probability: float,
    ) -> None:
        """Persist inference output for debugging and observability."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO Predictions (room_id, date, time_slot, idle_probability)
                VALUES (?, ?, ?, ?);
                """,
                (room_id, date, time_slot, idle_probability),
            )
            conn.commit()

    def count_predictions(self) -> int:
        """Return persisted prediction count for diagnostics and tests."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) AS count FROM Predictions;")
            return int(cursor.fetchone()["count"])

    def list_rooms_for_allocation(self) -> list[Room]:
        """Return room capacities for allocation optimization."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, capacity
                FROM Rooms
                ORDER BY id ASC;
                """
            )
            return [
                Room(
                    room_id=int(row["id"]),
                    capacity=int(row["capacity"]),
                )
                for row in cursor.fetchall()
            ]

    def list_pending_requests(
        self,
        requested_date: str,
        requested_time_slot: str,
    ) -> list[AllocationRequest]:
        """Return pending requests eligible for the target date/slot."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    id,
                    requested_capacity,
                    requested_date,
                    requested_time_slot,
                    priority_weight,
                    stakeholder_id
                FROM Requests
                WHERE requested_date = ?
                  AND requested_time_slot = ?
                  AND status = 'PENDING'
                ORDER BY id ASC;
                """,
                (requested_date, requested_time_slot),
            )
            return [
                AllocationRequest(
                    request_id=int(row["id"]),
                    requested_capacity=int(row["requested_capacity"]),
                    requested_date=str(row["requested_date"]),
                    requested_time_slot=str(row["requested_time_slot"]),
                    priority_weight=float(row["priority_weight"]),
                    stakeholder_id=str(row["stakeholder_id"]),
                )
                for row in cursor.fetchall()
            ]

    def list_all_pending_requests(self) -> list[AllocationRequest]:
        """Return all pending requests across dates/slots in deterministic order."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    id,
                    requested_capacity,
                    requested_date,
                    requested_time_slot,
                    priority_weight,
                    stakeholder_id
                FROM Requests
                WHERE status = 'PENDING'
                ORDER BY requested_date ASC, requested_time_slot ASC, id ASC;
                """
            )
            return [
                AllocationRequest(
                    request_id=int(row["id"]),
                    requested_capacity=int(row["requested_capacity"]),
                    requested_date=str(row["requested_date"]),
                    requested_time_slot=str(row["requested_time_slot"]),
                    priority_weight=float(row["priority_weight"]),
                    stakeholder_id=str(row["stakeholder_id"]),
                )
                for row in cursor.fetchall()
            ]

    def list_idle_predictions(
        self,
        requested_date: str,
        requested_time_slot: str,
    ) -> list[IdlePrediction]:
        """Return latest idle predictions per room for a date/slot."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT p.room_id, p.date, p.time_slot, p.idle_probability
                FROM Predictions AS p
                INNER JOIN (
                    SELECT room_id, date, time_slot, MAX(id) AS max_id
                    FROM Predictions
                    WHERE date = ? AND time_slot = ?
                    GROUP BY room_id, date, time_slot
                ) AS latest
                    ON latest.max_id = p.id
                ORDER BY p.room_id ASC;
                """,
                (requested_date, requested_time_slot),
            )
            return [
                IdlePrediction(
                    room_id=int(row["room_id"]),
                    date=str(row["date"]),
                    time_slot=str(row["time_slot"]),
                    idle_probability=float(row["idle_probability"]),
                )
                for row in cursor.fetchall()
            ]

    def save_forecast_output(
        self,
        forecast_date: str,
        forecasts: list[DemandForecast],
    ) -> None:
        """Persist demand forecasts for auditability/debugging."""
        if not forecasts:
            return
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                """
                INSERT INTO DemandForecastLogs (
                    forecast_date,
                    time_slot,
                    historical_count,
                    demand_intensity_score
                )
                VALUES (?, ?, ?, ?);
                """,
                [
                    (
                        forecast_date,
                        forecast.time_slot,
                        forecast.historical_count,
                        forecast.demand_intensity_score,
                    )
                    for forecast in forecasts
                ],
            )
            conn.commit()

    def save_allocation_logs(
        self,
        allocations: Iterable[tuple[int, int, float]],
    ) -> None:
        """Persist allocation decisions for observability and audit trails."""
        allocation_rows = list(allocations)
        if not allocation_rows:
            return
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                """
                INSERT INTO AllocationLogs (request_id, room_id, allocation_score)
                VALUES (?, ?, ?);
                """,
                allocation_rows,
            )
            conn.commit()

    def mark_requests_allocated(self, request_ids: Sequence[int]) -> None:
        """Mark allocated request ids for stateful request lifecycle tracking."""
        if not request_ids:
            return
        placeholders = ",".join("?" for _ in request_ids)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                UPDATE Requests
                SET status = 'ALLOCATED'
                WHERE id IN ({placeholders});
                """,
                tuple(request_ids),
            )
            conn.commit()

    def get_historical_request_counts_by_time_slot(
        self,
        lookback_days: int,
        target_date: str,
    ) -> dict[str, int]:
        """Aggregate request frequencies by slot for forecasting baseline."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT requested_time_slot AS time_slot, COUNT(*) AS count
                FROM Requests
                WHERE requested_date < ?
                  AND requested_date >= date(?, ?)
                GROUP BY requested_time_slot
                ORDER BY requested_time_slot ASC;
                """,
                (target_date, target_date, f"-{lookback_days} day"),
            )
            return {
                str(row["time_slot"]): int(row["count"])
                for row in cursor.fetchall()
            }

    def create_request(
        self,
        requested_capacity: int,
        requested_date: str,
        requested_time_slot: str,
        priority_weight: float,
        stakeholder_id: str,
    ) -> int:
        """Insert request row and return the created id."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO Requests (
                    requested_capacity,
                    requested_date,
                    requested_time_slot,
                    priority_weight,
                    stakeholder_id
                )
                VALUES (?, ?, ?, ?, ?);
                """,
                (
                    requested_capacity,
                    requested_date,
                    requested_time_slot,
                    priority_weight,
                    stakeholder_id,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def count_allocation_logs(self) -> int:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) AS count FROM AllocationLogs;")
            return int(cursor.fetchone()["count"])

    def count_forecast_logs(self) -> int:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) AS count FROM DemandForecastLogs;")
            return int(cursor.fetchone()["count"])

    def get_request_status(self, request_id: int) -> Optional[str]:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT status FROM Requests WHERE id = ?;",
                (request_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return str(row["status"])


def get_database_path() -> str:
    """Backward compatible access for existing startup scripts."""
    return str(DataRepository().database_path)


def initialize_database() -> None:
    """Backward compatible module-level initializer."""
    DataRepository().initialize_database()


def seed_synthetic_data() -> None:
    """Backward compatible module-level seeding entry point."""
    DataRepository().seed_synthetic_data()
