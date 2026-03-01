# SIET Demo Guide

## Prerequisites

- Python 3.11+
- All packages installed from `requirements.txt`
- Server running: `python main.py`

---

## Quick Start (3 commands)

```bash
pip install -r requirements.txt
python main.py
# Open http://127.0.0.1:8000/dashboard
```

---

## Browser Demo Flow

The dashboard shows a **login screen first**. The full workflow is revealed only after
successful authentication.

| Step | Action | What Happens |
|------|--------|--------------|
| 1 | Enter `admin-token` → **Login** | Session token issued. Date/slot pre-filled from first pending request. |
| 2 | Click **Predict** | Idle probabilities computed and displayed for all 10 rooms. |
| 3 | Click **Allocate** | CP-SAT runs. Results table fills with stakeholder assignments. |
| 4 | Check **Enable Temporary Overrides** → Click **Run Simulation** | What-if with priority weight 1.20 vs baseline. |
| 5 | Read **Metrics (Before vs After)** | Four metrics update: idle activation rate, simulated rate, efficiency, delta. |
| 6 | Click **Approve** | Draft committed. Requests marked ALLOCATED. |
| 7 | Click **Refresh Metrics** | Confirms post-approval state. |

The `ADMIN_TOKEN` field is a password input — it is never shown in plain text.
After login, a small "Logged in as admin / Logout" badge appears in the header.

---

## CLI Demo (curl-based)

```bash
# Requires the server to be running already
bash scripts/demo.sh
```

Output example:
```
============================================================
  SIET Space Utilization Digital Twin — Demo Flow
============================================================

[ 1/7 ] Login...
        Token: Ax7fQ3Rp...
[ 2/7 ] Loading demo context...
        Date=2026-02-23  Slot=09-11  Pending requests=8
[ 3/7 ] Running predictions for 2026-02-23 09-11...
        Predictions returned: 10 rooms
[ 4/7 ] Running allocation for 2026-02-23 09-11...
        Objective value=3.4758  Fairness (Jain's)=0.8889
[ 5/7 ] Running what-if simulation...
        Utilization delta=0.10  Request change=1
[ 6/7 ] Reading metrics...
        Baseline=0.40  Simulated=0.50  Efficiency=6.46  Delta%=10.00
[ 7/7 ] Approving allocation...
        Approved allocations: 3

============================================================
  Demo complete. All 7 steps passed.
============================================================
```

---

## Environment Validation

Run before the demo to verify all 7 system checks pass:

```bash
python scripts/validate_environment.py
```

Expected output:
```
============================================
 SIET Environment Validation
============================================
 [PASS] Python 3.x.x
 [PASS] Required packages: all importable
 [PASS] Database initialization
 [PASS] Synthetic dataset: 840 rows
 [PASS] Model training
 [PASS] Prediction inference: idle=0.xxxx confidence=0.xxxx
 [PASS] Demo request seeding: 8 requests
============================================
 All checks passed. Environment is ready.
============================================
```

---

## Demo Request Inventory

8 deterministic requests are seeded on first startup across 3 dates and 6 stakeholders:

| Date | Slot | Stakeholder | Capacity | Priority |
|------|------|-------------|----------|----------|
| 2026-02-23 | 09-11 | Dept-Engineering | 20 | 1.60 |
| 2026-02-23 | 09-11 | Dept-Science | 28 | 1.40 |
| 2026-02-23 | 09-11 | Student-Innovation | 14 | 1.10 |
| 2026-02-23 | 11-13 | Events | 38 | 1.80 |
| 2026-02-24 | 14-16 | Dept-CS | 18 | 1.25 |
| 2026-02-24 | 14-16 | Operations | 42 | 1.55 |
| 2026-02-25 | 11-13 | Community-Lab | 12 | 1.05 |
| 2026-02-23 | 11-13 | Research-Center | 25 | 1.30 |

---

## Key Engineering Points to Highlight

**No look-ahead data leakage in ML features:**
`historical_occupancy_frequency` uses cumulative mean with `cumcount()` shift.
`rolling_7d_occupancy_average` uses `shift(1).rolling(7)`. Both prevent future
data contaminating training features — a common mistake in time-series ML.

**Simulation is provably non-mutating:**
`SimulationService` uses `copy.deepcopy()` on the dataset and `persist=False` on
every prediction call. The test suite verifies this by asserting identical row counts
in `AllocationLogs`, `Predictions`, `DemandForecastLogs`, and `Requests` before and
after each simulation run.

**Greedy fallback is production-quality:**
The fallback is not a stub. It implements capacity filtering, idle threshold filtering,
stakeholder cap enforcement, and deterministic tie-breaking by idle probability → capacity
→ room_id. It triggers automatically on three conditions: OR-Tools unavailability,
solver infeasibility, and OPTIMAL status with zero assignments despite feasible pairs.

**Authentication uses session separation:**
`POST /login` generates `secrets.token_urlsafe(32)` as the session token and stores it
in memory. The admin secret is validated once but never transmitted again. Bearer tokens
are validated against the stored session token, not the original secret.
