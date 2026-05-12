"""Deterministic escalation rules pick the right model + log a reason.

Phase-4 verify gate: a synthetic high-contradiction case forces
the 32B tier; the logged reason matches the firing rule.
"""
from __future__ import annotations

import json
from typing import Any

from orbitbrief_core.world_model.pack_prior import PackPrior, PackPriorState
from orbitbrief_core.world_model.planner import Planner
from orbitbrief_core.world_model.planner.escalation import (
    PlannerEscalationReason,
    PlannerTier,
    decide_tier,
)
from orbitbrief_core.world_model.site_reality import (
    SiteRealityEngine,
    SiteRealityState,
)

from tests.world_model.planner.conftest import (
    ScriptedChatClient,
    _valid_brief_payload,
)


def _envelope_with_contradictions(
    n_atoms: int, n_contradictions: int
) -> dict[str, Any]:
    """Synthetic envelope with high contradiction density."""
    atoms = [
        {
            "id": f"a{i}",
            "artifact_id": "art",
            "atom_type": "scope_item",
            "authority_class": "machine_extractor",
            "confidence": 0.9,
            "text": f"wireless ap install at site {i} with controller deployment",
            "section_path": [],
            "locator": {},
            "verified": "unverified",
        }
        for i in range(n_atoms)
    ]
    edges = [
        {
            "id": f"ed_{i}",
            "edge_type": "contradicts",
            "from_atom_id": f"a{2 * i}",
            "to_atom_id": f"a{2 * i + 1}",
            "reason": "synthetic_contradiction",
            "confidence": 0.95,
            "cross_artifact": False,
            "metadata": {},
        }
        for i in range(n_contradictions)
    ]
    # One entity that touches every atom so the runtime contradiction
    # walker actually finds the edges.
    entity = {
        "id": "e1",
        "entity_type": "thing",
        "canonical_key": "thing:all",
        "canonical_name": "All",
        "aliases": [],
        "artifact_ids": ["art"],
        "source_atom_ids": [a["id"] for a in atoms],
        "review_status": "auto_accepted",
        "confidence": 0.9,
    }
    return {
        "schema_version": "orbitbrief.input.v2",
        "project_id": "synthetic_contradictions",
        "compile_id": "syn_001",
        "generated_at": "2026-01-01T00:00:00Z",
        "summary": {
            "artifact_count": 1, "page_count": 1,
            "atom_count": n_atoms, "packet_count": 0,
            "entity_count": 1, "edge_count": n_contradictions,
        },
        "documents": [
            {
                "artifact_id": "art", "filename": "syn.txt",
                "artifact_type": "txt", "sha256": "0" * 64,
                "size_bytes": 1024, "parser_name": "t",
                "parser_version": "0.0.0", "structured": {},
                "atom_ids": [a["id"] for a in atoms],
            }
        ],
        "atoms": atoms,
        "entities": [entity],
        "edges": edges,
        "packets": [],
        "indexes": {
            "atoms_by_section_path": {}, "atoms_by_atom_type": {},
            "atoms_by_authority": {}, "atoms_by_artifact": {
                "art": [a["id"] for a in atoms]
            },
            "atoms_by_entity_key": {"thing:all": [a["id"] for a in atoms]},
            "edges_by_atom": {},
            "entity_id_by_canonical_key": {"thing:all": "e1"},
        },
    }


def test_unit_decide_tier_contradiction_density() -> None:
    """A contradiction density above the threshold → escalated tier with the right reason."""
    env = _envelope_with_contradictions(n_atoms=20, n_contradictions=5)
    pp = PackPriorState(
        project_id="x", compile_id="y", scores=(),
        top_pack_id="wireless", top_confidence=0.8,
        runner_up_pack_id="other", runner_up_confidence=0.2,
        margin=0.6,
    )
    sr = SiteRealityState(
        project_id="x", compile_id="y", clusters=(),
        cluster_count=0, escalation_log={"count": 0, "by_reason": {}, "entries": []},
    )
    decision = decide_tier(
        pack_prior=pp, site_reality=sr, envelope=env, contradiction_count=5
    )
    assert decision.tier is PlannerTier.ESCALATED
    assert PlannerEscalationReason.CONTRADICTION_DENSITY in decision.reasons


