#!/usr/bin/env bash
# Usage: bash scripts/demo.sh
# Requires: curl, jq (jq is optional — falls back to raw output if missing)
# The SIET server must be running: uvicorn main:app --reload

set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
ADMIN_TOKEN="${ADMIN_TOKEN:-admin-token}"

HAS_JQ=false
command -v jq &>/dev/null && HAS_JQ=true

json_get() {
  local json="$1" key="$2"
  if $HAS_JQ; then
    echo "$json" | jq -r "$key" 2>/dev/null || echo "(parse error)"
  else
    echo "$json" | grep -o "\"${key#.}\":[^,}]*" | head -1 | sed 's/.*: *"//' | sed 's/".*//' || echo "?"
  fi
}

echo ""
echo "============================================================"
echo "  SIET Space Utilization Digital Twin — Demo Flow"
echo "============================================================"
echo ""

# STEP 1 — Login
echo "[ 1/7 ] Login..."
LOGIN_RESP=$(curl -sf -X POST "$BASE_URL/login" \
  -H "Content-Type: application/json" \
  -d "{\"admin_token\": \"$ADMIN_TOKEN\"}")
TOKEN=$(json_get "$LOGIN_RESP" ".access_token")
echo "        Token: ${TOKEN:0:8}..."

AUTH_HEADER="Authorization: Bearer $TOKEN"

# STEP 2 — Demo context
echo "[ 2/7 ] Loading demo context..."
CTX=$(curl -sf "$BASE_URL/demo_context" -H "$AUTH_HEADER")
DATE=$(json_get "$CTX" ".default_date")
SLOT=$(json_get "$CTX" ".default_time_slot")
COUNT=$(json_get "$CTX" ".pending_request_count")
echo "        Date=$DATE  Slot=$SLOT  Pending requests=$COUNT"

# STEP 3 — Predict
echo "[ 3/7 ] Running predictions for $DATE $SLOT..."
PRED=$(curl -sf -X POST "$BASE_URL/predict" \
  -H "Content-Type: application/json" \
  -H "$AUTH_HEADER" \
  -d "{\"date\": \"$DATE\", \"time_slot\": \"$SLOT\"}")
N_PRED=$(json_get "$PRED" ".predictions | length")
echo "        Predictions returned: $N_PRED rooms"

# STEP 4 — Allocate
echo "[ 4/7 ] Running allocation for $DATE $SLOT..."
ALLOC=$(curl -sf -X POST "$BASE_URL/allocate" \
  -H "Content-Type: application/json" \
  -H "$AUTH_HEADER" \
  -d "{\"requested_date\": \"$DATE\", \"requested_time_slot\": \"$SLOT\", \"idle_probability_threshold\": 0.25, \"stakeholder_usage_cap\": 0.60}")
OBJ=$(json_get "$ALLOC" ".objective_value")
FAIR=$(json_get "$ALLOC" ".fairness_metric")
echo "        Objective value=$OBJ  Fairness (Jain's)=$FAIR"

# STEP 5 — Simulate
echo "[ 5/7 ] Running what-if simulation..."
SIM=$(curl -sf -X POST "$BASE_URL/simulate" \
  -H "Content-Type: application/json" \
  -H "$AUTH_HEADER" \
  -d '{"stakeholder_priority_weight": 1.20, "idle_probability_threshold": 0.30}')
UTIL_DELTA=$(json_get "$SIM" ".delta.utilization_change")
REQ_DELTA=$(json_get "$SIM" ".delta.request_change")
echo "        Utilization delta=$UTIL_DELTA  Request change=$REQ_DELTA"

# STEP 6 — Metrics
echo "[ 6/7 ] Reading metrics..."
METRICS=$(curl -sf "$BASE_URL/metrics" -H "$AUTH_HEADER")
BASE_RATE=$(json_get "$METRICS" ".baseline_idle_activation_rate")
SIM_RATE=$(json_get "$METRICS" ".simulated_idle_activation_rate")
EFF=$(json_get "$METRICS" ".allocation_efficiency_score")
DELTA_PCT=$(json_get "$METRICS" ".utilization_delta_percentage")
echo "        Baseline=$BASE_RATE  Simulated=$SIM_RATE  Efficiency=$EFF  Delta%=$DELTA_PCT"

# STEP 7 — Approve
echo "[ 7/7 ] Approving allocation..."
APPROVE=$(curl -sf -X POST "$BASE_URL/approve" \
  -H "Content-Type: application/json" \
  -H "$AUTH_HEADER")
APPROVED_COUNT=$(json_get "$APPROVE" ".approved_allocations_count")
echo "        Approved allocations: $APPROVED_COUNT"

echo ""
echo "============================================================"
echo "  Demo complete. All 7 steps passed."
echo "============================================================"
echo ""
