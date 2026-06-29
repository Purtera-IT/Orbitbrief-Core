#!/usr/bin/env bash
# Lovable-parity smoke: POST + poll GET orbitbrief runs on Azure proxy (OPTBOT deal).
set -euo pipefail

DEAL_ID="${DEAL_ID:-841ea7e0-0e2f-412a-aebc-5794c199b85c}"
FUNCTION_APP="${FUNCTION_APP:-purpulse-dev-api-eus2}"
RESOURCE_GROUP="${RESOURCE_GROUP:-purtera-dev-rg}"
POLL_SEC="${POLL_SEC:-15}"
MAX_POLLS="${MAX_POLLS:-80}"

API_BASE="https://${FUNCTION_APP}.azurewebsites.net/api/proxy"
RUNS_PATH="${API_BASE}/api/quoting/deal/${DEAL_ID}/orbitbrief/runs"

if [[ -z "${BEARER_TOKEN:-}" ]]; then
  CLIENT_ID="$(az functionapp config appsettings list -g "$RESOURCE_GROUP" -n "$FUNCTION_APP" \
    --query "[?name=='AZURE_AD_CLIENT_ID'].value | [0]" -o tsv 2>/dev/null || true)"
  if [[ -n "$CLIENT_ID" && "$CLIENT_ID" != "null" ]]; then
    echo "==> Acquiring Entra token (resource api://${CLIENT_ID}) — sign in if prompted"
    BEARER_TOKEN="$(az account get-access-token --resource "api://${CLIENT_ID}" --query accessToken -o tsv 2>/dev/null || true)"
  fi
fi

if [[ -z "${BEARER_TOKEN:-}" ]]; then
  echo "error: set BEARER_TOKEN (copy from Lovable DevTools → Network → Authorization header)" >&2
  exit 1
fi

echo "==> POST ${RUNS_PATH}"
POST_BODY="$(curl -sS -m 60 -X POST "$RUNS_PATH" \
  -H "Authorization: Bearer ${BEARER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{}')"
echo "$POST_BODY" | python3 -m json.tool 2>/dev/null || echo "$POST_BODY"

RUN_ID="$(echo "$POST_BODY" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('runId',''))" 2>/dev/null || true)"
if [[ -z "$RUN_ID" ]]; then
  echo "error: POST did not return runId (401/403? check BEARER_TOKEN and pm.orbitbrief.run capability)" >&2
  exit 1
fi

echo "run_id=$RUN_ID"
DETAIL_URL="${RUNS_PATH}/${RUN_ID}"

echo "==> Poll GET ${DETAIL_URL} (every ${POLL_SEC}s)"
for i in $(seq 1 "$MAX_POLLS"); do
  DETAIL="$(curl -sS -m 60 -X GET "$DETAIL_URL" -H "Authorization: Bearer ${BEARER_TOKEN}")"
  STATUS="$(echo "$DETAIL" | python3 -c "import json,sys; d=json.load(sys.stdin); print((d.get('run') or {}).get('status',''))" 2>/dev/null || echo "?")"
  PM_STATUS="$(echo "$DETAIL" | python3 -c "import json,sys; d=json.load(sys.stdin); print((d.get('run') or {}).get('pmStatus',''))" 2>/dev/null || echo "")"
  CASE_ID="$(echo "$DETAIL" | python3 -c "
import json,sys
d=json.load(sys.stdin)
data=d.get('data') or {}
print(data.get('case_id',''))
" 2>/dev/null || echo "")"
  echo "[${i}/${MAX_POLLS}] status=${STATUS} pm_status=${PM_STATUS} case_id=${CASE_ID:0:36}"
  if [[ "$STATUS" == "done" || "$STATUS" == "failed" ]]; then
    if [[ "$STATUS" == "done" && "$CASE_ID" == stub_* ]]; then
      echo "FAIL: handoff still stub case_id=$CASE_ID" >&2
      exit 1
    fi
    if [[ "$STATUS" == "done" && -n "$CASE_ID" && "$CASE_ID" != stub_* ]]; then
      echo "PASS: real Core handoff (case_id=$CASE_ID)"
      exit 0
    fi
    echo "FAIL: run ended with status=$STATUS" >&2
    echo "$DETAIL" | python3 -m json.tool 2>/dev/null | head -40
    exit 1
  fi
  sleep "$POLL_SEC"
done

echo "FAIL: timed out waiting for terminal status" >&2
exit 1
