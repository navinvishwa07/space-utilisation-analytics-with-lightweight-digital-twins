"""Repository layer responsible for all database access."""

from __future__ import annotations

import csv
import random
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
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

    _SYNTHETIC_COLUMNS = ("room_id", "date", "time_slot", "occupied")
    _SYNTHETIC_WEEKDAY_PROBABILITY_RANGE = (0.65, 0.75)
    _SYNTHETIC_WEEKEND_PROBABILITY_RANGE = (0.30, 0.40)
    _ROOM_CATALOG: tuple[tuple[int, str, int, str, str], ...] = (
        (1, "Room A", 30, "Classroom", "Block 1"),
        (2, "Room B", 50, "Auditorium", "Block 1"),
        (3, "Room C", 20, "Lab", "Block 2"),
        (4, "Room D", 40, "Classroom", "Block 2"),
        (5, "Room E", 25, "Seminar", "Block 3"),
        (6, "Room F", 60, "Auditorium", "Block 3"),
        (7, "Room G", 35, "Classroom", "Block 4"),
        (8, "Room H", 45, "Lab", "Block 4"),
        (9, "Room I", 30, "Seminar", "Block 5"),
        (10, "Room J", 55, "Auditorium", "Block 5"),
    )
    _DEMO_REQUEST_BLUEPRINTS: tuple[tuple[int, int, int, float, str], ...] = (
        (2, 0, 20, 1.60, "Dept-Engineering"),
        (2, 0, 28, 1.40, "Dept-Science"),
        (2, 0, 14, 1.10, "Student-Innovation"),
        (2, 1, 38, 1.80, "Events"),
        (3, 2, 18, 1.25, "Dept-CS"),
        (3, 2, 42, 1.55, "Operations"),
        (3, 3, 12, 1.05, "Community-Lab"),
        (4, 1, 25, 1.30, "Research-Center"),
    )

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()
        self._db_path = Path(self._settings.database_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._synthetic_dataset_path = (
            self._db_path.parent / self._settings.synthetic_dataset_filename
        )

    @property
    def database_path(self) -> Path:
        return self._db_path

    @property
    def synthetic_dataset_path(self) -> Path:
        return self._synthetic_dataset_path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON;")
        return connection

    def _validate_probability_range(
        self,
        label: str,
        value: float,
        lower: float,
        upper: float,
    ) -> None:
        if not lower <= value <= upper:
            raise RuntimeError(
                f"{label} must be within [{lower:.2f}, {upper:.2f}], got {value:.4f}"
            )

    def _validate_synthetic_configuration(self) -> None:
        if self._settings.synthetic_seed_days <= 0:
            raise RuntimeError("SYNTHETIC_SEED_DAYS must be greater than zero")
        if not self._settings.synthetic_time_slots:
            raise RuntimeError("SYNTHETIC_TIME_SLOTS must not be empty")
        self._validate_probability_range(
            label="SYNTHETIC_WEEKDAY_OCCUPIED_PROBABILITY",
            value=self._settings.synthetic_weekday_occupied_probability,
            lower=self._SYNTHETIC_WEEKDAY_PROBABILITY_RANGE[0],
            upper=self._SYNTHETIC_WEEKDAY_PROBABILITY_RANGE[1],
        )
        self._validate_probability_range(
            label="SYNTHETIC_WEEKEND_OCCUPIED_PROBABILITY",
            value=self._settings.synthetic_weekend_occupied_probability,
            lower=self._SYNTHETIC_WEEKEND_PROBABILITY_RANGE[0],
            upper=self._SYNTHETIC_WEEKEND_PROBABILITY_RANGE[1],
        )

    def _expected_synthetic_row_count(self) -> int:
        return len(self._ROOM_CATALOG) * self._settings.synthetic_seed_days * len(
            self._settings.synthetic_time_slots
        )

    def _generate_synthetic_dataset_csv(self) -> None:
        self.synthetic_dataset_path.parent.mkdir(parents=True, exist_ok=True)
        rng = random.Random(self._settings.synthetic_random_seed)
        end_date = datetime.strptime(
            self._settings.synthetic_reference_end_date,
            "%Y-%m-%d",
        ).date()
        start_date = end_date - timedelta(days=self._settings.synthetic_seed_days - 1)

        with self.synthetic_dataset_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(self._SYNTHETIC_COLUMNS)

            for offset in range(self._settings.synthetic_seed_days):
                current_day = start_date + timedelta(days=offset)
                occupied_probability = (
                    self._settings.synthetic_weekday_occupied_probability
                    if current_day.weekday() < 5
                    else self._settings.synthetic_weekend_occupied_probability
                )
                for room_id, *_ in self._ROOM_CATALOG:
                    for slot in self._settings.synthetic_time_slots:
                        occupied = 1 if rng.random() < occupied_probability else 0
                        writer.writerow([room_id, current_day.isoformat(), slot, occupied])

        logger.info(
            "Synthetic dataset generated at %s with %s rows",
            self.synthetic_dataset_path,
            self._expected_synthetic_row_count(),
        )

    def _ensure_synthetic_dataset_exists(self) -> None:
        if self.synthetic_dataset_path.exists():
            return
        self._generate_synthetic_dataset_csv()

    def _load_synthetic_rows_from_csv(self) -> list[tuple[int, str, str, int]]:
        if not self.synthetic_dataset_path.exists():
            raise RuntimeError(
                f"Synthetic dataset not found at {self.synthetic_dataset_path}"
            )

        rows: list[tuple[int, str, str, int]] = []
        allowed_slots = set(self._settings.synthetic_time_slots)
        expected_room_ids = {room_id for room_id, *_ in self._ROOM_CATALOG}
        seen_keys: set[tuple[int, str, str]] = set()

        with self.synthetic_dataset_path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != list(self._SYNTHETIC_COLUMNS):
                raise RuntimeError(
                    "Synthetic dataset columns must be exactly: "
                    "room_id,date,time_slot,occupied"
                )

            for line_no, raw_row in enumerate(reader, start=2):
                if raw_row is None:
                    raise RuntimeError(f"Malformed CSV row at line {line_no}")

                missing_columns = [
                    column
                    for column in self._SYNTHETIC_COLUMNS
                    if raw_row.get(column) is None or str(raw_row[column]).strip() == ""
                ]
                if missing_columns:
                    raise RuntimeError(
                        f"Missing values in columns {missing_columns} at line {line_no}"
                    )

                try:
                    room_id = int(raw_row["room_id"])
                    date_value = str(raw_row["date"])
                    slot = str(raw_row["time_slot"])
                    occupied = int(raw_row["occupied"])
                except ValueError as exc:
                    raise RuntimeError(
                        f"Invalid value types in synthetic dataset at line {line_no}"
                    ) from exc

                if room_id not in expected_room_ids:
                    raise RuntimeError(
                        f"room_id {room_id} is out of allowed range 1-10 at line {line_no}"
                    )
                try:
                    datetime.strptime(date_value, "%Y-%m-%d")
                except ValueError as exc:
                    raise RuntimeError(
                        f"Invalid date format '{date_value}' at line {line_no}"
                    ) from exc
                if slot not in allowed_slots:
                    raise RuntimeError(
                        f"time_slot '{slot}' is invalid at line {line_no}"
                    )
                if occupied not in (0, 1):
                    raise RuntimeError(
                        f"occupied must be 0 or 1 at line {line_no}, got {occupied}"
                    )

                dedupe_key = (room_id, date_value, slot)
                if dedupe_key in seen_keys:
                    raise RuntimeError(
                        "Duplicate room_id/date/time_slot found at line "
                        f"{line_no}: {dedupe_key}"
                    )
                seen_keys.add(dedupe_key)
                rows.append((room_id, date_value, slot, occupied))

        expected_rows = self._expected_synthetic_row_count()
        if len(rows) != expected_rows:
            raise RuntimeError(
                f"Synthetic dataset must contain exactly {expected_rows} rows, "
                f"got {len(rows)}"
            )
        return rows

    def _seed_room_catalog(self, cursor: sqlite3.Cursor) -> None:
        cursor.executemany(
            """
            INSERT OR IGNORE INTO Rooms (id, name, capacity, room_type, location)
            VALUES (?, ?, ?, ?, ?);
            """,
            self._ROOM_CATALOG,
        )
        expected_room_ids = {room_id for room_id, *_ in self._ROOM_CATALOG}
        cursor.execute(
            """
            SELECT id
            FROM Rooms
            WHERE id BETWEEN 1 AND 10;
            """
        )
        persisted_room_ids = {int(row["id"]) for row in cursor.fetchall()}
        missing_room_ids = sorted(expected_room_ids - persisted_room_ids)
        if missing_room_ids:
            raise RuntimeError(
                "Rooms catalog is missing required room ids: "
                f"{missing_room_ids}. Cannot seed BookingHistory."
            )

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
                    CREATE TABLE IF NOT EXISTS ModelRegistry (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        model_type TEXT NOT NULL,
                        model_version TEXT NOT NULL,
                        trained_at TEXT NOT NULL
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
                    DELETE FROM BookingHistory
                    WHERE id NOT IN (
                        SELECT MIN(id)
                        FROM BookingHistory
                        GROUP BY room_id, date, time_slot
                    );
                    """
                )
                cursor.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_booking_unique_room_date_slot
                    ON BookingHistory(room_id, date, time_slot);
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
        """Seed BookingHistory from CSV source of truth in an idempotent way."""
        self._validate_synthetic_configuration()
        self._ensure_synthetic_dataset_exists()
        booking_rows = self._load_synthetic_rows_from_csv()
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                self._seed_room_catalog(cursor)
                cursor.execute("SELECT COUNT(*) AS count FROM BookingHistory;")
                before_count = int(cursor.fetchone()["count"])
                cursor.executemany(
                    """
                    INSERT OR IGNORE INTO BookingHistory (
                        room_id,
                        date,
                        time_slot,
                        occupied
                    )
                    VALUES (?, ?, ?, ?);
                    """,
                    booking_rows,
                )
                cursor.execute("SELECT COUNT(*) AS count FROM BookingHistory;")
                after_count = int(cursor.fetchone()["count"])
                conn.commit()
            inserted_count = after_count - before_count
            duplicate_count = max(len(booking_rows) - inserted_count, 0)
            logger.info(
                "Synthetic CSV loaded successfully from %s (%s rows)",
                self.synthetic_dataset_path,
                len(booking_rows),
            )
            logger.info(
                "BookingHistory inserted rows: %s",
                inserted_count,
            )
            if duplicate_count == 0:
                logger.info("No duplicate BookingHistory rows created during seed")
            else:
                logger.info(
                    "BookingHistory duplicate rows skipped: %s",
                    duplicate_count,
                )
        except sqlite3.Error as exc:
            raise RuntimeError(f"Synthetic data seeding failed: {exc}") from exc

    def _build_demo_requests(self) -> list[tuple[int, str, str, float, str]]:
        slots = self._settings.synthetic_time_slots
        if not slots:
            raise RuntimeError("No synthetic_time_slots configured for demo request seeding")
        reference_end_date = datetime.strptime(
            self._settings.synthetic_reference_end_date,
            "%Y-%m-%d",
        ).date()
        requests: list[tuple[int, str, str, float, str]] = []
        for day_offset, slot_index, capacity, priority, stakeholder in self._DEMO_REQUEST_BLUEPRINTS:
            request_date = (reference_end_date + timedelta(days=day_offset)).isoformat()
            request_slot = slots[slot_index % len(slots)]
            requests.append(
                (
                    capacity,
                    request_date,
                    request_slot,
                    priority,
                    stakeholder,
                )
            )
        return requests

    def seed_demo_requests_if_empty(self) -> int:
        """Seed deterministic demo requests only when Requests is empty."""
        demo_rows = self._build_demo_requests()
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) AS count FROM Requests;")
                existing_count = int(cursor.fetchone()["count"])
                if existing_count > 0:
                    logger.info(
                        "Demo request seed skipped because Requests already has %s rows",
                        existing_count,
                    )
                    return 0
                cursor.executemany(
                    """
                    INSERT INTO Requests (
                        requested_capacity,
                        requested_date,
                        requested_time_slot,
                        priority_weight,
                        stakeholder_id,
                        status
                    )
                    VALUES (?, ?, ?, ?, ?, 'PENDING');
                    """,
                    demo_rows,
                )
                conn.commit()
                inserted_count = len(demo_rows)
            logger.info("Seeded %s deterministic demo requests", inserted_count)
            return inserted_count
        except sqlite3.Error as exc:
            raise RuntimeError(f"Demo request seeding failed: {exc}") from exc

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

    def count_requests(self) -> int:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) AS count FROM Requests;")
            return int(cursor.fetchone()["count"])

    def list_pending_request_windows(
        self,
        limit: int = 20,
    ) -> list[tuple[str, str, int]]:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT requested_date, requested_time_slot, COUNT(*) AS request_count
                FROM Requests
                WHERE status = 'PENDING'
                GROUP BY requested_date, requested_time_slot
                ORDER BY requested_date ASC, requested_time_slot ASC
                LIMIT ?;
                """,
                (limit,),
            )
            return [
                (
                    str(row["requested_date"]),
                    str(row["requested_time_slot"]),
                    int(row["request_count"]),
                )
                for row in cursor.fetchall()
            ]

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

    def save_model_metadata(
        self,
        *,
        model_type: str,
        model_version: str,
        trained_at: str,
    ) -> None:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO ModelRegistry (id, model_type, model_version, trained_at)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    model_type = excluded.model_type,
                    model_version = excluded.model_version,
                    trained_at = excluded.trained_at;
                """,
                (model_type, model_version, trained_at),
            )
            conn.commit()

    def get_model_metadata(self) -> Optional[dict[str, str]]:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT model_type, model_version, trained_at
                FROM ModelRegistry
                WHERE id = 1;
                """
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return {
                "model_type": str(row["model_type"]),
                "model_version": str(row["model_version"]),
                "trained_at": str(row["trained_at"]),
            }


def get_database_path() -> str:
    """Backward compatible access for existing startup scripts."""
    return str(DataRepository().database_path)


def initialize_database() -> None:
    """Backward compatible module-level initializer."""
    DataRepository().initialize_database()


def seed_synthetic_data() -> None:
    """Backward compatible module-level seeding entry point."""
    DataRepository().seed_synthetic_data()


def seed_demo_requests_if_empty() -> int:
    """Backward compatible module-level demo request seeding entry point."""
    return DataRepository().seed_demo_requests_if_empty()
