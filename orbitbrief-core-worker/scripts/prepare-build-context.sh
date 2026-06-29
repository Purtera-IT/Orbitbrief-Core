#!/usr/bin/env bash
# Stage parser-os + Orbitbrief-Core + worker into a temp dir for `az acr build`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${1:-/tmp/ob-core-worker-build}"

PARSER_OS="${PARSER_OS_ROOT:-$(dirname "$ROOT")/parser-os}"
CORE="${ORBITBRIEF_CORE_ROOT:-$(dirname "$ROOT")/Orbitbrief-Core}"

for d in "$PARSER_OS" "$CORE"; do
  if [ ! -d "$d" ]; then
    echo "error: missing checkout: $d" >&2
    exit 1
  fi
done

rm -rf "$OUT"
mkdir -p "$OUT"
cp -R "$PARSER_OS" "$OUT/parser-os"
cp -R "$CORE" "$OUT/Orbitbrief-Core"
cp -R "$ROOT/orbitbrief-core-worker" "$OUT/orbitbrief-core-worker"
cp "$ROOT/orbitbrief-core-worker/Dockerfile" "$OUT/Dockerfile"

echo "Build context ready: $OUT"
echo "  az acr build -g purtera-dev-rg -r purpulsedevacr -t orbitbrief-core-worker:v1 $OUT"
