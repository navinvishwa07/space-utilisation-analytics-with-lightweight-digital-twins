# SIET — Space Utilisation Digital Twin

**AMD Slingshot Hackathon Submission**

A lightweight digital twin platform that predicts idle room capacity, forecasts demand,
optimises fair allocation using CP-SAT integer programming, and simulates policy changes
before committing them — all through a clean admin dashboard.

---

## Architecture

```
HTML Admin Dashboard  (dashboard/index.html)
          │
          ▼
FastAPI Backend  (uvicorn, single process)
          │
  ┌───────┼───────┐
  │       │       │
Predict  Alloc  Simulate
  │       │       │
  └───────┴───────┘
          │
   SQLite + CSV
```

**Four-layer separation, strictly enforced:**

```
backend/
  controllers/   ← HTTP routing and input validation only
  services/      ← All business logic (prediction, matching, simulation, auth, workflow)
  repository/    ← All SQLite access, zero business logic
  domain/        ← Pure dataclasses and constraint rules
  utils/         ← Config and logging
  data/          ← SQLite database + synthetic CSV
dashboard/
  index.html     ← Single-file HTML/JS admin dashboard
scripts/
  demo.sh                  ← Full 7-step demo via curl
  validate_environment.py  ← Pre-demo environment check
docs/
  API.md          ← Full endpoint reference
  DEMO.md         ← Step-by-step demo guide
  Architecture.md ← System design
  PRD.md          ← Product requirements
  MVP.md          ← MVP scope definition
  Plan.md         ← Execution plan
  Skills.md       ← Skills demonstrated
```

---

## Quick Start

### 1. Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env if needed — default ADMIN_TOKEN=admin-token works for local demo
```

### 3. Validate environment (optional but recommended)

```bash
python scripts/validate_environment.py
```

### 4. Run

```bash
python main.py
```

This starts the server **and opens the dashboard automatically** in your browser.

The dashboard will appear at `http://127.0.0.1:8000/dashboard`.

**Alternative (without browser auto-open):**
```bash
uvicorn app:app --reload
```

> **⚠️ Single-worker requirement:** The allocate → approve workflow stores the pending
> allocation draft in process memory. Always run with a single worker (the default).
> Running `uvicorn app:app --workers 4` will break the allocate → approve flow.

### 5. Open dashboard

```
http://127.0.0.1:8000/dashboard
```

Enter `admin-token` (or your configured `ADMIN_TOKEN`) to log in.

---

## Dashboard Workflow

The dashboard separates authentication from the workflow panels:

| Step | Action | Result |
|------|--------|--------|
| 1 | Enter ADMIN_TOKEN → Login | Session token issued. Demo context auto-loaded. |
| 2 | Click **Predict** | Idle probabilities computed for all 10 rooms. |
| 3 | Click **Allocate** | CP-SAT optimisation runs. Draft stored in memory. |
| 4 | Click **Run Simulation** | What-if scenario compared to baseline. |
| 5 | Read Metrics panel | Before/after utilisation, efficiency score, delta. |
| 6 | Click **Approve** | Draft persisted to AllocationLogs. Requests marked ALLOCATED. |
| 7 | Click **Refresh Metrics** | Metrics updated from latest simulation state. |

