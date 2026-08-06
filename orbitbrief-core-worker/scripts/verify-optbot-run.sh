#!/usr/bin/env bash
# Enqueue an OPTBOT OrbitBrief run and poll until done/failed (dev).
set -euo pipefail

DEAL_ID="${DEAL_ID:-841ea7e0-0e2f-412a-aebc-5794c199b85c}"
FUNCTION_APP="${FUNCTION_APP:-purpulse-dev-api-eus2}"
RESOURCE_GROUP="${RESOURCE_GROUP:-purtera-dev-rg}"
POLL_SEC="${POLL_SEC:-60}"
MAX_POLLS="${MAX_POLLS:-25}"

DB_URL="$(az functionapp config appsettings list -g "$RESOURCE_GROUP" -n "$FUNCTION_APP" \
  --query "[?name=='DATABASE_URL'].value | [0]" -o tsv)"
if [[ -z "$DB_URL" || "$DB_URL" == "null" ]]; then
  echo "error: DATABASE_URL not on $FUNCTION_APP" >&2
  exit 1
fi

if ! command -v psql >/dev/null 2>&1; then
  echo "error: psql required" >&2
  exit 1
fi

echo "==> Insert queued run for deal $DEAL_ID"
RUN_ID="$(psql "$DB_URL" -t -A -c \
  "INSERT INTO public.orbitbrief_runs (deal_id, status) VALUES ('${DEAL_ID}'::uuid, 'queued') RETURNING id;" \
  | grep -oE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' | head -1)"
if [[ -z "$RUN_ID" ]]; then
  echo "error: could not parse run id from insert" >&2
  exit 1
fi
echo "run_id=$RUN_ID"

echo "==> Trigger orbitbrief-runs-timer"
MASTER_KEY="$(az functionapp keys list -g "$RESOURCE_GROUP" -n "$FUNCTION_APP" --query masterKey -o tsv)"
curl -sS -m 120 -X POST \
  "https://${FUNCTION_APP}.azurewebsites.net/admin/functions/orbitbrief-runs-timer" \
  -H "x-functions-key: ${MASTER_KEY}" \
  -H "Content-Type: application/json" \
  -d '{}' \
  -o /tmp/ob-timer-invoke.json -w "timer_http=%{http_code}\n" || true

sleep 5
echo "==> Poll run status (every ${POLL_SEC}s, max ${MAX_POLLS})"
for i in $(seq 1 "$MAX_POLLS"); do
  ROW="$(psql "$DB_URL" -t -A -F '|' -c \
    "SELECT status, COALESCE(pm_status,''), COALESCE(LEFT(error_message,120),'')
     FROM public.orbitbrief_runs WHERE id='${RUN_ID}'::uuid LIMIT 1;")"
  STATUS="$(echo "$ROW" | cut -d'|' -f1)"
  PM_STATUS="$(echo "$ROW" | cut -d'|' -f2)"
  ERR="$(echo "$ROW" | cut -d'|' -f3)"
  echo "[${i}/${MAX_POLLS}] status=${STATUS} pm_status=${PM_STATUS} err=${ERR}"
  if [[ "$STATUS" == "done" || "$STATUS" == "failed" ]]; then
    break
  fi
  sleep "$POLL_SEC"
done

echo "==> Handoff compile_id (if done)"
psql "$DB_URL" -t -A -c \
  "SELECT status, pm_status, LEFT(error_message,200) FROM public.orbitbrief_runs WHERE id='${RUN_ID}'::uuid;"

if command -v az >/dev/null 2>&1; then
  az storage blob download --account-name purpulsedevstg01 --container-name orbitbrief-artifacts \
    --name "deals/${DEAL_ID}/orbitbrief/${RUN_ID}/PM_HANDOFF.json" \
    --file /tmp/ob-handoff.json --auth-mode login --overwrite 2>/dev/null || true
  if [[ -f /tmp/ob-handoff.json ]]; then
    python3 - <<'PY'
import json
p="/tmp/ob-handoff.json"
with open(p) as f:
    d=json.load(f)
print("case_id:", d.get("case_id"))
print("compile_id:", d.get("compile_id"))
print("status:", d.get("status"))
PY
  fi
fi
