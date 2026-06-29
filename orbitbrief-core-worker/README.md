# Orbitbrief Core worker (Phase 7)

HTTP worker that runs **Orbitbrief-Core** `compile_brief.py` for queued `orbitbrief_runs` rows:

1. Download `deals/{dealId}/orbitbrief/latest/envelope.json`
2. Compile via **Ollama** (`OLLAMA_BASE_URL` → `ollama-mac-proxy-dev-eus2` → Mac Studio)
3. Upload artifacts to `deals/{dealId}/orbitbrief/{runId}/` and mirror to `latest/`
4. Update Postgres `orbitbrief_runs` → `done` or `failed`

PM users **do not** need Tailscale; only this container reaches the Mac Studio proxy.

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/healthz` | Liveness |
| GET | `/readyz` | Readiness |
| POST | `/v1/compile-run?async=1` | Accept compile (returns immediately; updates PG when finished) |
| POST | `/v1/compile-run` | Synchronous compile (15 min max; use from manual curl, not Function timer) |

Body:

```json
{ "deal_id": "<uuid>", "run_id": "<uuid>", "mirror_latest": true }
```

Optional header: `Authorization: Bearer <ORBITBRIEF_CORE_WORKER_BEARER>`

## Build & deploy (dev)

```bash
export PARSER_OS_ROOT=/path/to/parser-os
export ORBITBRIEF_CORE_ROOT=/path/to/Orbitbrief-Core

bash Platform-infra/orbitbrief-core-worker/scripts/deploy-dev.sh
```

Configure Container App secrets/env, then on **`purpulse-dev-api-eus2`**:

| Setting | Example |
|---------|---------|
| `ORBITBRIEF_CORE_RUN_MODE` | `worker` |
| `ORBITBRIEF_CORE_WORKER_URL` | `https://orbitbrief-core-worker-dev-eus2....azurecontainerapps.io` |
| `ORBITBRIEF_CORE_WORKER_BEARER` | shared secret |
| `ORBITBRIEF_CORE_WORK_ASYNC` | `true` (default — timer dispatches without waiting) |

`orbitbrief-runs-timer` claims `queued` rows and POSTs `?async=1` to this worker.

## Local run

```bash
cd orbitbrief-core-worker
pip install -r requirements.txt
export ORBITBRIEF_ARTIFACTS_CONNECTION_STRING='...'
export DATABASE_URL='...'
export OLLAMA_BASE_URL='http://griffins-mac-studio:11434'  # on tailnet
export ORBITBRIEF_CORE_ROOT=../Orbitbrief-Core
export PARSER_OS_ROOT=../parser-os
python -m uvicorn app:app --reload --port 8095
```

## Stub mode

Leave `ORBITBRIEF_CORE_RUN_MODE` unset or `stub` on the Function App to keep copy-from-`latest/` behavior (Phase 7 stub).
