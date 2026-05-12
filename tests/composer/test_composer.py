"""Composer aggregates brain outputs deterministically into a typed ComposedBrief."""
from __future__ import annotations

import json
from typing import Any

import pytest

from orbitbrief_core.brains._briefing import BriefingItem, BriefingState
from orbitbrief_core.brains.managed_services.schema import (
    ManagedServicesScopeState,
    ScopeItem,
)
from orbitbrief_core.calibrator.calibrator import (
    CalibratedItem,
    CalibratorReport,
)
from orbitbrief_core.calibrator.verdict import EscalationReason, Verdict
from orbitbrief_core.composer import (
    ComposedBrief,
    Composer,
    ComposerInputs,
    render_markdown,
)
from orbitbrief_core.validator.report import (
    ItemRef,
    ItemValidation,
    ValidationFailure,
    ValidationReport,
    ValidationRuleId,
    ValidationSeverity,
)
from orbitbrief_core.world_model.planner.schema import BriefState


def _brief() -> BriefState:
    return BriefState(
        project_id="p1",
        compile_id="c1",
        generated_at="2026-01-01T00:00:00Z",
        pack_activations=(
            {"pack_id": "wireless", "status": "active", "confidence": 0.9, "rationale": ""},  # type: ignore[arg-type]
        ),
        sites=(
            {  # type: ignore[arg-type]
                "cluster_id": "site_cluster::site:hq",
                "canonical_name": "HQ",
                "role": "primary",
                "confidence": 0.9,
            },
        ),
        claims=(),
        contradictions=(),
        review_flags=(),
        orchestration=(),
        model_used="qwen3:14b",
        tier="default",
        escalation_log={},
        token_cost={},
    )


def _wireless_state() -> BriefingState:
    item = BriefingItem(
        id="wifi_001",
        statement="Predictive wireless survey of 12 buildings.",
        supporting_packet_ids=("pkt_w1",),
        supporting_atom_ids=("a_w1",),
        confidence=0.88,
        metadata={"survey_type": "Predictive Survey"},
    )
    return BriefingState(
        project_id="p1",
        compile_id="c1",
        generated_at="2026-01-01T00:00:00Z",
        domain_id="wireless",
        scope_overview=(item,),
        detailed_scope_of_services=(item,),
        deliverables=(item,),
    )


def _msp_state() -> ManagedServicesScopeState:
    si = ScopeItem(
        id="msp_scope_001",
        statement="24x7 endpoint monitoring across 220 devices.",
        supporting_packet_ids=("pkt_m1",),
        supporting_atom_ids=("a_m1",),
        confidence=0.9,
        category="monitoring",
    )
    return ManagedServicesScopeState(
        project_id="p1",
        compile_id="c1",
        generated_at="2026-01-01T00:00:00Z",
        scope_items=(si,),
    )


def _calibration_for(
    *, project_id: str, compile_id: str, brain: str, section: str, item_id: str,
    verdict: Verdict, calibrated: float = 0.85,
) -> CalibratorReport:
    ref = ItemRef(
        project_id=project_id, compile_id=compile_id,
        brain=brain, section=section, item_id=item_id,
    )
    return CalibratorReport(
        project_id=project_id, compile_id=compile_id, brain=brain,
        items=(
            CalibratedItem(
                ref=ref,
                raw_confidence=0.7,
                calibrated_confidence=calibrated,
                verdict=verdict,
                reasons=(EscalationReason.AUTO_OK if verdict is Verdict.AUTO_ACCEPT else EscalationReason.BORDERLINE_CONFIDENCE,),
                signals={},
                payload={"id": item_id},
            ),
        ),
    )


def test_composer_emits_typed_composed_brief() -> None:
    inputs = ComposerInputs(
        brief=_brief(),
        brain_states={"wireless": _wireless_state()},
    )
    composed = Composer().compose(inputs)
    assert isinstance(composed, ComposedBrief)
    assert composed.summary.project_id == "p1"
    assert composed.summary.active_packs == ("wireless",)
    assert len(composed.sites) == 1
    assert len(composed.domains) == 1
    group = composed.domains[0]
    assert group.pack_id == "wireless"
    assert group.brain == "wireless"
    nonempty = [s for s in group.sections if s.items]
    assert {s.section_id for s in nonempty} == {
        "scope_overview",
        "detailed_scope_of_services",
        "deliverables",
    }


