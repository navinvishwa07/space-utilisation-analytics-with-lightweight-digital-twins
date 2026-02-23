"""Domain models for demand forecasting and allocation optimization."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Room:
    room_id: int
    capacity: int


@dataclass(frozen=True)
class AllocationRequest:
    request_id: int
    requested_capacity: int
    requested_date: str
    requested_time_slot: str
    priority_weight: float
    stakeholder_id: str


@dataclass(frozen=True)
class IdlePrediction:
    room_id: int
    date: str
    time_slot: str
    idle_probability: float


@dataclass(frozen=True)
class DemandForecast:
    time_slot: str
    historical_count: int
    demand_intensity_score: float


@dataclass(frozen=True)
class AllocationDecision:
    request_id: int
    room_id: int
    score: float
    stakeholder_id: str


@dataclass(frozen=True)
class OptimizationResult:
    allocations: list[AllocationDecision]
    objective_value: float
    fairness_metric: float
    unassigned_request_ids: list[int]
