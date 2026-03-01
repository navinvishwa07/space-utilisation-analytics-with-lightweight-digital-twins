"""Business logic for occupancy-to-idle availability prediction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from backend.repository.data_repository import BookingRecord, DataRepository
from backend.utils.config import Settings, get_settings
from backend.utils.logger import get_logger


logger = get_logger(__name__)


class PredictionError(Exception):
    """Base exception for prediction workflow failures."""


class PredictionValidationError(PredictionError):
    """Raised when incoming prediction input is invalid."""


class RoomNotFoundError(PredictionError):
    """Raised when a room id does not exist in persisted state."""


class ModelNotReadyError(PredictionError):
    """Raised when inference is attempted before successful model training."""


@dataclass(frozen=True)
class PredictionResponse:
    """Canonical prediction result returned by the service."""

    idle_probability: float
    confidence_score: float

    def to_dict(self) -> Dict[str, float]:
        return {
            "idle_probability": self.idle_probability,
            "confidence_score": self.confidence_score,
        }


@dataclass(frozen=True)
class ModelMetadata:
    model_type: str
    model_version: str
    trained_at: str
    training_rows: int

    def to_dict(self) -> dict[str, str | int]:
        return {
            "model_type": self.model_type,
            "model_version": self.model_version,
            "trained_at": self.trained_at,
            "training_rows": self.training_rows,
        }


class AvailabilityPredictionService:
    """Trains and serves the baseline logistic regression model."""

    _FEATURE_COLUMNS = [
        "day_of_week",
        "time_slot",
        "room_type",
        "historical_occupancy_frequency",
        "rolling_7d_occupancy_average",
    ]

    def __init__(
        self,
        repository: Optional[DataRepository] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._repository = repository or DataRepository(self._settings)
        self._model: Optional[Pipeline] = None
        self._model_lock = RLock()
        self._trained_at: Optional[datetime] = None
        self._training_rows: int = 0
        self._model_metadata: Optional[ModelMetadata] = None

    def _validate_inputs(self, room_id: int, date: str, time_slot: str) -> datetime:
        if room_id <= 0:
            raise PredictionValidationError("room_id must be a positive integer")

        try:
            parsed_date = datetime.strptime(date, "%Y-%m-%d")
        except ValueError as exc:
            raise PredictionValidationError("date must follow YYYY-MM-DD format") from exc

        pattern = re.compile(self._settings.prediction_time_slot_regex)
        if pattern.fullmatch(time_slot) is None:
            raise PredictionValidationError(
                "time_slot must follow HH-HH format with 24-hour boundaries"
            )

        start_hour, end_hour = (int(value) for value in time_slot.split("-"))
        if start_hour >= end_hour:
            raise PredictionValidationError("time_slot start hour must be less than end")

        return parsed_date

    def _build_training_frame(self, records: list[BookingRecord]) -> pd.DataFrame:
        """Create model-ready frame with historical and rolling context."""

        frame = pd.DataFrame(
            [
                {
                    "room_id": record.room_id,
                    "date": record.date,
                    "time_slot": record.time_slot,
                    "occupied": record.occupied,
                    "room_type": record.room_type,
                }
                for record in records
            ]
        )
        if frame.empty:
            return frame

        frame["date_dt"] = pd.to_datetime(frame["date"], format="%Y-%m-%d", errors="coerce")
        frame = frame.dropna(subset=["date_dt"]).copy()
        if frame.empty:
            return frame

        frame = frame.sort_values(by=["room_id", "time_slot", "date_dt"])
        frame["day_of_week"] = frame["date_dt"].dt.dayofweek.astype(int)

        group_series = frame.groupby(["room_id", "time_slot"], sort=False)["occupied"]
        prev_count = group_series.cumcount()
        prev_sum = group_series.cumsum() - frame["occupied"]

        global_occupancy_mean = float(frame["occupied"].mean())
        frame["historical_occupancy_frequency"] = np.where(
            prev_count > 0,
            prev_sum / prev_count,
            global_occupancy_mean,
        )

        rolling_window_days = self._settings.prediction_rolling_window_days
        frame["rolling_7d_occupancy_average"] = (
            group_series.transform(
                lambda series: series.shift(1).rolling(
                    window=rolling_window_days,
                    min_periods=1,
                ).mean()
            )
        )
        frame["rolling_7d_occupancy_average"] = frame[
            "rolling_7d_occupancy_average"
        ].fillna(frame["historical_occupancy_frequency"])

        return frame

    def prepare_features(self, room_id: int, date: str, time_slot: str) -> pd.DataFrame:
        """Assemble inference-time features for a single room/date/slot request."""

        parsed_date = self._validate_inputs(room_id=room_id, date=date, time_slot=time_slot)
        room = self._repository.get_room(room_id)
        if room is None:
            raise RoomNotFoundError(f"room_id {room_id} not found")

        historical_frequency = self._repository.get_historical_occupancy_frequency(
            room_id=room_id,
            time_slot=time_slot,
        )
        global_frequency = self._repository.get_global_occupancy_frequency()
        if historical_frequency is None:
            historical_frequency = global_frequency

        rolling_average = self._repository.get_rolling_occupancy_average(
            room_id=room_id,
            time_slot=time_slot,
            target_date=date,
            window_days=self._settings.prediction_rolling_window_days,
        )
        if rolling_average is None:
            rolling_average = historical_frequency

        feature_row = {
            "day_of_week": parsed_date.weekday(),
            "time_slot": time_slot,
            "room_type": room.room_type,
            "historical_occupancy_frequency": float(historical_frequency),
            "rolling_7d_occupancy_average": float(rolling_average),
        }
        return pd.DataFrame([feature_row], columns=self._FEATURE_COLUMNS)

    def train_model(self) -> None:
        """Train baseline model once and cache it in memory."""

        with self._model_lock:
            logger.info("Prediction training started")
            records = self._repository.get_booking_history_for_training()
            self._training_rows = len(records)
            if self._training_rows < self._settings.prediction_min_training_rows:
                raise ModelNotReadyError(
                    "Insufficient booking history for model training"
                )

            training_frame = self._build_training_frame(records)
            if training_frame.empty:
                raise ModelNotReadyError(
                    "Training data is empty after feature engineering"
                )

            x_train = training_frame[self._FEATURE_COLUMNS]
            y_train = training_frame["occupied"].astype(int)

            preprocessor = ColumnTransformer(
                transformers=[
                    (
                        "categorical",
                        OneHotEncoder(handle_unknown="ignore"),
                        ["time_slot", "room_type"],
                    ),
                    (
                        "numerical",
                        "passthrough",
                        [
                            "day_of_week",
                            "historical_occupancy_frequency",
                            "rolling_7d_occupancy_average",
                        ],
                    ),
                ]
            )

            if y_train.nunique() >= 2:
                classifier = LogisticRegression(
                    max_iter=self._settings.prediction_model_max_iter,
                    random_state=self._settings.prediction_random_state,
                )
                model_name = "logistic_regression"
            else:
                classifier = DummyClassifier(strategy="most_frequent")
                model_name = "dummy_most_frequent"
                logger.warning(
                    "Training labels contained a single class. Falling back to %s",
                    model_name,
                )

            pipeline = Pipeline(
                steps=[
                    ("preprocessor", preprocessor),
                    ("classifier", classifier),
                ]
            )
            pipeline.fit(x_train, y_train)

            self._model = pipeline
            self._trained_at = datetime.now(timezone.utc)
            trained_at = self._trained_at.isoformat()
            self._model_metadata = ModelMetadata(
                model_type=model_name,
                model_version=self._settings.prediction_model_version,
                trained_at=trained_at,
                training_rows=self._training_rows,
            )
            self._repository.save_model_metadata(
                model_type=model_name,
                model_version=self._settings.prediction_model_version,
                trained_at=trained_at,
            )
            logger.info(
                "Prediction training completed | rows=%s | model=%s | version=%s | trained_at=%s",
                self._training_rows,
                model_name,
                self._settings.prediction_model_version,
                trained_at,
            )

    def retrain_model(self) -> None:
        """Explicit retraining hook for operators and future admin endpoint use."""
        logger.info("Manual model retraining requested")
        self.train_model()

    def _get_occupancy_probability(self, feature_frame: pd.DataFrame) -> float:
        if self._model is None:
            raise ModelNotReadyError("Model is not trained; call train_model() first")

        classes = list(self._model.classes_)  # type: ignore[attr-defined]
        probabilities = self._model.predict_proba(feature_frame)[0]

        if 1 in classes:
            occupied_idx = classes.index(1)
            return float(probabilities[occupied_idx])

        # Defensive fallback if estimator only knows class 0.
        return 0.0

    def get_model_metadata(self) -> dict[str, Any]:
        with self._model_lock:
            if self._model_metadata is not None:
                return dict(self._model_metadata.to_dict())
            persisted = self._repository.get_model_metadata()
            if persisted is None:
                raise ModelNotReadyError("Model metadata is unavailable; train model first")
            return dict(persisted)

    def predict(
        self,
        room_id: int,
        date: str,
        time_slot: str,
        *,
        persist: bool = True,
    ) -> Dict[str, float]:
        """Run availability inference with optional persistence."""
        with self._model_lock:
            feature_frame = self.prepare_features(
                room_id=room_id,
                date=date,
                time_slot=time_slot,
            )
            occupancy_probability = self._get_occupancy_probability(feature_frame)
            idle_probability = max(0.0, min(1.0, 1.0 - occupancy_probability))
            confidence_score = abs(idle_probability - 0.5) * 2.0

            if persist:
                self._repository.save_prediction(
                    room_id=room_id,
                    date=date,
                    time_slot=time_slot,
                    idle_probability=idle_probability,
                )

            result = PredictionResponse(
                idle_probability=idle_probability,
                confidence_score=confidence_score,
            )
            logger.info(
                (
                    "Prediction inference completed | room_id=%s | date=%s | "
                    "time_slot=%s | idle_probability=%.6f | confidence_score=%.6f"
                ),
                room_id,
                date,
                time_slot,
                idle_probability,
                confidence_score,
            )
            return result.to_dict()
