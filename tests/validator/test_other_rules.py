"""Coverage for the non-path-legality validator rules."""
from __future__ import annotations

import pytest

from orbitbrief_core.validator import (
    BrainOutputValidator,
    DictEvidenceLookup,
    PackIncompatibility,
    ValidationRuleId,
    ValidationSeverity,
)
from orbitbrief_core.world_model.planner.schema import BriefState


def _scope_item(item_id: str, *, packets, atoms, statement: str = ""):
    return {
        "id": item_id,
        "statement": statement or f"item {item_id}",
        "supporting_packet_ids": list(packets),
        "supporting_atom_ids": list(atoms),
        "confidence": 0.85,
        "category": "general",
    }


def test_missing_evidence_when_no_atom_ids(
    build_state, small_bundle, small_brief
) -> None:
    """An item citing only packets (no atoms) trips MISSING_EVIDENCE WARNING."""
    state = build_state(
        {"scope_items": [_scope_item("s1", packets=("pkt_s1",), atoms=())]}
    )
    validator = BrainOutputValidator(lookup=DictEvidenceLookup(atoms={}))
    report = validator.validate_managed_services(
        state, brief=small_brief, bundle=small_bundle
    )
    iv = report.items[0]
    rules = {f.rule_id for f in iv.failures}
    assert ValidationRuleId.MISSING_EVIDENCE in rules


def test_impossible_state_when_replay_failed(
    build_state, small_bundle, small_brief
) -> None:
    """Cite an atom whose ``verified == failed`` → BLOCKER IMPOSSIBLE_STATE."""
    bad_lookup = DictEvidenceLookup(
        atoms={
            "a1": {
                "id": "a1",
                "text": "MSP scope item",
                "verified": "failed",
                "locator": {"page": 5},
            },
        }
    )
    state = build_state(
        {"scope_items": [_scope_item("s1", packets=("pkt_s1",), atoms=("a1",))]}
    )
    validator = BrainOutputValidator(lookup=bad_lookup)
    report = validator.validate_managed_services(
        state, brief=small_brief, bundle=small_bundle
    )
    iv = report.items[0]
    rules = {f.rule_id for f in iv.failures}
    assert ValidationRuleId.IMPOSSIBLE_STATE in rules
    assert iv.has_blocker


def test_site_count_sanity_flags_inflated_quantity(
    build_state, small_bundle, small_brief, lookup_with_two_atoms
) -> None:
    """Item statement claims 50 sites but BriefState has 0 → INFO SITE_COUNT_SANITY."""
    # Rebuild brief with 0 sites — already is 0 in the fixture.
    state = build_state(
        {
            "scope_items": [
                _scope_item(
                    "s1",
                    packets=("pkt_s1",),
                    atoms=("a1",),
                    statement="Roll out monitoring across 50 sites in EMEA.",
                )
            ]
        }
    )
    validator = BrainOutputValidator(lookup=lookup_with_two_atoms)
    report = validator.validate_managed_services(
        state, brief=small_brief, bundle=small_bundle
    )
    iv = report.items[0]
    rules = [(f.rule_id, f.severity) for f in iv.failures]
    assert (ValidationRuleId.SITE_COUNT_SANITY, ValidationSeverity.INFO) in rules


def test_pack_incompatibility_at_project_level(
    build_state, small_bundle, lookup_with_two_atoms
) -> None:
    """Two incompatible packs both active → project-level WARNING PACK_INCOMPATIBILITY."""
    brief = BriefState(
        project_id="p1",
        compile_id="c1",
        generated_at="2026-01-01T00:00:00Z",
        pack_activations=(
            {"pack_id": "itad", "status": "active", "confidence": 0.9, "rationale": ""},  # type: ignore[arg-type]
            {"pack_id": "hardware", "status": "active", "confidence": 0.85, "rationale": ""},  # type: ignore[arg-type]
        ),
        sites=(), claims=(), contradictions=(), review_flags=(), orchestration=(),
        model_used="qwen3:14b", tier="default",
        escalation_log={}, token_cost={},
    )
    state = build_state({})
    validator = BrainOutputValidator(lookup=lookup_with_two_atoms)
    report = validator.validate_managed_services(
        state, brief=brief, bundle=small_bundle
    )
    rule_ids = {f.rule_id for f in report.project_failures}
    assert ValidationRuleId.PACK_INCOMPATIBILITY in rule_ids
