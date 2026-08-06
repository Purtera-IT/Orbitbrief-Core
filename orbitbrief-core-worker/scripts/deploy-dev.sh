#!/usr/bin/env bash
# Build orbitbrief-core-worker image and deploy dev Container App (single-replica HTTP worker).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKER_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PLATFORM_ROOT="$(cd "$WORKER_ROOT/.." && pwd)"

ACR_NAME="purpulsedevacr"
ACR_RG="purtera-dev-rg"
IMAGE_NAME="orbitbrief-core-worker"
IMAGE_TAG="${IMAGE_TAG:-v1}"
APP_NAME="orbitbrief-core-worker-dev-eus2"
ENV_NAME="${CONTAINERAPPS_ENV:-parser-dev-env-eus2}"
RESOURCE_GROUP="${RESOURCE_GROUP:-purtera-dev-rg}"

BUILD_CTX="$(mktemp -d /tmp/ob-core-worker-ctx.XXXXXX)"
trap 'rm -rf "$BUILD_CTX"' EXIT

bash "$SCRIPT_DIR/prepare-build-context.sh" "$BUILD_CTX"

if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  echo "==> ACR build ${ACR_NAME}.azurecr.io/${IMAGE_NAME}:${IMAGE_TAG}"
  az acr build -g "$ACR_RG" -r "$ACR_NAME" --image "${IMAGE_NAME}:${IMAGE_TAG}" "$BUILD_CTX"
fi

FULL_IMAGE="${ACR_NAME}.azurecr.io/${IMAGE_NAME}:${IMAGE_TAG}"
ACR_ID="$(az acr show -g "$ACR_RG" -n "$ACR_NAME" --query id -o tsv)"

ensure_acrpull() {
  local pid
  pid="$(az containerapp show -g "$RESOURCE_GROUP" -n "$APP_NAME" --query identity.principalId -o tsv)"
  if [[ -z "$pid" || "$pid" == "null" ]]; then
    echo "error: no system-assigned identity on $APP_NAME" >&2
    exit 1
  fi
  if ! az role assignment list --assignee "$pid" --scope "$ACR_ID" --role "AcrPull" --query "[0].id" -o tsv 2>/dev/null | grep -q .; then
    echo "==> AcrPull for $APP_NAME"
    az role assignment create --assignee "$pid" --role AcrPull --scope "$ACR_ID" >/dev/null
  fi
  az containerapp registry set -g "$RESOURCE_GROUP" -n "$APP_NAME" \
    --server "${ACR_NAME}.azurecr.io" \
    --identity system >/dev/null
}

if az containerapp show -g "$RESOURCE_GROUP" -n "$APP_NAME" >/dev/null 2>&1; then
  echo "==> Update $APP_NAME"
  ensure_acrpull
  az containerapp update -g "$RESOURCE_GROUP" -n "$APP_NAME" \
    --image "$FULL_IMAGE" \
    --revision-suffix "$(date +%m%d%H%M)" \
    --min-replicas 1 --max-replicas 2 \
    --cpu 2 --memory 4Gi
else
  echo "==> Create $APP_NAME (bootstrap image, then switch to ACR)"
  az containerapp create -g "$RESOURCE_GROUP" -n "$APP_NAME" \
    --environment "$ENV_NAME" \
    --image "mcr.microsoft.com/k8se/quickstart:latest" \
    --target-port 8080 --ingress external \
    --min-replicas 1 --max-replicas 2 \
    --cpu 2 --memory 4Gi \
    --system-assigned
  ensure_acrpull
  az containerapp update -g "$RESOURCE_GROUP" -n "$APP_NAME" \
    --image "$FULL_IMAGE" \
    --revision-suffix "$(date +%m%d%H%M)" \
    --min-replicas 1 --max-replicas 2 \
    --cpu 2 --memory 4Gi
fi

az containerapp ingress enable -g "$RESOURCE_GROUP" -n "$APP_NAME" \
  --type external --target-port 8080 --transport auto >/dev/null 2>&1 || true

if [[ "${SKIP_CONFIGURE:-0}" != "1" ]]; then
  bash "$SCRIPT_DIR/configure-dev.sh"
else
  echo "SKIP_CONFIGURE=1 — run: bash $SCRIPT_DIR/configure-dev.sh"
fi
