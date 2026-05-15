#!/usr/bin/env bash
# pm_handoff.sh — One-shot, never-skip-the-LLM PM hand-off compile.
#
# This is the script you point your PM at. It guarantees that the FULL
# pipeline runs (parser-os → OrbitBrief brains via Ollama → PM handoff
# bundle), and refuses to silently downgrade to substrate-only mode. If
# Ollama is unreachable or the requested model is missing, it errors out
# loudly instead of producing a half-empty dashboard.
#
# Usage:
#   ./pm_handoff.sh <case_dir> [<out_dir>]
#
# Examples:
#   ./pm_handoff.sh /Users/purtera/dev/purtera/parser-os-repo/real_data_cases/COPPER_001_SPRING_LAKE_AUDITORIUM
#   ./pm_handoff.sh ./my_case /tmp/my_case_artifacts
#
# Env overrides:
#   OLLAMA_BASE_URL    default: http://localhost:11434
#   CHAT_MODEL         default: qwen3:14b
#   ESCALATED_MODEL    default: qwen3:14b   (use qwen3:32b on a real GPU host)
#   PARSER_OS_ROOT     default: ../parser-os-repo  (sibling of Orbitbrief-Core)

set -euo pipefail

# ---- args -------------------------------------------------------------
if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 <case_dir> [<out_dir>]" >&2
  exit 64
fi

CASE_DIR="$1"
if [[ ! -d "$CASE_DIR" ]]; then
  echo "pm_handoff: case dir not found: $CASE_DIR" >&2
  exit 66
fi
CASE_NAME="$(basename "$CASE_DIR")"
OUT_DIR="${2:-/tmp/pm_handoff_${CASE_NAME}_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$OUT_DIR"

# ---- env defaults -----------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://localhost:11434}"
CHAT_MODEL="${CHAT_MODEL:-qwen3:14b}"
ESCALATED_MODEL="${ESCALATED_MODEL:-qwen3:14b}"
PARSER_OS_ROOT="${PARSER_OS_ROOT:-$(cd "$SCRIPT_DIR/../parser-os-repo" 2>/dev/null && pwd || true)}"

if [[ -z "${PARSER_OS_ROOT}" || ! -d "${PARSER_OS_ROOT}" ]]; then
  echo "pm_handoff: PARSER_OS_ROOT not found. Set PARSER_OS_ROOT=/abs/path/to/parser-os-repo" >&2
  exit 78
fi

echo "pm_handoff: case_dir       = $CASE_DIR"
echo "pm_handoff: out_dir        = $OUT_DIR"
echo "pm_handoff: parser_os_root = $PARSER_OS_ROOT"
echo "pm_handoff: ollama_url     = $OLLAMA_BASE_URL"
echo "pm_handoff: chat_model     = $CHAT_MODEL"
echo "pm_handoff: escalated      = $ESCALATED_MODEL"

# ---- preflight: Ollama reachable + model present ---------------------
echo "pm_handoff: preflight — checking Ollama at $OLLAMA_BASE_URL ..."
if ! TAGS=$(curl -fsS --max-time 5 "$OLLAMA_BASE_URL/api/tags" 2>/dev/null); then
  cat >&2 <<EOF
pm_handoff: ERROR — Ollama is not reachable at $OLLAMA_BASE_URL.

This script refuses to fall back to substrate-only mode because that
produces a half-empty PM dashboard ("(no brains ran for this engagement)").
Start Ollama and try again:

    brew services start ollama          # macOS
    ollama serve &                      # any host

Or override the URL:
    OLLAMA_BASE_URL=http://gpu-host:11434 $0 $CASE_DIR
EOF
  exit 69
fi

if ! echo "$TAGS" | grep -q "\"$CHAT_MODEL\""; then
  cat >&2 <<EOF
pm_handoff: ERROR — chat model '$CHAT_MODEL' is not pulled on $OLLAMA_BASE_URL.

Pull it first:
    ollama pull $CHAT_MODEL

Available right now:
$(echo "$TAGS" | python3 -c 'import json,sys;print("\n".join("  - "+m["name"] for m in json.load(sys.stdin).get("models",[])))' 2>/dev/null || echo "  (could not parse /api/tags)")
EOF
  exit 70
fi
echo "pm_handoff: preflight OK (Ollama up, '$CHAT_MODEL' present)."

# ---- run --------------------------------------------------------------
echo "pm_handoff: compiling — this typically takes 5–15 min on Mac (qwen3:14b)."
START_TS=$(date +%s)

PARSER_OS_ROOT="$PARSER_OS_ROOT" \
  PYTHONPATH="$SCRIPT_DIR/src" \
  python3 "$SCRIPT_DIR/compile_brief.py" \
    "$CASE_DIR" \
    --out "$OUT_DIR" \
    --ollama \
    --ollama-base-url "$OLLAMA_BASE_URL" \
    --chat-model "$CHAT_MODEL" \
    --escalated-model "$ESCALATED_MODEL" \
    --quiet-parser \
    --quiet

ELAPSED=$(( $(date +%s) - START_TS ))
echo "pm_handoff: compile finished in ${ELAPSED}s."

# ---- post-flight: verify the dashboard isn't empty -------------------
MANIFEST="$OUT_DIR/manifest.json"
if [[ ! -f "$MANIFEST" ]]; then
  echo "pm_handoff: ERROR — manifest.json missing under $OUT_DIR" >&2
  exit 65
fi

BRAINS_RUN=$(python3 -c "import json,sys; m=json.load(open(sys.argv[1])); print(','.join(m.get('brains_run') or []))" "$MANIFEST")
SKIPPED=$(python3 -c "import json,sys; m=json.load(open(sys.argv[1])); print('1' if m.get('skipped_brains_no_chat') else '0')" "$MANIFEST")

if [[ "$SKIPPED" == "1" || -z "$BRAINS_RUN" ]]; then
  cat >&2 <<EOF
pm_handoff: ERROR — pipeline produced an empty-brain bundle.

  brains_run             = '$BRAINS_RUN'
  skipped_brains_no_chat = $SKIPPED

This is exactly the case the PM dashboard would render as "(no brains
ran for this engagement)". Inspect $OUT_DIR/pipeline_log.json and
$OUT_DIR/manifest.json to see why brains were skipped or emitted nothing.
EOF
  exit 75
fi

echo "pm_handoff: brains_run = $BRAINS_RUN"
echo ""
echo "pm_handoff: PM dashboard ready:"
echo "  $OUT_DIR/91_inspection_report.html"
echo "  $OUT_DIR/PM_HANDOFF.html"
echo "  $OUT_DIR/PM_EXECUTIVE_SUMMARY.html"
echo "  $OUT_DIR/SA_REVIEW_PACKET.html"

# Best-effort open on macOS; harmless elsewhere.
if command -v open >/dev/null 2>&1; then
  open "$OUT_DIR/91_inspection_report.html" || true
fi
