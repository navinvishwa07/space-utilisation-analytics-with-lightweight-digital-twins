# Product Requirements Document (PRD)

## Space Utilization Digital Twin

---

## 1. Overview

The Space Utilization Digital Twin is a predictive and optimization-driven system that identifies underutilized institutional spaces and intelligently allocates them to external demand while preserving fairness and efficiency.

The system integrates historical occupancy modeling, idle probability prediction, demand forecasting, constraint-based optimization, and simulation-driven policy testing.

The primary objective is to maximize idle space activation while balancing stakeholder fairness.

---

## 2. Problem Statement

Institutions frequently experience fragmented and underutilized infrastructure. Classrooms, auditoriums, halls, and parking spaces remain unused during certain time windows, while external demand for such infrastructure exists but is not dynamically matched.

Traditional booking systems are reactive. They do not:

- Predict idle capacity
- Optimize allocation under constraints
- Balance stakeholder priority dynamically
- Support policy simulation

This system addresses those gaps.

---

## 3. Core Objectives

- Predict room idle probability using historical booking data
- Forecast demand intensity across time blocks
- Allocate space using mathematical optimization
- Provide simulation mode for policy experimentation
- Maintain deterministic reproducibility

---

## 4. System Architecture Principles

- Strict separation: Controllers → Services → Repository
- No direct database access inside business logic services
- Idempotent startup initialization
- Deterministic synthetic dataset generation
- Config-driven thresholds
- SQLite-backed persistence layer
- CP-SAT solver for allocation optimization

---

## 5. Data Layer (Day 1)

### Tables

- Rooms
- BookingHistory
- Requests
- Predictions
- AllocationLogs
- DemandForecastLogs

### Synthetic Dataset Requirements

- 10 rooms
- 21 days of historical data
- 4 time slots per day:
  - 09-11
  - 11-13
  - 14-16
  - 16-18
- Weekday occupancy probability: 0.65–0.75
- Weekend occupancy probability: 0.30–0.40
- Fixed random seed
- No missing values
- No duplicate records
- Unique composite key (room_id, date, time_slot)

### Startup Behavior

- If synthetic_dataset.csv exists → validate and load
- If not → generate deterministically
- No duplicate inserts on restart
- Database seeding must be idempotent

---

## 6. Idle Probability Prediction (Day 2)

### Model

- Logistic Regression classifier
- Trained using BookingHistory table

### Features

- Day of week
- Time slot encoding
- Historical frequency
- Room ID encoding

### Output

- Idle probability score (0–1)
- Confidence score
- Persisted in Predictions table

### Operational Constraints

- Model trains once at startup
- No retraining during inference
- Predictions stored for audit and traceability

---

## 7. Demand Forecasting (Day 3)

The system aggregates request history to compute demand intensity per time block.

Output stored in DemandForecastLogs.

Forecasting supports:

- Allocation analytics
- Simulation evaluation
- Policy stress testing

---

## 8. Allocation Engine (Day 3)

### Optimization Model

Uses CP-SAT constraint solver.

Objective Function:

Maximize:

idle_probability × stakeholder_priority_weight

This is a weighted optimization design rather than rigid tier blocking.

### Hard Constraints

- Room capacity limit
- No overlapping allocations per room per slot
- Stakeholder usage cap
- Minimum idle probability threshold
- One allocation per request per slot

### Design Rationale

Weighted objective optimization ensures:

- High-priority stakeholders are favored
- Global utilization remains maximized
- Feasibility remains high under heavy demand
- System avoids rigid hierarchical inefficiencies

---

## 9. Simulation Mode (Day 4)

The system provides a policy simulation endpoint.

Capabilities:

- Inject temporary constraint overrides
- Re-run prediction and allocation
- Compare baseline vs simulated outcomes
- Compute utilization delta

Simulation Rules:

- No mutation of production tables
- In-memory overrides only
- Deterministic outputs under fixed seed
- No persistent side effects

---

## 10. Edge Case Handling

The system handles:

- No feasible allocation scenarios
- Demand exceeding supply
- Zero available rooms
- Missing prediction entries
- Invalid input payloads
- Duplicate request detection

---

## 11. MVP Definition

The system qualifies as MVP-complete when:

- Synthetic dataset loads reproducibly
- Model trains deterministically
- Allocation engine respects all constraints
- Simulation produces stable comparative metrics
- No runtime artifacts are version-controlled
- Clean architectural separation is maintained

---

## 12. Future Enhancements

- True lexicographic tier optimization
- Multi-day rolling allocation planning
- Real-time streaming demand ingestion
- Visualization dashboard
- Explainable allocation scoring
- Multi-institution federation support

---

## 13. Design Philosophy

The Digital Twin prioritizes:

Utilization efficiency with fairness influence.

The system balances optimization rigor with adaptability, making it applicable across universities, public institutions, NGOs, and shared infrastructure networks.