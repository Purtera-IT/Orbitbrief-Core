#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MANIFEST="$ROOT/holdout_download_manifest.csv"
TAIL_START=2
mkdir -p "$ROOT/pdfs/holdout_public"
while IFS=, read -r label packet_id category title url target; do
  [ "$label" = "label" ] && continue
  mkdir -p "$(dirname "$ROOT/$target")"
  echo "Downloading $packet_id -> $target"
  curl -L --fail --retry 2 --max-time 120 -A 'Mozilla/5.0' -o "$ROOT/$target" "$url"
done < "$MANIFEST"
