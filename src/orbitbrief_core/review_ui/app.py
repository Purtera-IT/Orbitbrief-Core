"""FastAPI app + routes for the reviewer UI.

Server-rendered (Jinja2 templates). HTMX powers the decision form
so a reviewer can accept/reject an item without a full page
reload — the queue list updates in place.

Routes:

* ``GET  /``                       — redirect to ``/queue``.
* ``GET  /queue``                  — open review items, filterable by brain.
* ``GET  /item/{composite_id:path}`` — full payload + decision form.
* ``POST /item/{composite_id:path}/decide`` — record a decision; HTMX
  swaps the queue row with a confirmation pill.
* ``GET  /composed``               — rendered :class:`ComposedBrief` (HTML).
* ``GET  /api/queue``              — JSON view (handy for scripting).
* ``GET  /api/training_log``       — JSONL passthrough.
* ``GET  /healthz``                — process health.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

# We import FastAPI / Jinja2 lazily so the rest of the package still
# works without the optional ``[ui]`` dependency installed.
try:
    from fastapi import FastAPI, Form, HTTPException, Query, Request
    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
    from fastapi.templating import Jinja2Templates
except ImportError as exc:  # pragma: no cover - environmental
    raise ImportError(
        "Phase-8 review UI needs FastAPI + Jinja2. "
        "Install with: pip install -e '.[ui]'"
    ) from exc

from orbitbrief_core.calibrator.verdict import Verdict
from orbitbrief_core.composer.markdown import render_markdown
from orbitbrief_core.review_runtime import (
    DecisionAction,
    ReviewDecision,
    record_decision,
)
from orbitbrief_core.review_ui.context import ReviewContext


_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def build_app(context: ReviewContext) -> FastAPI:
    """Construct a FastAPI app over the given :class:`ReviewContext`."""
    templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))
    app = FastAPI(title="OrbitBrief Reviewer", version="0.1.0")

    # ───── pages ─────

    @app.get("/", include_in_schema=False)
    def _root() -> RedirectResponse:
        return RedirectResponse(url="/queue")

    @app.get("/queue", response_class=HTMLResponse)
    def _queue(
        request: Request,
        brain: str | None = Query(default=None),
        limit: int = Query(default=200, ge=1, le=2000),
    ) -> HTMLResponse:
        items = list(context.queue.list_open(limit=limit))
        if brain:
            items = [it for it in items if it.ref.brain == brain]
        brains = sorted({it.ref.brain for it in context.queue.list_open()})
        return templates.TemplateResponse(
            request,
            "queue.html",
            {
                "items": items,
                "brains": brains,
                "active_brain": brain,
                "manifest": context.manifest(),
            },
        )

    @app.get("/item/{composite_id:path}", response_class=HTMLResponse)
    def _item(request: Request, composite_id: str) -> HTMLResponse:
        item = context.queue.get(composite_id)
        if item is None:
            raise HTTPException(status_code=404, detail=f"unknown item: {composite_id}")
        decisions = context.queue.decisions_for(composite_id)
        return templates.TemplateResponse(
            request,
            "item.html",
            {
                "item": item,
                "decisions": decisions,
                "verdicts_for_action": [v.value for v in DecisionAction],
            },
        )

    @app.post("/item/{composite_id:path}/decide", response_class=HTMLResponse)
    def _decide(
        request: Request,
        composite_id: str,
        action: str = Form(...),
        decided_by: str = Form(default="reviewer@orbitbrief"),
        notes: str = Form(default=""),
        edited_payload_json: str = Form(default=""),
    ) -> HTMLResponse:
        try:
            action_enum = DecisionAction(action)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"bad action {action!r}")

        item = context.queue.get(composite_id)
        if item is None:
            raise HTTPException(status_code=404, detail=f"unknown item: {composite_id}")

        edited_payload: dict[str, Any] | None = None
        if edited_payload_json.strip():
            try:
                import json

                edited_payload = json.loads(edited_payload_json)
                if not isinstance(edited_payload, dict):
                    raise ValueError("edited_payload must be a JSON object")
            except (ValueError, json.JSONDecodeError) as exc:
                raise HTTPException(status_code=400, detail=f"bad JSON: {exc}")

        decision = ReviewDecision(
            composite_id=composite_id,
            action=action_enum,
            decided_by=decided_by or "reviewer@orbitbrief",
            notes=notes,
            edited_payload=edited_payload,
        )
        decided = context.queue.record_decision(decision)
        record_decision(item=item, decision=decision, log=context.training_log)
        return templates.TemplateResponse(
            request,
            "_decision_pill.html",
            {"item": decided, "decision": decision},
        )

    @app.get("/composed", response_class=HTMLResponse)
    def _composed(request: Request) -> HTMLResponse:
        brief = context.composed_brief()
        md = context.composed_brief_markdown()
        return templates.TemplateResponse(
            request,
            "composed.html",
            {"brief": brief, "markdown": md},
        )

    @app.get("/inspection", response_class=HTMLResponse)
    def _inspection() -> HTMLResponse:
        body = context.inspection_html()
        if body is None:
            return HTMLResponse(
                "<h1>No inspection report</h1><p>Run the orchestrator on this artifacts directory to generate <code>91_inspection_report.html</code>.</p>",
                status_code=404,
            )
        return HTMLResponse(body)

    @app.get("/api/inspection")
    def _api_inspection() -> JSONResponse:
        report = context.inspection_json()
        if report is None:
            raise HTTPException(status_code=404, detail="no inspection report")
        return JSONResponse(report)

    # ───── JSON API surface ─────

    @app.get("/api/queue")
    def _api_queue() -> JSONResponse:
        return JSONResponse(
            [it.model_dump(mode="json") for it in context.queue.list_open()]
        )

    @app.get("/api/training_log")
    def _api_training_log() -> JSONResponse:
        return JSONResponse(
            [r.model_dump(mode="json") for r in context.training_log.all()]
        )

    @app.get("/healthz")
    def _healthz() -> dict[str, Any]:
        return {
            "status": "ok",
            "queue_open": len(context.queue.list_open()),
            "training_records": len(context.training_log.all()),
            "artifacts_dir": str(context.artifacts_dir),
        }

    return app


def create_app_from_artifacts(artifacts_dir: Path | str) -> FastAPI:
    """Convenience entry point: build a :class:`ReviewContext` then an app."""
    return build_app(ReviewContext(artifacts_dir=Path(artifacts_dir)))
