"""Domain-level validation rules for allocation optimization."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AllocationConfig:
    idle_probability_threshold: float
    stakeholder_usage_cap: float
    solver_max_time_seconds: int
    objective_scale: int
    cp_sat_workers: int


def validate_allocation_config(config: AllocationConfig) -> None:
    if not 0.0 <= config.idle_probability_threshold <= 1.0:
        raise ValueError("idle_probability_threshold must be between 0 and 1")
    if not 0.0 < config.stakeholder_usage_cap <= 1.0:
        raise ValueError("stakeholder_usage_cap must be in (0, 1]")
    if config.solver_max_time_seconds <= 0:
        raise ValueError("solver_max_time_seconds must be > 0")
    if config.objective_scale <= 0:
        raise ValueError("objective_scale must be > 0")
    if config.cp_sat_workers <= 0:
        raise ValueError("cp_sat_workers must be > 0")
