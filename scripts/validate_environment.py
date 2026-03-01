#!/usr/bin/env python3
"""Validate local SIET environment readiness."""

from __future__ import annotations

import importlib
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.repository.data_repository import DataRepository
from backend.services.prediction_service import AvailabilityPredictionService
from backend.utils.config import get_settings

SEPARATOR_LINE = "=" * 44


def _print_result(name: str, success: bool, detail: str = "") -> tuple[bool, str]:
    if success:
        return True, f"[PASS] {name}{detail}"
    return False, f"[FAIL] {name}: {detail}"


def main() -> int:
    results: list[str] = []
    all_passed = True
    temp_dir = tempfile.mkdtemp(prefix="siet-env-")

    # CHECK 1 — Python version >= 3.11
    if sys.version_info >= (3, 11):
        ok, line = _print_result("Python " + sys.version.split()[0], True)
    else:
        ok, line = _print_result(
            "Python version >= 3.11",
            False,
            f"found {sys.version.split()[0]}",
        )
    results.append(line)
    all_passed = all_passed and ok

    # CHECK 2 — Required packages importable with versions
    package_specs = [
        ("fastapi", "fastapi"),
        ("uvicorn", "uvicorn"),
        ("pydantic", "pydantic"),
        ("numpy", "numpy"),
        ("pandas", "pandas"),
        ("sklearn", "scikit-learn"),
        ("ortools", "ortools"),
        ("httpx", "httpx"),
        ("pytest", "pytest"),
    ]
    import_errors: list[str] = []
    try:
        from importlib.metadata import version
    except Exception:  # pragma: no cover
        version = None  # type: ignore[assignment]
    for module_name, dist_name in package_specs:
        try:
            module = importlib.import_module(module_name)
            if version is not None:
                _ = version(dist_name)
            else:
                _ = getattr(module, "__version__", "unknown")
        except Exception as exc:  # pragma: no cover - runtime guard
            import_errors.append(f"{module_name} ({exc})")
    if import_errors:
        ok, line = _print_result(
            "Required packages",
            False,
            "missing/unimportable -> " + "; ".join(import_errors),
        )
    else:
        ok, line = _print_result("Required packages: all importable", True)
    results.append(line)
    all_passed = all_passed and ok

    try:
        base_settings = get_settings()
        temp_db_path = Path(temp_dir) / "siet_validation.db"
        validation_settings = replace(
            base_settings,
            database_path=temp_db_path,
            prediction_min_training_rows=1,
        )
        repository = DataRepository(validation_settings)

        # CHECK 3 — Database initialization
        try:
            repository.initialize_database()
            ok, line = _print_result("Database initialization", True)
        except Exception as exc:
            ok, line = _print_result("Database initialization", False, str(exc))
        results.append(line)
        all_passed = all_passed and ok

        # CHECK 4 — Synthetic data seeding (840 rows)
        seeded_rows = 0
        try:
            repository.seed_synthetic_data()
            with sqlite3.connect(temp_db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM BookingHistory;")
                seeded_rows = int(cursor.fetchone()[0])
            if seeded_rows != 840:
                raise RuntimeError(f"expected 840 rows, got {seeded_rows}")
            ok, line = _print_result("Synthetic dataset: 840 rows", True)
        except Exception as exc:
            ok, line = _print_result("Synthetic dataset", False, str(exc))
        results.append(line)
        all_passed = all_passed and ok

        # CHECK 5 — Model training
        prediction_service = AvailabilityPredictionService(
            repository=repository,
            settings=validation_settings,
        )
        try:
            prediction_service.train_model()
            ok, line = _print_result("Model training", True)
        except Exception as exc:
            ok, line = _print_result("Model training", False, str(exc))
        results.append(line)
        all_passed = all_passed and ok

        # CHECK 6 — Prediction inference
        try:
            inference = prediction_service.predict(
                room_id=1,
                date="2026-02-23",
                time_slot="09-11",
                persist=False,
            )
            idle_probability = float(inference["idle_probability"])
            confidence_score = float(inference["confidence_score"])
            if not (0.0 <= idle_probability <= 1.0 and 0.0 <= confidence_score <= 1.0):
                raise RuntimeError("prediction values out of [0,1] bounds")
            ok, line = _print_result(
                "Prediction inference",
                True,
                f": idle={idle_probability:.4f} confidence={confidence_score:.4f}",
            )
        except Exception as exc:
            ok, line = _print_result("Prediction inference", False, str(exc))
        results.append(line)
        all_passed = all_passed and ok

        # CHECK 7 — Demo request seeding
        try:
            seeded_demo = repository.seed_demo_requests_if_empty()
            if not (5 <= seeded_demo <= 10):
                raise RuntimeError(f"expected seeded rows between 5 and 10, got {seeded_demo}")
            ok, line = _print_result(
                "Demo request seeding",
                True,
                f": {seeded_demo} requests",
            )
        except Exception as exc:
            ok, line = _print_result("Demo request seeding", False, str(exc))
        results.append(line)
        all_passed = all_passed and ok

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    print(SEPARATOR_LINE)
    print(" SIET Environment Validation")
    print(SEPARATOR_LINE)
    for line in results:
        print(f" {line}")
    print(SEPARATOR_LINE)
    if all_passed:
        print(" All checks passed. Environment is ready.")
        print(SEPARATOR_LINE)
        return 0
    print(" One or more checks failed.")
    print(SEPARATOR_LINE)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
