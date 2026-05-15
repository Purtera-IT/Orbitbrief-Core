"""Tests for ``inspection_html.render_inspection_html`` empty-state behavior.

The dashboard used to render a substrate-only run as if it were broken
("(no brains ran for this engagement)") with no context about why brains
were absent. These tests lock in the new behavior:

* Substrate-only runs show a clear "Substrate-only run (no LLM)" badge,
  surface the rerun command, and explain why brain/composed sections
  are empty.
* LLM runs that completed surface ``brains_run`` in the badge and never
  render the substrate-only callout.
* Pipeline log gets a stage-status summary line above the table when
  any stages were recorded.
"""

from __future__ import annotations

from typing import Any

import pytest

from orbitbrief_core.orchestrator.inspection_html import (
    _run_mode,
    render_inspection_html,
)


def _empty_funnel() -> dict[str, Any]:
    return {
        "source_artifacts": 0,
        "atoms_extracted": 0,
        "entities_normalized": 0,
        "edges_built": 0,
        "packets_certified": 0,
        "active_packs": [],
        "bundled_packets_total": 0,
        "bundled_packets_per_pack": {},
        "brain_items_per_pack": {},
        "brain_cited_packets": 0,
        "brain_cited_atoms": 0,
        "composed_brief_items": 0,
        "atoms_to_brief_pct": 0.0,
        "packets_to_brief_pct": 0.0,
        "pack_prior_top": None,
        "pack_prior_margin": None,
    }


def _base_report(*, manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": "TEST_PROJECT",
        "compile_id": "test_compile",
        "funnel": _empty_funnel(),
        "pack_prior": {},
        "site_reality": {},
        "artifacts": [],
        "entities": [],
        "edges": [],
        "packets": [],
        "brain_items": {},
        "validations": {},
        "calibrations": {},
        "composed_brief_summary": {},
        "review_queue": {"open_count": 0, "decided_count": 0, "decisions_logged": 0},
        "pipeline_log": [],
        "manifest": manifest,
        "refined_brief": {},
    }


def test_substrate_only_run_shows_clear_badge_and_rerun_hint() -> None:
    manifest = {
        "generated_at": "2026-05-15T14:00:00Z",
        "active_packs": [],
        "brains_run": [],
        "skipped_brains_no_chat": True,
        "stage_count": 0,
        "stage_status_counts": {},
    }
    html = render_inspection_html(_base_report(manifest=manifest))
    assert "Substrate-only run (no LLM)" in html
    assert "mode-warn" in html
    assert "compile_brief.py" in html
    assert "--ollama" in html
    # Header should not pretend the planner model is missing — it
    # should explicitly say substrate-only instead of "—".
    assert "substrate-only" in html
    # Old broken-looking copy must be gone.
    assert "(no brains ran for this engagement)" not in html


def test_llm_run_shows_brains_run_in_badge() -> None:
    manifest = {
        "generated_at": "2026-05-15T14:00:00Z",
        "active_packs": ["low_voltage_cabling", "msp"],
        "brains_run": ["low_voltage_cabling", "msp"],
        "skipped_brains_no_chat": False,
        "stage_count": 21,
        "stage_status_counts": {"ok": 17, "skipped": 3, "fallback": 1},
    }
    report = _base_report(manifest=manifest)
    report["refined_brief"] = {
        "model_used": "qwen3:14b",
        "tier": "default",
        "token_cost": {"total_tokens": 13943},
    }
    report["pipeline_log"] = [
        {"stage": "10_pack_prior", "status": "ok", "duration_ms": 120, "detail": {}},
        {"stage": "40_brain", "status": "ok", "duration_ms": 8500, "detail": {"pack": "msp"}},
        {"stage": "60_calibration", "status": "fallback", "duration_ms": 30, "detail": {}},
    ]
    html = render_inspection_html(report)
    assert "LLM run · brains: low_voltage_cabling, msp" in html
    assert "mode-ok" in html
    # Pipeline log should now carry the stage-status summary line.
    assert "3 stages · total 8650 ms" in html
    # And the substrate-only callout must NOT appear when brains ran.
    assert "Substrate-only run (no LLM)" not in html


def test_run_mode_categorizes_skipped_active_unknown() -> None:
    assert _run_mode({"skipped_brains_no_chat": True})["mode"] == "substrate"
    assert _run_mode({"brains_run": ["msp"]})["mode"] == "llm"
    assert _run_mode({"active_packs": ["msp"], "brains_run": []})["mode"] == "llm"
    assert _run_mode({})["mode"] == "unknown"


@pytest.mark.parametrize("manifest", [
    {"skipped_brains_no_chat": True},
    {"brains_run": ["msp"]},
    {},
])
def test_render_never_throws_with_minimal_manifest(manifest: dict[str, Any]) -> None:
    # Defensive: catch regressions where the new manifest-aware blocks
    # crash on partial dict shapes.
    html = render_inspection_html(_base_report(manifest=manifest))
    assert "<html" in html
    assert "</html>" in html


def test_verification_block_surfaces_failed_atom_health() -> None:
    """The Source verification block must show health %, the failed
    counts, and the top failed artifact when the parser is drifting.

    Regression guard for the case the user flagged: ``verified=failed``
    was already in the data but invisible in the dashboard, so parser
    drift could go unnoticed for entire engagements.
    """
    report = _base_report(manifest={"brains_run": ["msp"]})
    report["verification"] = {
        "atom_total": 10,
        "counts": {"verified": 6, "failed": 3, "partial": 1},
        "verified_count": 6,
        "failed_count": 3,
        "partial_count": 1,
        "unverified_count": 0,
        "unsupported_count": 0,
        "verified_pct": 60.0,
        "failed_pct": 30.0,
        "partial_pct": 10.0,
        "health_pct": 60.0,
        "top_failed_artifacts": [
            {
                "artifact_id": "art_abc",
                "filename": "RFP_addendum.pdf",
                "artifact_type": "pdf",
                "failed_atoms": 3,
                "atom_count": 7,
            }
        ],
    }
    html = render_inspection_html(report)
    assert "Source verification" in html
    # 60% should hit the warn band (< 80% would be the bad band, but
    # exactly 60 is bad). Either way the bad/warn badge must show.
    assert "parser regression suspected" in html or "look closely" in html
    # Counts must be in the KPI strip.
    assert ">3</strong> failed" in html
    assert ">6</strong> verified" in html
    # Top failed artifact must be linkable.
    assert "RFP_addendum.pdf" in html


def test_verification_block_clean_corpus_shows_ok_badge() -> None:
    report = _base_report(manifest={"brains_run": ["msp"]})
    report["verification"] = {
        "atom_total": 100,
        "counts": {"verified": 100},
        "verified_count": 100,
        "failed_count": 0,
        "partial_count": 0,
        "unverified_count": 0,
        "unsupported_count": 0,
        "verified_pct": 100.0,
        "failed_pct": 0.0,
        "partial_pct": 0.0,
        "health_pct": 100.0,
        "top_failed_artifacts": [],
    }
    html = render_inspection_html(report)
    assert "100.0% atoms replayed clean" in html
    assert "mode-ok" in html
    assert "no failed atoms" in html