def test_composer_handles_two_brains_one_msp_one_briefing() -> None:
    inputs = ComposerInputs(
        brief=_brief(),
        brain_states={
            "wireless": _wireless_state(),
            "msp": _msp_state(),
        },
    )
    composed = Composer().compose(inputs)
    pack_ids = {g.pack_id for g in composed.domains}
    assert pack_ids == {"wireless", "msp"}
    msp_group = next(g for g in composed.domains if g.pack_id == "msp")
    assert msp_group.brain == "managed_services"
    # Managed-services scope_items section is preserved with its 1 item.
    si = next(s for s in msp_group.sections if s.section_id == "scope_items")
    assert si.item_count == 1
    assert si.items[0].metadata.get("category") == "monitoring"


def test_composer_attaches_calibrator_verdict_per_item() -> None:
    state = _wireless_state()
    cal = _calibration_for(
        project_id="p1", compile_id="c1", brain="wireless",
        section="scope_overview", item_id="wifi_001",
        verdict=Verdict.NEEDS_REVIEW, calibrated=0.65,
    )
    inputs = ComposerInputs(
        brief=_brief(),
        brain_states={"wireless": state},
        calibrations={"wireless": cal},
    )
    composed = Composer().compose(inputs)
    grp = composed.domains[0]
    overview = next(s for s in grp.sections if s.section_id == "scope_overview")
    item = overview.items[0]
    assert item.verdict is Verdict.NEEDS_REVIEW
    assert pytest.approx(item.calibrated_confidence, abs=1e-9) == 0.65
    assert composed.review_count == 1
    assert composed.blocker_count == 0
    # The other two sections (detailed_scope_of_services + deliverables)
    # share the same item but had no per-section calibration → default
    # to AUTO_ACCEPT. Real pipelines calibrate every section; this test
    # exercises the partial-calibration fallback path.
    assert composed.auto_accept_count == 2


def test_composer_includes_validation_failures() -> None:
    state = _wireless_state()
    ref = ItemRef(
        project_id="p1", compile_id="c1", brain="wireless",
        section="scope_overview", item_id="wifi_001",
    )
    val = ValidationReport(
        project_id="p1", compile_id="c1", brain="wireless",
        items=(
            ItemValidation(
                item=ref,
                failures=(
                    ValidationFailure(
                        rule_id=ValidationRuleId.MISSING_SOURCE_REF,
                        severity=ValidationSeverity.WARNING,
                        message="atom locator missing",
                    ),
                ),
            ),
        ),
    )
    inputs = ComposerInputs(
        brief=_brief(),
        brain_states={"wireless": state},
        validations={"wireless": val},
    )
    composed = Composer().compose(inputs)
    item = composed.domains[0].sections[0].items[0]
    assert any(f["rule_id"] == "missing_source_ref" for f in item.validation_failures)


def test_composer_aggregates_open_questions() -> None:
    state = _wireless_state().model_copy(
        update={
            "open_items": (
                BriefingItem(
                    id="oq_001",
                    statement="Ceiling height per building unspecified.",
                    supporting_packet_ids=("pkt_w1",),
                    confidence=0.8,
                ),
            )
        }
    )
    composed = Composer().compose(
        ComposerInputs(
            brief=_brief(),
            brain_states={"wireless": state},
        )
    )
    assert len(composed.open_questions) == 1
    assert composed.open_questions[0].item_id == "oq_001"


def test_composer_is_deterministic() -> None:
    inputs = ComposerInputs(
        brief=_brief(),
        brain_states={"wireless": _wireless_state()},
    )
    a = Composer().compose(inputs)
    b = Composer().compose(inputs)
    # generated_at is stamped at compose-time; everything else must match.
    a_dump = a.model_dump(mode="json"); a_dump["generated_at"] = ""; a_dump["summary"]["generated_at"] = ""
    b_dump = b.model_dump(mode="json"); b_dump["generated_at"] = ""; b_dump["summary"]["generated_at"] = ""
    assert a_dump == b_dump


def test_render_markdown_includes_summary_and_section_headings() -> None:
    composed = Composer().compose(
        ComposerInputs(
            brief=_brief(),
            brain_states={"wireless": _wireless_state()},
        )
    )
    md = render_markdown(composed)
    assert "# OrbitBrief — p1" in md
    assert "## Executive Summary" in md
    assert "## Wireless" in md
    assert "### Scope Overview" in md
    assert "Predictive wireless survey of 12 buildings." in md


def test_render_markdown_marks_fallback_brains() -> None:
    composed = Composer().compose(
        ComposerInputs(
            brief=_brief(),
            brain_states={"wireless": _wireless_state()},
            fallback_used={"wireless": True},
        )
    )
    md = render_markdown(composed)
    assert "## Wireless (fallback)" in md
