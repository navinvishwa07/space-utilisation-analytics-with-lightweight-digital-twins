# Product Requirements Document (PRD)
## Space Utilization Digital Twin

---

## 1. Overview

The Space Utilization Digital Twin is a predictive and optimization-driven system that identifies underutilized institutional spaces and intelligently allocates them to external demand while preserving fairness and efficiency.

The system combines:

- Historical occupancy modeling
- Idle probability prediction
- Demand forecasting
- Constraint-based optimization
- Simulation-based policy testing

The core objective is to maximize idle space activation while balancing stakeholder fairness.

---

## 2. Core Objectives

- Predict room idle probability using historical booking data
- Forecast demand intensity across time blocks
- Allocate space using constraint optimization
- Provide simulation mode for policy experimentation
- Preserve system reproducibility and determinism

---

## 3. System Architecture Principles

- Clean separation: Controllers → Services → Repository
- No direct database access inside services
- Idempotent startup behavior
- Deterministic synthetic dataset generation
- Config-driven thresholds (no hardcoding)
- SQLite-backed persistence
- Optimization powered by CP-SAT solver

---

## 4. Data Layer (Day 1)

### Tables

- Rooms
- BookingHistory
- Requests
- Predictions
- AllocationLogs
- DemandForecastLogs

### Synthetic Dataset

The system uses a deterministic synthetic dataset as the historical source of truth.

Dataset Specifications:

- 10 rooms (IDs 1–10)
- 21 days of historical data
- 4 daily time slots:
  - 09-11
  - 11-13
  - 14-16
  - 16-18
- Weekday occupancy probability: 0.65–0.75
- Weekend occupancy probability: 0.30–0.40
- Fixed random seed for reproducibility
- No derived features stored
- No missing values

Startup behavior:

- If `synthetic_dataset.csv` exists → validate and load
- If not → generate deterministically and load
- No duplicate inserts on restart
- Unique composite key on (room_id, date, time_slot)

---

## 5. Idle Probability Prediction (Day 2)

### Model Design

- Logistic Regression classifier
- Trained on BookingHistory
- Feature engineering:
  - Day of week
  - Time slot encoding
  - Historical frequency
  - Room ID

### Output

- Idle probability (0–1)
- Confidence score (heuristic-based)
- Stored in Predictions table

### Operational Behavior

- Model trains once at startup
- Inference does not retrain
- Predictions persisted for auditability

---

## 6. Demand Forecasting (Day 3)

The system aggregates historical requests by:

- Date
- Time block

A demand intensity score is computed and stored in DemandForecastLogs.

Forecast data is used for analytics and scenario evaluation.

---

## 7. Allocation Engine (Day 3)

### Optimization Model

The allocation engine uses a CP-SAT optimization model.

Objective Function:

Maximize:

```
idle_probability × priority_weight
```

This is a **weighted optimization model**, not a strict tier enforcement system.

### Hard Constraints

- Room capacity limit
- No time-slot conflicts (per optimization run)
- Stakeholder usage cap
- Minimum idle probability threshold

### Priority Handling Design

Stakeholder priority is implemented as an objective weight rather than a blocking constraint.

This ensures:

- Higher-priority stakeholders are favored
- Overall utilization remains maximized
- The solver preserves global optimality
- The system avoids rigid hierarchical bottlenecks

Rationale:

Hard tier constraints can reduce total utilization and create infeasible allocations during high-demand periods. A weighted objective approach balances fairness with efficiency.

---

## 8. Simulation Mode (Day 4)

The system includes a policy simulation endpoint.

Capabilities:

- Inject temporary constraints
- Re-run prediction + optimization
- Compare baseline vs simulated utilization
- Compute delta utilization

Simulation rules:

- No writes to production tables
- In-memory constraint overrides only
- Deterministic outputs under fixed seed
- No state mutation across runs

---

## 9. Edge Case Handling

The system handles:

- No feasible solution scenarios
- Demand exceeding supply
- Zero available rooms
- Missing prediction data
- Invalid request inputs

---

## 10. Design Philosophy

The Digital Twin prioritizes:

**Utilization efficiency with fairness influence**

Rather than enforcing rigid hierarchical access control, the system dynamically balances stakeholder importance with global space activation goals.

This design makes the system adaptable across:

- Universities
- Public institutions
- NGOs
- Corporate shared infrastructure models

---

## 11. MVP Definition

The system qualifies as MVP-complete when:

- Synthetic dataset loads reproducibly
- Model trains deterministically
- Allocation engine runs with all constraints
- Simulation produces stable comparative metrics
- No runtime artifacts are committed to version control
- Architecture passes clean separation review

---

## 12. Future Enhancements

- True tier-based lexicographic optimization
- Multi-day rolling optimization
- Real-time demand streaming
- Dashboard visualization layer
- Explainability scoring for allocation decisions

---