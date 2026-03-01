# Shared Infrastructure Exchange Twin (SIET)
## Hackathon MVP Definition

---

## MVP Objective

Build a lightweight digital twin that:

- Predicts idle room availability
- Forecasts demand intensity
- Optimizes fair allocation of unused spaces
- Simulates scheduling changes before confirmation

The MVP focuses on a single campus or institution with 10–20 modeled rooms.

---

## MVP Scope

### Included

- Digital twin data model for rooms
- Synthetic historical booking dataset
- Availability prediction model
- Demand forecasting model
- Fairness-aware allocation engine (OR-Tools)
- What-if simulation engine
- HTML Admin Dashboard (login screen → full workflow, served by FastAPI at `/dashboard`)
- Allocation audit logs

### Excluded

- IoT hardware integration
- Real-time sensor feeds
- Multi-city scaling
- Advanced climate modeling
- Fully automated approvals

---

## Digital Twin Model

Each room contains:

- Room ID
- Capacity
- Room type
- Available time blocks
- Historical usage frequency
- Constraint flags (locked, restricted, etc.)

---

## Core MVP Components

### 1. Availability Predictor
Predict probability of idle space for each room/time slot using:
- Day of week
- Time block
- Room type
- Historical booking frequency

Output:
- Idle probability score
- Confidence score

---

### 2. Demand Forecaster

Aggregate booking requests by time block.

Output:
- Demand intensity score per slot

---

### 3. Allocation Engine

Objective:
Maximize utilization of predicted idle rooms.

Constraints:
- No double booking
- Capacity limit enforcement
- Priority tier weighting
- Usage share cap per stakeholder

---

### 4. What-If Simulation

Admin can:
- Block a room
- Add high-priority event
- Modify priority weights

System re-runs prediction + allocation and shows impact delta.

---

## Demo Narrative

“We predict idle capacity before waste occurs and intelligently redistribute it using fairness-aware optimization.”