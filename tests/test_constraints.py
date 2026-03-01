from __future__ import annotations

import pytest

from backend.domain.constraints import AllocationConfig, validate_allocation_config


<<<<<<< Updated upstream
def test_validate_allocation_config_accepts_valid_values():
    config = AllocationConfig(
        idle_probability_threshold=0.5,
        stakeholder_usage_cap=0.7,
=======
def valid_config(**overrides) -> AllocationConfig:
    base = AllocationConfig(
        idle_probability_threshold=0.5,
        stakeholder_usage_cap=0.6,
>>>>>>> Stashed changes
        solver_max_time_seconds=10,
        solver_random_seed=42,
        objective_scale=1000,
        cp_sat_workers=2,
    )
<<<<<<< Updated upstream
    validate_allocation_config(config)


@pytest.mark.parametrize(
    "config",
    [
        AllocationConfig(-0.1, 0.5, 10, 42, 1000, 2),
        AllocationConfig(1.1, 0.5, 10, 42, 1000, 2),
        AllocationConfig(0.5, 0.0, 10, 42, 1000, 2),
        AllocationConfig(0.5, 1.1, 10, 42, 1000, 2),
        AllocationConfig(0.5, 0.5, 0, 42, 1000, 2),
        AllocationConfig(0.5, 0.5, 10, -1, 1000, 2),
        AllocationConfig(0.5, 0.5, 10, 42, 0, 2),
        AllocationConfig(0.5, 0.5, 10, 42, 1000, 0),
    ],
)
def test_validate_allocation_config_rejects_invalid_values(config):
    with pytest.raises(ValueError):
        validate_allocation_config(config)
=======
    return AllocationConfig(**{**base.__dict__, **overrides})


def test_valid_config_passes() -> None:
    validate_allocation_config(valid_config())


def test_idle_probability_threshold_below_zero_fails() -> None:
    with pytest.raises(ValueError):
        validate_allocation_config(valid_config(idle_probability_threshold=-0.01))


def test_idle_probability_threshold_above_one_fails() -> None:
    with pytest.raises(ValueError):
        validate_allocation_config(valid_config(idle_probability_threshold=1.01))


def test_stakeholder_usage_cap_zero_fails() -> None:
    with pytest.raises(ValueError):
        validate_allocation_config(valid_config(stakeholder_usage_cap=0.0))


def test_stakeholder_usage_cap_above_one_fails() -> None:
    with pytest.raises(ValueError):
        validate_allocation_config(valid_config(stakeholder_usage_cap=1.01))


def test_solver_max_time_seconds_zero_fails() -> None:
    with pytest.raises(ValueError):
        validate_allocation_config(valid_config(solver_max_time_seconds=0))


def test_solver_random_seed_negative_fails() -> None:
    with pytest.raises(ValueError):
        validate_allocation_config(valid_config(solver_random_seed=-1))


def test_objective_scale_zero_fails() -> None:
    with pytest.raises(ValueError):
        validate_allocation_config(valid_config(objective_scale=0))


def test_cp_sat_workers_zero_fails() -> None:
    with pytest.raises(ValueError):
        validate_allocation_config(valid_config(cp_sat_workers=0))


def test_boundary_values_pass() -> None:
    validate_allocation_config(
        valid_config(
            idle_probability_threshold=0.0,
            stakeholder_usage_cap=1.0,
        )
    )
>>>>>>> Stashed changes
