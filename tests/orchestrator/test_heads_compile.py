"""Under the super heads' brief (ORBITBRIEF_C3_BRIEF on + envelope.c3_brief):
one handoff build per compile, no planner->brains chain, no prose rewriters,
and a failed brief is a failed compile. Deep audit 2026-10-27 findings 2-9."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from orbitbrief_core.orchestrator import BriefPipeline, PipelineConfig, StageStatus

ROOT = Path(__file__).resolve().parents[2]


class _NoChat:
    """Any LLM call is a test failure."""

    def __getattr__(self, name):
        raise AssertionError(f"chat client used: {name}")


def _heads(env: dict) -> dict:
    env = dict(env)
    env["c3_brief"] = {"version": 2, "service": {"value": "msp", "p": 0.9, "by": "base:deal:primary_service"},
                       "sections": {"scope_of_work": [{"id": "a1", "type": "scope_item", "text": "Monitor."}]},
                       "also_mentioned": [], "questions": [],
                       "written": {"summary": "Monitor 220 endpoints [a1].", "sections": {},
                                   "open_questions": [], "catalog_questions": []}}
    return env


def test_heads_pipeline_skips_stages_20_to_80(tmp_path, msp_envelope_path):
    pipe = BriefPipeline(chat_client=None, config=PipelineConfig(persist_review_queue=False, heads_brief=True))
    result = pipe.compile(msp_envelope_path, out_dir=tmp_path / "out")
    by = {r.stage: r for r in result.stage_records}
    for stage in ("30_planner", "40_brain", "60_calibrator", "80_composer"):
        assert by[stage].status == StageStatus.SKIPPED and "c3_brief" in by[stage].detail["reason"]
    assert by["90_inspection"].status == StageStatus.OK
    cal = tmp_path / "out" / "60_calibrations"
    assert not cal.exists() or not any(cal.iterdir())   # no calibrator_verdict from it


def test_pipeline_never_builds_the_pm_handoff(tmp_path, msp_envelope_path, monkeypatch):
    import orbitbrief_core.pm_handoff as ph

    monkeypatch.setattr(ph, "build_pm_handoff", lambda *a, **k: (_ for _ in ()).throw(AssertionError("built")))
    BriefPipeline(chat_client=None, config=PipelineConfig(persist_review_queue=False)).compile(
        msp_envelope_path, out_dir=tmp_path / "out")


def _compile_brief():
    sys.path.insert(0, str(ROOT))
    import compile_brief

    return compile_brief


def test_compile_builds_the_handoff_once_and_runs_no_rewriter(tmp_path, msp_envelope_dict, monkeypatch):
    monkeypatch.setenv("ORBITBRIEF_C3_BRIEF", "on")
    monkeypatch.delenv("ORBITBRIEF_ROUTER_MODEL", raising=False)
    env_path = tmp_path / "envelope.json"
    env_path.write_text(json.dumps(_heads(msp_envelope_dict)))
    import orbitbrief_core.pm_handoff as ph
    import orbitbrief_core.risk_net as rn
    import orbitbrief_core.pm_handoff.polish as pol

    calls = []
    real = ph.build_pm_handoff
    monkeypatch.setattr(ph, "build_pm_handoff", lambda d: calls.append(d) or real(d))
    for name in ("apply_envelope_passthroughs", "apply_risk_signals", "apply_claim_consensus",
                 "apply_section_narration"):
        monkeypatch.setattr(rn, name, lambda *a, **k: (_ for _ in ()).throw(AssertionError("risk_net ran")))
    monkeypatch.setattr(pol, "polish_pm_handoff", lambda *a, **k: (_ for _ in ()).throw(AssertionError("polish")))
    out = tmp_path / "out"
    rc = _compile_brief().main([str(env_path), "--out", str(out), "--quiet", "--no-persist-queue"])
    assert rc == 0 and len(calls) == 1
    h = json.loads((out / "PM_HANDOFF.json").read_text())
    assert h["executive_summary"]["source"] == "c3_brief"
    assert h["calibrator_verdict"] is None
    assert "missing_sow_items" not in h["metrics"] and "questions_hidden" not in h["metrics"]
    assert "SOW_DRAFT.md" not in h["executive_summary"]["next_action"]
    assert json.loads((out / "polish_report.json").read_text())["skipped"]
    assert "Monitor 220 endpoints" in (out / "91_inspection_report.html").read_text()   # PM block from the one build
    for dead in ("PM_EXECUTIVE_SUMMARY.md", "PM_EXECUTIVE_SUMMARY.html", "SA_REVIEW_PACKET.md",
                 "SA_REVIEW_PACKET.html", "PM_HANDOFF.md"):
        assert not (out / dead).exists()


def test_failed_brief_exits_non_zero_with_marker(tmp_path, msp_envelope_path, monkeypatch):
    import orbitbrief_core.pm_handoff as ph

    monkeypatch.setattr(ph, "build_pm_handoff", lambda d: (_ for _ in ()).throw(IndexError("no such group")))
    out = tmp_path / "out"
    rc = _compile_brief().main([str(msp_envelope_path), "--out", str(out), "--quiet", "--no-persist-queue"])
    assert rc == 3
    marker = json.loads((out / "brief_failed.json").read_text())
    assert marker["brief_failed"] and "no such group" in marker["error"]
    assert not (out / "PM_HANDOFF.json").exists()
