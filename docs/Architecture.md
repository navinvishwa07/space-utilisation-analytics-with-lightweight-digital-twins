# System Architecture

## 1. High-Level Architecture

Streamlit Dashboard
        |
FastAPI Backend
        |
-------------------------
| Prediction Module     |
| Matching Module       |
| Simulation Module     |
-------------------------
        |
CSV / SQLite Data Store

---

## 2. Layered Architecture

Controller Layer
- API endpoints
- Input validation

Service Layer
- Prediction service
- Matching service
- Simulation service

Domain Layer
- Room model
- Booking request model
- Constraint logic

Data Layer
- CSV / SQLite access
- No hardcoded paths

---

## 3. Prediction Module

Model: Logistic Regression  
Inputs:
- Day of week
- Time slot
- Historical utilization %
- Room type
Output:
- Idle probability (0–1)

Model version logged.

---

## 4. Matching Engine

Optimization: OR-Tools Integer Programming

Objective:
Maximize idle_probability × priority_weight

Constraints:
- Capacity constraint
- Non-overlap constraint
- One allocation per slot
- Deterministic assignment

Fallback:
Greedy allocator if solver fails.

---

## 5. Simulation Engine

Calculates:
Pre-allocation utilization  
Post-allocation utilization  
Improvement percentage  

---

## 6. Observability

Structured JSON logs  
Request ID tagging  
Model version logging  
Allocation decision logging  

---

## 7. Failure Isolation

Prediction failure → default baseline probability  
Solver failure → greedy fallback  
System restart → reload state from dataset  