# SIET API Reference

**Base URL:** `http://127.0.0.1:8000`

**Authentication:** All protected endpoints require `Authorization: Bearer <session_token>`.
Obtain a session token via `POST /login`. The token is ephemeral and distinct from `ADMIN_TOKEN`.

---

## Public Endpoints

### GET /demo_context

Pre-loads the first pending request window for dashboard auto-fill. No auth required.

**Response:**
```json
{
  "default_date": "2026-02-23",
  "default_time_slot": "09-11",
  "pending_windows": [
    {
      "requested_date": "2026-02-23",
      "requested_time_slot": "09-11",
      "request_count": 3
    }
  ],
  "pending_request_count": 8
}
```

---

## Authentication

### POST /login

**Request:**
```json
{ "admin_token": "admin-token" }
```

**Response:**
```json
{ "access_token": "Ax7f...", "token_type": "bearer" }
```

| Status | Meaning |
|--------|---------|
| 200 | Login successful — use `access_token` as bearer |
| 401 | Invalid or missing admin token |

---

## Dashboard Workflow Endpoints (Protected)

### POST /predict

Computes idle probability for all 10 rooms for a given date and time slot.
Persists predictions to the `Predictions` table.

**Request:**
```json
{
  "date": "2026-02-23",
  "time_slot": "09-11"
}
```

**Response:**
```json
{
  "predictions": [
    {
      "room_id": 1,
      "date": "2026-02-23",
      "time_slot": "09-11",
      "predicted_idle_probability": 0.7241,
      "confidence_score": 0.4482
    }
  ]
}
```

---

### POST /allocate

Runs CP-SAT allocation optimisation for the given date/slot. Stores a draft in memory
for subsequent `/approve`. Does **not** write to `AllocationLogs`.

**Request:**
```json
{
  "requested_date": "2026-02-23",
  "requested_time_slot": "09-11",
  "idle_probability_threshold": 0.25,
  "stakeholder_usage_cap": 0.60
}
```

**Response:**
```json
{
  "allocations": [
    {
      "room_id": 3,
      "stakeholder": "Dept-Engineering",
      "time_slot": "09-11",
      "allocation_score": 1.1586,
      "priority_weight": 1.60,
      "constraint_status": "SATISFIED"
    }
  ],
  "objective_value": 3.4758,
  "fairness_metric": 0.8889,
  "unassigned_request_ids": []
}
```

---

### POST /simulate

Runs a fully isolated in-memory what-if scenario. Does **not** write to any table.

**Request:**
```json
{
  "stakeholder_priority_weight": 1.20,
  "idle_probability_threshold": 0.30,
  "stakeholder_usage_cap": 0.70,
  "temporary_constraints": {
    "capacity_override": { "1": 35 },
    "priority_adjustment": { "Dept-Engineering": 1.5 }
  }
}
```

**Response:**
```json
{
  "baseline": {
    "utilization_rate": 0.40,
    "requests_satisfied": 4,
    "objective_value": 5.12,
    "total_rooms_utilized": 4,
    "average_idle_probability_utilized": 0.78,
    "fairness_metric": 0.89
  },
  "simulation": {
    "utilization_rate": 0.50,
    "requests_satisfied": 5,
    "objective_value": 6.46,
    "total_rooms_utilized": 5,
    "average_idle_probability_utilized": 0.76,
    "fairness_metric": 0.91
  },
  "delta": {
    "utilization_change": 0.10,
    "request_change": 1,
    "objective_change": 1.34,
    "total_rooms_utilized_change": 1,
    "avg_idle_probability_change": -0.02,
    "fairness_change": 0.02
  }
}
```

---

### POST /approve

Persists the pending allocation draft to `AllocationLogs` and marks requests as `ALLOCATED`.
Clears the draft after success. Must be preceded by `/allocate`.

**Response:**
```json
{
  "status": "APPROVED",
  "approved_allocations_count": 3,
  "objective_value": 3.4758,
  "fairness_metric": 0.8889
}
```

| Status | Meaning |
|--------|---------|
| 200 | Allocation approved and persisted |
| 400 | No draft found — call `/allocate` first |

---

### GET /metrics

Returns four headline metrics from the most recent simulation. If no simulation has
been run, triggers a baseline simulation automatically.

**Response:**
```json
{
  "baseline_idle_activation_rate": 0.40,
  "simulated_idle_activation_rate": 0.50,
  "allocation_efficiency_score": 6.46,
  "utilization_delta_percentage": 10.00
}
```

---

## Legacy Endpoints (Protected)

These bypass the two-phase draft workflow and are used for testing and raw access.

### POST /predict_availability

Single-room idle probability prediction.

**Request:**
```json
{ "room_id": 1, "date": "2026-02-23", "time_slot": "09-11" }
```

**Response:**
```json
{ "idle_probability": 0.7241, "confidence_score": 0.4482 }
```

### POST /optimize_allocation

Raw CP-SAT optimisation without draft storage.

**Request:** Same as `/allocate`.

**Response:**
```json
{
  "allocations": [{ "request_id": 1, "room_id": 3, "score": 1.1586 }],
  "objective_value": 3.4758,
  "fairness_metric": 0.8889
}
```

---

## Error Format

All errors use FastAPI's standard envelope:

```json
{ "detail": "Human-readable description" }
```

| Status | Meaning |
|--------|---------|
| 400 | Invalid input or business rule violation |
| 401 | Missing or invalid bearer token |
| 404 | Resource not found (e.g. unknown room_id) |
| 503 | Service unavailable (model not trained, OR-Tools missing) |
