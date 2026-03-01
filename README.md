# SIET Space Utilization Digital Twin

FastAPI-based space utilization analytics system with:
- deterministic synthetic occupancy data,
- logistic-regression idle prediction,
- CP-SAT weighted allocation with deterministic greedy fallback,
- in-memory what-if simulation,
- authenticated admin dashboard flow.

## What Happens On Startup

When the app starts, startup is idempotent and deterministic:
1. Initialize SQLite schema at `backend/data/siet.db`.
2. Seed synthetic booking history from `backend/data/synthetic_dataset.csv` if needed.
3. Seed deterministic demo requests **only if** `Requests` is empty.
4. Train and register prediction model metadata (`ModelRegistry`).

No duplicate synthetic rows are inserted on restarts.  
Demo requests are seeded once and never duplicated if requests already exist.

## Determinism Guarantees

- Synthetic CSV generation uses fixed seed and fixed reference end date.
- If synthetic CSV already exists, it is reused (not regenerated).
- Allocation solver seed is fixed.
- Greedy fallback is deterministic (stable sort strategy).
- Simulation is in-memory and does not mutate production data/tables.

## Architecture

```
backend/
  controllers/   # FastAPI routes and request/response validation
  services/      # Business logic (prediction, allocation, simulation, auth, workflow)
  repository/    # SQLite access only
  domain/        # Core models and constraints
  utils/         # config and logging
  data/          # database + synthetic csv
dashboard/
  index.html     # browser dashboard (served by FastAPI)
main.py          # ASGI entrypoint for uvicorn main:app --reload
```

Layering rule:
- Controllers -> Services -> Repository.
- Services do not access SQLite directly.

## Authentication

- `POST /login` validates `ADMIN_TOKEN` and returns bearer token.
- Protected endpoints require `Authorization: Bearer <token>`.
- Default token is `admin-token` unless overridden via `ADMIN_TOKEN`.

## API Endpoints

- `POST /login`
- `POST /predict`
- `POST /allocate`
- `POST /simulate`
- `POST /approve`
- `GET /metrics`
- `GET /demo_context`

Legacy service endpoints (also protected):
- `POST /predict_availability`
- `POST /optimize_allocation`

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Environment Setup

Copy `.env.example` to `.env` and set your `ADMIN_TOKEN`:

```bash
cp .env.example .env
```

Edit `.env` to set a token value. The default `admin-token` is fine for local demo.
For any shared or non-local environment, use a strong random secret.

Alternatively, export directly in your shell:

```bash
export ADMIN_TOKEN="your-secure-token"
```

## Run

```bash
export ADMIN_TOKEN="admin-token"
uvicorn main:app --reload
```

> **⚠️ Single-worker requirement:** The allocate → approve workflow stores the pending
> allocation draft in process memory. Always run with a single worker (the `--reload`
> default). Running `uvicorn main:app --workers 4` will cause `/approve` to fail with
> "No allocation draft found" because the draft lives in a different worker process.
> Multi-worker session persistence (e.g., Redis-backed draft store) is a post-MVP concern.

Open dashboard:
- `http://127.0.0.1:8000/dashboard`

## Quick Demo Flow

1. Login with `ADMIN_TOKEN`.
2. Click `Predict` to generate idle probabilities.
3. Click `Allocate` to preview allocation results.
4. Click `Run Simulation` to compare baseline vs temporary overrides.
5. Click `Approve` to persist final allocation logs and request status.
6. Click `Refresh Metrics` to re-read metrics.

No manual SQL or DB edits are needed for demo flow.

## Allocation Fallback Behavior

Primary path:
- CP-SAT weighted optimization.

Automatic fallback path:
- If CP-SAT dependency is unavailable, solver fails, or returns infeasible/empty despite feasible pairs, a deterministic greedy allocator runs.
- Greedy order:
  - requests sorted by descending priority then request id,
  - choose highest-idle eligible room meeting capacity and threshold,
  - stable tie-breaking by capacity then room id.

## Model Versioning

Model training metadata is stored in `ModelRegistry`:
- `model_type`
- `model_version`
- `trained_at`

Retraining overwrites row `id=1` deterministically and does not affect existing prediction rows.

## Tests

```bash
pytest -q
```
