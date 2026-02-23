"""Centralized configuration for runtime behavior and model settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Tuple


def _env_int(name: str, default: int) -> int:
    """Safely parse integer environment values with sensible defaults."""
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    """Safely parse float environment values with sensible defaults."""
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_csv(name: str, default: Tuple[str, ...]) -> Tuple[str, ...]:
    """Allow slot configuration via comma-separated env var."""
    value = os.getenv(name)
    if not value:
        return default
    items = tuple(item.strip() for item in value.split(",") if item.strip())
    return items or default


@dataclass(frozen=True)
class Settings:
    """Runtime settings.

    A frozen dataclass keeps configuration immutable after startup so all layers
    behave deterministically and are easier to test.
    """

    app_name: str
    app_version: str
    log_level: str
    database_path: Path

    synthetic_seed_days: int
    synthetic_time_slots: Tuple[str, ...]
    synthetic_weekday_occupied_probability: float
    synthetic_weekend_occupied_probability: float
    synthetic_random_seed: int

    prediction_model_max_iter: int
    prediction_random_state: int
    prediction_min_training_rows: int
    prediction_rolling_window_days: int
    prediction_default_occupancy_probability: float
    prediction_time_slot_regex: str

    allocation_idle_probability_threshold: float
    allocation_stakeholder_usage_cap: float
    allocation_solver_max_time_seconds: int
    allocation_objective_scale: int
    allocation_cp_sat_workers: int
    allocation_forecast_history_days: int


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache runtime settings once for process lifetime."""
    backend_dir = Path(__file__).resolve().parents[1]
    data_dir = backend_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        app_name=os.getenv("APP_NAME", "SIET API"),
        app_version=os.getenv("APP_VERSION", "1.0.0"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        database_path=data_dir / os.getenv("DATABASE_FILENAME", "siet.db"),
        synthetic_seed_days=_env_int("SYNTHETIC_SEED_DAYS", 21),
        synthetic_time_slots=_env_csv(
            "SYNTHETIC_TIME_SLOTS",
            ("09-11", "11-13", "14-16", "16-18"),
        ),
        synthetic_weekday_occupied_probability=_env_float(
            "SYNTHETIC_WEEKDAY_OCCUPIED_PROBABILITY",
            0.65,
        ),
        synthetic_weekend_occupied_probability=_env_float(
            "SYNTHETIC_WEEKEND_OCCUPIED_PROBABILITY",
            0.35,
        ),
        synthetic_random_seed=_env_int("SYNTHETIC_RANDOM_SEED", 42),
        prediction_model_max_iter=_env_int("PREDICTION_MODEL_MAX_ITER", 500),
        prediction_random_state=_env_int("PREDICTION_RANDOM_STATE", 42),
        prediction_min_training_rows=_env_int("PREDICTION_MIN_TRAINING_ROWS", 20),
        prediction_rolling_window_days=_env_int("PREDICTION_ROLLING_WINDOW_DAYS", 7),
        prediction_default_occupancy_probability=_env_float(
            "PREDICTION_DEFAULT_OCCUPANCY_PROBABILITY",
            0.5,
        ),
        prediction_time_slot_regex=os.getenv(
            "PREDICTION_TIME_SLOT_REGEX",
            r"^([01]\d|2[0-3])-([01]\d|2[0-3])$",
        ),
        allocation_idle_probability_threshold=_env_float(
            "ALLOCATION_IDLE_PROBABILITY_THRESHOLD",
            0.50,
        ),
        allocation_stakeholder_usage_cap=_env_float(
            "ALLOCATION_STAKEHOLDER_USAGE_CAP",
            0.50,
        ),
        allocation_solver_max_time_seconds=_env_int(
            "ALLOCATION_SOLVER_MAX_TIME_SECONDS",
            10,
        ),
        allocation_objective_scale=_env_int("ALLOCATION_OBJECTIVE_SCALE", 1000),
        allocation_cp_sat_workers=_env_int("ALLOCATION_CP_SAT_WORKERS", 8),
        allocation_forecast_history_days=_env_int(
            "ALLOCATION_FORECAST_HISTORY_DAYS",
            30,
        ),
    )