---

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/login` | No | Get session bearer token |
| GET | `/demo_context` | No | Load first pending window for dashboard pre-fill |
| POST | `/predict` | Yes | Idle probability for all rooms |
| POST | `/allocate` | Yes | Preview CP-SAT allocation (draft, not persisted) |
| POST | `/simulate` | Yes | In-memory what-if scenario with constraint overrides |
| POST | `/approve` | Yes | Persist pending draft to AllocationLogs |
| GET | `/metrics` | Yes | Four headline metrics (before vs after) |
| POST | `/predict_availability` | Yes | Single-room idle probability (legacy) |
| POST | `/optimize_allocation` | Yes | Raw allocation without draft workflow (legacy) |

See [`docs/API.md`](docs/API.md) for full request/response schemas.

---

## What Happens on Startup

Startup is **idempotent** — safe to restart without data loss:

1. Initialise SQLite schema (`backend/data/siet.db`)
2. Validate and load `backend/data/synthetic_dataset.csv` into `BookingHistory`
3. Seed 8 deterministic demo requests into `Requests` (only if empty)
4. Train LogisticRegression prediction model and register metadata in `ModelRegistry`

No duplicate rows are ever inserted on restarts.

---

## Synthetic Dataset

- **10 rooms** across 5 blocks (Classroom, Auditorium, Lab, Seminar types)
- **21 days** of booking history (2026-02-01 to 2026-02-21)
- **4 time slots** per day: `09-11`, `11-13`, `14-16`, `16-18`
- **840 rows** total, deterministic (`random.seed(42)`)
- Weekday occupancy probability: **0.65** | Weekend: **0.35**

---

## ML Model

**LogisticRegression** with `DummyClassifier` fallback if training labels are single-class.

Features (all leakage-free):
- `day_of_week` — integer (0–6)
- `time_slot` — OneHotEncoded
- `room_type` — OneHotEncoded
- `historical_occupancy_frequency` — cumulative mean (shift prevents look-ahead)
- `rolling_7d_occupancy_average` — shift(1).rolling(7) prevents look-ahead

Output: `idle_probability` ∈ [0,1], `confidence_score` = `2 × |idle − 0.5|`

---

## Allocation Engine

**CP-SAT integer programming** (OR-Tools) with deterministic **greedy fallback**.

Objective: `maximise Σ idle_probability × priority_weight`

Hard constraints:
- Room capacity ≥ requested capacity
- No room allocated to more than one request per slot
- One allocation per request maximum
- Only rooms above `idle_probability_threshold` are eligible
- Stakeholder usage capped at `stakeholder_usage_cap × total_requests`

Fallback triggers automatically when:
- OR-Tools is unavailable
- Solver returns infeasible/unknown status
- Solver returns OPTIMAL but zero allocations despite feasible pairs

Fairness: **Jain's index** computed across stakeholders for every allocation result.

---

## Simulation Engine

Fully isolated in-memory what-if analysis:

- `copy.deepcopy()` isolates dataset before applying overrides
- `persist=False` on all prediction calls — nothing written to DB
- Separate `simulation_solver_random_seed` for independent determinism
- Tests verify zero row-count changes across all tables after simulation

Override types: `idle_threshold`, `stakeholder_cap`, `capacity_override`, `priority_adjustment`

---

## Authentication

- `POST /login` validates `ADMIN_TOKEN` with `secrets.compare_digest`
- Returns an ephemeral session token (`secrets.token_urlsafe(32)`) — **distinct from the admin secret**
- All protected endpoints require `Authorization: Bearer <session_token>`
- `GET /demo_context` is public (no auth) for cold-demo dashboard loading

---

## Tests

```bash
pytest -q
```

Test suite covers:
- `test_prediction.py` — inference, persistence, model metadata
- `test_matching.py` — allocation service, endpoint, zero-idle edge case
- `test_simulation.py` — isolation, determinism, endpoint validation
- `test_dashboard_flow.py` — full end-to-end login → predict → allocate → simulate → approve
- `test_repository_seeding.py` — CSV generation, idempotency, demo request seeding
- `test_allocation_fallback.py` — greedy fallback, auto-prediction generation
- `test_constraints.py` — all six validation branches of AllocationConfig

---

## CLI Demo

```bash
# Server must be running in another terminal
bash scripts/demo.sh
```

Runs the full 7-step flow (login → demo context → predict → allocate → simulate →
metrics → approve) via curl and prints results. Uses `jq` if available.

---

## Documentation

| File | Description |
|------|-------------|
| [`docs/API.md`](docs/API.md) | Full REST API reference with request/response examples |
| [`docs/DEMO.md`](docs/DEMO.md) | Step-by-step demo guide with technical highlights |
| [`docs/Architecture.md`](docs/Architecture.md) | System design and layer descriptions |
| [`docs/PRD.md`](docs/PRD.md) | Product requirements document |
| [`docs/MVP.md`](docs/MVP.md) | MVP scope definition |
| [`docs/Plan.md`](docs/Plan.md) | 7-day hackathon execution plan |
| [`docs/Skills.md`](docs/Skills.md) | Engineering skills demonstrated |

---

## Project Constraints

- Single-worker deployment required (in-memory allocation draft)
- No multi-tenant support — single admin operator model
- No real-time sensor integration — synthetic historical data only
- SQLite only — no external database required
- No Streamlit — dashboard is pure HTML/JS served by FastAPI

---

## License

MIT — see [LICENSE](LICENSE)
