#!/usr/bin/env bash
# Wire secrets/env on orbitbrief-core-worker + Function App worker mode (dev).
set -euo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-purtera-dev-rg}"
APP_NAME="${APP_NAME:-orbitbrief-core-worker-dev-eus2}"
FUNCTION_APP="${FUNCTION_APP:-purpulse-dev-api-eus2}"
STORAGE_ACCOUNT="${STORAGE_ACCOUNT:-purpulsedevstg01}"
ACR_NAME="${ACR_NAME:-purpulsedevacr}"

OLLAMA_PROXY_URL="${OLLAMA_PROXY_URL:-https://ollama-mac-proxy-dev-eus2.whitehill-a3348ba5.eastus2.azurecontainerapps.io}"

if ! az containerapp show -g "$RESOURCE_GROUP" -n "$APP_NAME" >/dev/null 2>&1; then
  echo "error: Container App $APP_NAME not found — run deploy-dev.sh first" >&2
  exit 1
fi

DATABASE_URL="$(az functionapp config appsettings list -g "$RESOURCE_GROUP" -n "$FUNCTION_APP" \
  --query "[?name=='DATABASE_URL'].value | [0]" -o tsv)"
if [[ -z "$DATABASE_URL" || "$DATABASE_URL" == "null" ]]; then
  echo "error: DATABASE_URL missing on $FUNCTION_APP" >&2
  exit 1
fi

OB_CONN="$(az storage account show-connection-string -g "$RESOURCE_GROUP" -n "$STORAGE_ACCOUNT" \
  --query connectionString -o tsv)"
if [[ -z "$OB_CONN" ]]; then
  echo "error: could not read storage connection string for $STORAGE_ACCOUNT" >&2
  exit 1
fi

if [[ -z "${ORBITBRIEF_CORE_WORKER_BEARER:-}" ]]; then
  ORBITBRIEF_CORE_WORKER_BEARER="$(openssl rand -hex 24)"
  echo "Generated ORBITBRIEF_CORE_WORKER_BEARER (saved to Function App + Container App)"
fi

ACR_ID="$(az acr show -g "$RESOURCE_GROUP" -n "$ACR_NAME" --query id -o tsv)"
PID="$(az containerapp show -g "$RESOURCE_GROUP" -n "$APP_NAME" --query identity.principalId -o tsv)"
if [[ -n "$PID" && "$PID" != "null" ]]; then
  if ! az role assignment list --assignee "$PID" --scope "$ACR_ID" --role "AcrPull" --query "[0].id" -o tsv 2>/dev/null | grep -q .; then
    echo "==> AcrPull for $APP_NAME"
    az role assignment create --assignee "$PID" --role AcrPull --scope "$ACR_ID" >/dev/null
  fi
  az containerapp registry set -g "$RESOURCE_GROUP" -n "$APP_NAME" \
    --server "${ACR_NAME}.azurecr.io" \
    --identity system >/dev/null
fi

echo "==> Container App secrets + env"
az containerapp secret set -g "$RESOURCE_GROUP" -n "$APP_NAME" \
  --secrets \
    "database-url=${DATABASE_URL}" \
    "orbitbrief-artifacts-conn=${OB_CONN}" \
    "worker-bearer=${ORBITBRIEF_CORE_WORKER_BEARER}" \
  >/dev/null

az containerapp update -g "$RESOURCE_GROUP" -n "$APP_NAME" \
  --revision-suffix "$(date +%m%d%H%M)" \
  --set-env-vars \
    "DATABASE_URL=secretref:database-url" \
    "ORBITBRIEF_ARTIFACTS_CONNECTION_STRING=secretref:orbitbrief-artifacts-conn" \
    "ORBITBRIEF_CORE_WORKER_BEARER=secretref:worker-bearer" \
    "OLLAMA_BASE_URL=${OLLAMA_PROXY_URL}" \
    "ORBITBRIEF_ARTIFACTS_CONTAINER=orbitbrief-artifacts" \
    "COMPILE_TIMEOUT_SEC=840" \
  >/dev/null

WORKER_FQDN="$(az containerapp show -g "$RESOURCE_GROUP" -n "$APP_NAME" \
  --query "properties.configuration.ingress.fqdn" -o tsv)"
WORKER_URL="https://${WORKER_FQDN}"

echo "==> Function App $FUNCTION_APP settings"
MAX_CONCURRENT="${ORBITBRIEF_CORE_MAX_CONCURRENT:-2}"
STUCK_MINUTES="${ORBITBRIEF_CORE_STUCK_RUNNING_MINUTES:-20}"
APPINSIGHTS_CONN="$(az functionapp config appsettings list -g "$RESOURCE_GROUP" -n "$FUNCTION_APP" \
  --query "[?name=='APPLICATIONINSIGHTS_CONNECTION_STRING'].value | [0]" -o tsv 2>/dev/null || true)"

az functionapp config appsettings set -g "$RESOURCE_GROUP" -n "$FUNCTION_APP" \
  --settings \
    "ORBITBRIEF_CORE_RUN_MODE=worker" \
    "ORBITBRIEF_CORE_WORKER_URL=${WORKER_URL}" \
    "ORBITBRIEF_CORE_WORKER_BEARER=${ORBITBRIEF_CORE_WORKER_BEARER}" \
    "ORBITBRIEF_CORE_RUN_ASYNC=true" \
    "ORBITBRIEF_CORE_MAX_CONCURRENT=${MAX_CONCURRENT}" \
    "ORBITBRIEF_CORE_STUCK_RUNNING_MINUTES=${STUCK_MINUTES}" \
    "ORBITBRIEF_ARTIFACTS_CONNECTION_STRING=${OB_CONN}" \
    "ORBITBRIEF_ARTIFACTS_CONTAINER=orbitbrief-artifacts" \
    "AzureWebJobs.orbitbrief-runs-timer.Disabled=false" \
  >/dev/null

az containerapp update -g "$RESOURCE_GROUP" -n "$APP_NAME" \
  --min-replicas 1 --max-replicas "${MAX_CONCURRENT}" \
  --set-env-vars \
    "ORBITBRIEF_CORE_MAX_CONCURRENT=${MAX_CONCURRENT}" \
  >/dev/null 2>&1 || true

if [[ -n "$APPINSIGHTS_CONN" && "$APPINSIGHTS_CONN" != "null" ]]; then
  az containerapp secret set -g "$RESOURCE_GROUP" -n "$APP_NAME" \
    --secrets "appinsights-conn=${APPINSIGHTS_CONN}" >/dev/null 2>&1 || true
  az containerapp update -g "$RESOURCE_GROUP" -n "$APP_NAME" \
    --set-env-vars "APPLICATIONINSIGHTS_CONNECTION_STRING=secretref:appinsights-conn" \
    >/dev/null 2>&1 || true
fi

echo ""
echo "Worker URL: ${WORKER_URL}"
echo "Health:     ${WORKER_URL}/healthz"
echo "Function:   ORBITBRIEF_CORE_RUN_MODE=worker, timer enabled"
echo ""
echo "Verify compile:"
echo "  curl -sS ${WORKER_URL}/healthz"
echo "  # POST orbitbrief run on OPTBOT deal, poll GET .../runs/{id}"
