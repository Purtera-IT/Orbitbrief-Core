"""
HTTP worker for Orbitbrief-Core async runs (Phase 7).
POST /v1/compile-run — sync or async (?async=1) Core compile for a deal/run id.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from compile_run import compile_orbitbrief_run
from db import mark_run_done, mark_run_failed

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("orbitbrief-core-worker")

app = FastAPI(title="orbitbrief-core-worker", version="0.1.0")


class CompileRunBody(BaseModel):
    deal_id: str = Field(..., min_length=8)
    run_id: str = Field(..., min_length=8)
    mirror_latest: bool = True


def _check_bearer(authorization: str | None = Header(default=None)) -> None:
    expected = str(os.environ.get("ORBITBRIEF_CORE_WORKER_BEARER", "") or "").strip()
    if not expected:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization[7:].strip()
    if token != expected:
        raise HTTPException(status_code=401, detail="Invalid bearer token")


def _execute_compile(deal_id: str, run_id: str, mirror_latest: bool) -> dict[str, Any]:
    try:
        result = compile_orbitbrief_run(deal_id, run_id, mirror_latest=mirror_latest)
        mark_run_done(run_id, deal_id, result.get("pm_status"))
        return result
    except Exception as e:
        log.exception("compile failed deal=%s run=%s", deal_id, run_id)
        mark_run_failed(run_id, deal_id, str(e))
        raise


def _background_compile(deal_id: str, run_id: str, mirror_latest: bool) -> None:
    try:
        _execute_compile(deal_id, run_id, mirror_latest)
    except Exception:
        pass


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    return {"status": "ready"}


@app.post("/v1/compile-run")
def compile_run(
    body: CompileRunBody,
    background_tasks: BackgroundTasks,
    async_mode: int = Query(0, alias="async"),
    _: None = Depends(_check_bearer),
) -> dict[str, Any]:
    if async_mode:
        background_tasks.add_task(_background_compile, body.deal_id, body.run_id, body.mirror_latest)
        return {
            "ok": True,
            "accepted": True,
            "deal_id": body.deal_id,
            "run_id": body.run_id,
            "message": "Compile queued on worker",
        }
    return _execute_compile(body.deal_id, body.run_id, body.mirror_latest)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
