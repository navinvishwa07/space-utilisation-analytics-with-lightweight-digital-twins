from __future__ import annotations

import pytest

from backend.domain.constraints import AllocationConfig, validate_allocation_config


def test_validate_allocation_config_accepts_valid_values():
    config = AllocationConfig(
        idle_probability_threshold=0.5,
        stakeholder_usage_cap=0.7,
        solver_max_time_seconds=10,
        solver_random_seed=42,
        objective_scale=1000,
        cp_sat_workers=2,
    )
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
