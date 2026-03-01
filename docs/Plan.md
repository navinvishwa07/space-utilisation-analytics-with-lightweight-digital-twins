# Hackathon Execution Plan

Day 1
- Finalize schema (Rooms, BookingHistory, Requests, Predictions, AllocationLogs,
  DemandForecastLogs, ModelRegistry)
- Setup layered project structure: controllers / services / repository / domain / utils
- Implement FastAPI skeleton with lifespan startup and dependency injection
- Generate deterministic synthetic dataset (10 rooms × 21 days × 4 slots, seed=42)
- Seed room catalog and BookingHistory idempotently from CSV

Day 2
- Implement availability prediction service (LogisticRegression + DummyClassifier fallback)
- Feature engineering with look-ahead leakage prevention:
    day_of_week, time_slot (OHE), room_type (OHE),
    historical_occupancy_frequency (cumulative-mean shift),
    rolling_7d_occupancy_average (shift+rolling)
- /predict_availability and /predict endpoints with bearer auth
- Persist predictions and model metadata (ModelRegistry)

Day 3
- Implement demand forecasting (historical slot aggregation → intensity score)
- Persist to DemandForecastLogs
- Integrate OR-Tools CP-SAT allocation optimizer
- Implement all six constraints: capacity, no-overlap, idle threshold,
  stakeholder cap, one-allocation-per-request, fairness-weighted objective
- Implement Jain's fairness metric
- Implement deterministic greedy fallback allocator (triggered on CP-SAT unavailability,
  infeasibility, or zero-allocation with feasible pairs)
- /optimize_allocation and /allocate endpoints

Day 4
- Implement SimulationService: fully isolated, in-memory, copy.deepcopy, persist=False
- Baseline vs constrained comparison with delta computation
- Separate simulation_solver_random_seed for determinism independence
- /simulate endpoint with all four override types:
  idle_threshold, stakeholder_cap, capacity_override, priority_adjustment

Day 5
- Build HTML/JS Admin Dashboard (dashboard/index.html) served by FastAPI at /dashboard
- Two-screen UX: login screen → dashboard revealed post-authentication
- Full operator flow: Login → Predict → Allocate → Simulate → Approve
- Metrics panel (before vs after), idle probability table, allocation results table
- Bearer session token authentication (session token ≠ admin secret)

Day 6
- Align all documentation (PRD, MVP, Architecture, AI_Rules, README, Plan)
- Curated requirements.txt (minimal, no unused packages)
- python-dotenv support with .env.example
- Integration and unit test suite:
    test_prediction, test_matching, test_simulation,
    test_dashboard_flow, test_repository_seeding,
    test_allocation_fallback, test_constraints

Day 7
- Structured logging throughout all layers with request tracing
- Edge-case testing: zero idle rooms, fallback triggers, constraint violations,
  empty requests, idempotency
- Environment validation script (scripts/validate_environment.py)
- Demo shell script (scripts/demo.sh)
- Final documentation audit and alignment pass
