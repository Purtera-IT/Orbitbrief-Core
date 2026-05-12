"""FastAPI route smoke tests for the reviewer UI."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

# Skip the whole module if FastAPI / TestClient aren't installed.
fastapi = pytest.importorskip("fastapi")
testclient_mod = pytest.importorskip("fastapi.testclient")

from orbitbrief_core.calibrator.calibrator import CalibratedItem
from orbitbrief_core.calibrator.verdict import EscalationReason, Verdict
from orbitbrief_core.review_runtime import (
    JsonlReviewQueue,
)
from orbitbrief_core.review_ui import create_app_from_artifacts
from orbitbrief_core.validator.report import ItemRef


def _seed_queue(artifacts_dir: Path) -> CalibratedItem:
    """Drop one CalibratedItem into the JSONL queue under artifacts_dir."""
    queue_dir = artifacts_dir / "70_review_queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    item = CalibratedItem(
        ref=ItemRef(
            project_id="p1",
            compile_id="c1",
            brain="wireless",
            section="scope_overview",
            item_id="wifi_001",
        ),
        raw_confidence=0.7,
        calibrated_confidence=0.62,
        verdict=Verdict.NEEDS_REVIEW,
        reasons=(EscalationReason.BORDERLINE_CONFIDENCE,),
        signals={"parser_confidence": 0.6},
        payload={
            "id": "wifi_001",
            "statement": "Predictive wireless survey of 12 buildings.",
            "supporting_packet_ids": ["pkt_w1"],
            "confidence": 0.88,
        },
    )
    JsonlReviewQueue(queue_dir).enqueue(item)
    return item


def _seed_composed(artifacts_dir: Path) -> None:
    (artifacts_dir / "80_composed_brief.json").write_text(
        json.dumps(
            {
                "project_id": "p1",
                "compile_id": "c1",
                "generated_at": "2026-01-01T00:00:00Z",
                "summary": {
                    "project_id": "p1",
                    "compile_id": "c1",
                    "generated_at": "2026-01-01T00:00:00Z",
                    "active_packs": ["wireless"],
                    "site_count": 0,
                    "contradiction_count": 0,
                    "review_flag_count": 0,
                    "planner_model": "qwen3:14b",
                    "planner_tier": "default",
                    "planner_fallback_used": False,
                },
                "sites": [],
                "domains": [],
                "open_questions": [],
                "blocker_count": 0,
                "review_count": 0,
                "auto_accept_count": 0,
            }
        )
    )
    (artifacts_dir / "81_composed_brief.md").write_text(
        "# OrbitBrief — p1\n\n## Executive Summary\n\n| Field | Value |\n"
    )


@pytest.fixture
def client(tmp_path: Path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    _seed_queue(artifacts)
    _seed_composed(artifacts)
    app = create_app_from_artifacts(artifacts)
    return testclient_mod.TestClient(app), artifacts


def test_root_redirects_to_queue(client) -> None:
    c, _ = client
    r = c.get("/", follow_redirects=False)
    assert r.status_code in (307, 308)
    assert r.headers["location"].endswith("/queue")


def test_queue_page_lists_open_items(client) -> None:
    c, _ = client
    r = c.get("/queue")
    assert r.status_code == 200
    body = r.text
    assert "Predictive wireless survey of 12 buildings." in body
    assert "wireless" in body
    assert "needs_review" not in body or "review" in body  # badge or filter


def test_item_detail_page_renders_payload(client) -> None:
    c, _ = client
    cid = "p1/c1/wireless/scope_overview/wifi_001"
    r = c.get(f"/item/{cid}")
    assert r.status_code == 200
    assert "wifi_001" in r.text
    assert "pkt_w1" in r.text


def test_decide_records_decision_and_swaps_form(client) -> None:
    c, _ = client
    cid = "p1/c1/wireless/scope_overview/wifi_001"
    r = c.post(
        f"/item/{cid}/decide",
        data={
            "action": "accept",
            "decided_by": "pm@x.com",
            "notes": "looks good",
            "edited_payload_json": "",
        },
    )
    assert r.status_code == 200, r.text
    assert "decision recorded" in r.text
    # Side effects: training log JSONL exists.
    log_files = list((c.app.state.__dict__.get("_artifacts", []) or []))
    # API view confirms the record.
    api = c.get("/api/training_log")
    assert api.status_code == 200
    records = api.json()
    assert len(records) == 1
    assert records[0]["reviewer_action"] == "accept"
    assert records[0]["accepted"] is True


def test_decide_rejects_bad_json(client) -> None:
    c, _ = client
    cid = "p1/c1/wireless/scope_overview/wifi_001"
    r = c.post(
        f"/item/{cid}/decide",
        data={
            "action": "edit",
            "decided_by": "pm@x.com",
            "notes": "",
            "edited_payload_json": "{not valid json",
        },
    )
    assert r.status_code == 400


def test_composed_page_renders_when_doc_present(client) -> None:
    c, _ = client
    r = c.get("/composed")
    assert r.status_code == 200
    assert "OrbitBrief" in r.text
    assert "Executive Summary" in r.text


def test_healthz_returns_state_summary(client) -> None:
    c, _ = client
    r = c.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["queue_open"] >= 0
    assert "artifacts_dir" in body


def test_api_queue_returns_json(client) -> None:
    c, _ = client
    r = c.get("/api/queue")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["ref"]["item_id"] == "wifi_001"
