"""Tests for allocation constraint validation logic.

Covers all six validation branches in validate_allocation_config().
"""

from __future__ import annotations

import pytest

from backend.domain.constraints import AllocationConfig, validate_allocation_config


def valid_config(**overrides) -> AllocationConfig:
    """Return a valid baseline AllocationConfig, optionally overriding fields."""
    defaults = {
        "idle_probability_threshold": 0.5,
        "stakeholder_usage_cap": 0.6,
        "solver_max_time_seconds": 10,
        "solver_random_seed": 42,
        "objective_scale": 1000,
        "cp_sat_workers": 2,
    }
    defaults.update(overrides)
    return AllocationConfig(**defaults)


# --- Baseline pass ---

def test_valid_config_passes() -> None:
    """A fully valid config must not raise."""
    validate_allocation_config(valid_config())


# --- idle_probability_threshold ---

def test_idle_probability_threshold_below_zero_raises() -> None:
    with pytest.raises(ValueError):
        validate_allocation_config(valid_config(idle_probability_threshold=-0.01))


def test_idle_probability_threshold_above_one_raises() -> None:
    with pytest.raises(ValueError):
        validate_allocation_config(valid_config(idle_probability_threshold=1.01))


# --- stakeholder_usage_cap ---

def test_stakeholder_usage_cap_zero_raises() -> None:
    with pytest.raises(ValueError):
        validate_allocation_config(valid_config(stakeholder_usage_cap=0.0))


def test_stakeholder_usage_cap_above_one_raises() -> None:
    with pytest.raises(ValueError):
        validate_allocation_config(valid_config(stakeholder_usage_cap=1.01))


# --- solver_max_time_seconds ---

def test_solver_max_time_seconds_zero_raises() -> None:
    with pytest.raises(ValueError):
        validate_allocation_config(valid_config(solver_max_time_seconds=0))


def test_solver_max_time_seconds_negative_raises() -> None:
    with pytest.raises(ValueError):
        validate_allocation_config(valid_config(solver_max_time_seconds=-1))


# --- solver_random_seed ---

def test_solver_random_seed_negative_raises() -> None:
    with pytest.raises(ValueError):
        validate_allocation_config(valid_config(solver_random_seed=-1))


# --- objective_scale ---

def test_objective_scale_zero_raises() -> None:
    with pytest.raises(ValueError):
        validate_allocation_config(valid_config(objective_scale=0))


def test_objective_scale_negative_raises() -> None:
    with pytest.raises(ValueError):
        validate_allocation_config(valid_config(objective_scale=-100))


# --- cp_sat_workers ---

def test_cp_sat_workers_zero_raises() -> None:
    with pytest.raises(ValueError):
        validate_allocation_config(valid_config(cp_sat_workers=0))


def test_cp_sat_workers_negative_raises() -> None:
    with pytest.raises(ValueError):
        validate_allocation_config(valid_config(cp_sat_workers=-1))


# --- Boundary values ---

def test_idle_probability_threshold_zero_passes() -> None:
    """Exact lower boundary must pass."""
    validate_allocation_config(valid_config(idle_probability_threshold=0.0))


def test_idle_probability_threshold_one_passes() -> None:
    """Exact upper boundary must pass."""
    validate_allocation_config(valid_config(idle_probability_threshold=1.0))


def test_stakeholder_usage_cap_one_passes() -> None:
    """Exact upper boundary must pass (cap > 0 and <= 1)."""
    validate_allocation_config(valid_config(stakeholder_usage_cap=1.0))


def test_solver_random_seed_zero_passes() -> None:
    """Seed of zero is valid (not negative)."""
    validate_allocation_config(valid_config(solver_random_seed=0))
