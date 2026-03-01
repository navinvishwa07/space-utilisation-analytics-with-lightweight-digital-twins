# Skills Demonstrated

## Backend Engineering
- REST API design with FastAPI (routers, lifespan, dependency injection via `app.state`)
- Four-layer architecture: controllers → services → repository → domain
- Input validation with Pydantic v2 (field validators, response models)
- Typed exception hierarchies with controller-level mapping to HTTP status codes
- ASGI application bootstrap with idempotent startup lifecycle

## Authentication and Security
- Ephemeral session token generation (`secrets.token_urlsafe(32)`)
- Session token distinct from admin secret — no password-as-token pattern
- Constant-time secret comparison (`secrets.compare_digest`) against timing attacks
- Protected vs public endpoint separation with FastAPI dependency injection

## Machine Learning
- Feature engineering with look-ahead leakage prevention:
  - `historical_occupancy_frequency` via cumulative mean with shift
  - `rolling_7d_occupancy_average` via `shift(1).rolling(7, min_periods=1)`
- One-hot encoding for categorical features (time_slot, room_type)
- LogisticRegression with DummyClassifier fallback for single-class edge case
- Confidence score derivation: `2 × |idle_probability − 0.5|`
- Model metadata registry with training_rows tracking

## Optimisation
- CP-SAT integer programming (OR-Tools) with six hard constraints
- Weighted objective function: `maximise Σ idle_probability × priority_weight`
- Jain's fairness index computed across stakeholder allocations
- Deterministic greedy fallback allocator (capacity, threshold, cap, tie-breaking)
- Three-trigger fallback orchestration: unavailability, infeasibility, zero-result

## Simulation and Digital Twin
- Fully isolated in-memory simulation with `copy.deepcopy()` dataset isolation
- `persist=False` propagated through all prediction calls during simulation
- Baseline vs constrained scenario comparison with delta computation
- Separate simulation solver seed for independence from allocation seed
- Four override types: idle_threshold, stakeholder_cap, capacity_override, priority_adjustment
- Tests verify zero DB mutation with row-count assertions

## Data Engineering
- Deterministic synthetic dataset generation (840 rows, seed=42)
- Idempotent CSV-based seeding with duplicate detection and dedup pass
- Unique index enforcement on (room_id, date, time_slot) composite key
- Rolling and cumulative aggregation with strict leakage guards
- SQLite migration guard pattern for schema evolution (ALTER TABLE with PRAGMA check)

## Software Engineering
- Frozen dataclasses for immutable domain models and runtime configuration
- Thread-safe service state with `RLock` for concurrent request handling
- `lru_cache` settings singleton for process-lifetime configuration
- `secrets.token_urlsafe` for cryptographically secure token generation
- Defensive programming: typed fallback paths, structured error handling

## Testing
- Integration test suite: 7 test modules, 30+ test cases
- Isolated test databases via `pytest tmp_path` (no shared state between tests)
- Row-count assertions verifying zero simulation side-effects
- Determinism assertions: two independent simulation runs must return identical results
- Edge case coverage: zero idle rooms, greedy fallback triggers, constraint violations,
  unauthenticated access, multi-room auto-prediction generation

## API and Documentation Engineering
- OpenAPI schema auto-generated via FastAPI with field-level validation
- Structured logging: `timestamp | level | module | message` format throughout all layers
- Environment validation script with 7 automated checks and summary table
- Shell-based demo script with jq-optional JSON parsing
- `.env.example` for reproducible environment setup
- Full API reference (`docs/API.md`) and demo guide (`docs/DEMO.md`)