def test_unit_decide_tier_pack_ambiguity() -> None:
    """A near-tied pack prior triggers the ambiguity rule."""
    env = {"atoms": [{"authority_class": "machine_extractor"} for _ in range(50)]}
    pp = PackPriorState(
        project_id="x", compile_id="y", scores=(),
        top_pack_id="wireless", top_confidence=0.51,
        runner_up_pack_id="other", runner_up_confidence=0.49,
        margin=0.02,
    )
    sr = SiteRealityState(
        project_id="x", compile_id="y", clusters=(),
        cluster_count=0, escalation_log={"count": 0, "by_reason": {}, "entries": []},
    )
    decision = decide_tier(
        pack_prior=pp, site_reality=sr, envelope=env, contradiction_count=0
    )
    assert decision.tier is PlannerTier.ESCALATED
    assert PlannerEscalationReason.PACK_AMBIGUITY in decision.reasons


def test_unit_decide_tier_default_path() -> None:
    """Clean inputs → default tier, no reasons."""
    env = {
        "atoms": [
            {"authority_class": "machine_extractor"} for _ in range(100)
        ],
    }
    pp = PackPriorState(
        project_id="x", compile_id="y", scores=(),
        top_pack_id="wireless", top_confidence=0.9,
        runner_up_pack_id="other", runner_up_confidence=0.1,
        margin=0.8,
    )
    sr = SiteRealityState(
        project_id="x", compile_id="y", clusters=(),
        cluster_count=2, escalation_log={"count": 0, "by_reason": {}, "entries": []},
    )
    decision = decide_tier(
        pack_prior=pp, site_reality=sr, envelope=env, contradiction_count=1
    )
    assert decision.tier is PlannerTier.DEFAULT
    assert decision.reasons == ()


def test_unit_decide_tier_unstable_site_model() -> None:
    """High site_reality LLM-call ratio → unstable_site_model reason."""
    env = {"atoms": [{"authority_class": "machine_extractor"} for _ in range(50)]}
    pp = PackPriorState(
        project_id="x", compile_id="y", scores=(),
        top_pack_id="wireless", top_confidence=0.9,
        runner_up_pack_id="other", runner_up_confidence=0.1,
        margin=0.8,
    )
    sr = SiteRealityState(
        project_id="x", compile_id="y", clusters=(),
        cluster_count=3,
        escalation_log={
            "count": 2,
            "by_reason": {"site_reality_ambiguous_name": 2},
            "entries": [],
        },
    )
    decision = decide_tier(
        pack_prior=pp, site_reality=sr, envelope=env, contradiction_count=0
    )
    assert decision.tier is PlannerTier.ESCALATED
    assert PlannerEscalationReason.UNSTABLE_SITE_MODEL in decision.reasons


def test_planner_uses_escalated_model_when_contradictions_high(
    runtime_from_envelope,
) -> None:
    """End-to-end: synthetic high-contradiction case forces qwen3:32b in the call log."""
    env = _envelope_with_contradictions(n_atoms=20, n_contradictions=5)
    rt = runtime_from_envelope(env)
    pp = PackPrior.with_default_registry(chat_client=None).compute(rt)
    sr = SiteRealityEngine(chat_client=None).compute(rt)

    payload = _valid_brief_payload(
        project_id=rt.default_key.project_id,
        compile_id=rt.default_key.compile_id,
        pack_ids=(pp.top_pack_id,),
        cluster_ids=(),
        atom_ids=[a["id"] for a in env["atoms"]],
    )
    chat = ScriptedChatClient(replies=[json.dumps(payload)])
    planner = Planner.with_default_registry(chat_client=chat)
    result = planner.compose(rt, pack_prior=pp, site_reality=sr)

    assert result.escalation.tier is PlannerTier.ESCALATED
    assert chat.call_log[0]["model"] == planner.escalated_model
    assert result.state.tier == "escalated"
    log = result.state.escalation_log
    assert log["tier"] == "escalated"
    assert PlannerEscalationReason.CONTRADICTION_DENSITY.value in log["reasons"]
