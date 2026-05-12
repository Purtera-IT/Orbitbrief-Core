"""Coverage for the Phase-7.5 briefing brains.

Each domain shares the same canonical 9-section :class:`BriefingState`
and the same :class:`BriefingBrain` runner, so we drive every brain
through the same parameterized test rather than copy-pasting per
domain.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from orbitbrief_core.brains import (
    BriefingItem,
    BriefingState,
    CANONICAL_SECTIONS,
    PacketSnippet,
    RetrievalBundle,
    known_briefing_domains,
    load_briefing_config,
)
from orbitbrief_core.brains._briefing_runner import BriefingBrain
from orbitbrief_core.brains.datacenter import DatacenterBrain
from orbitbrief_core.brains.imac import ImacBrain
from orbitbrief_core.brains.low_voltage_cabling import LowVoltageCablingBrain
from orbitbrief_core.brains.rack_and_stack import RackAndStackBrain
from orbitbrief_core.brains.wireless import WirelessBrain
from orbitbrief_core.world_model.planner.schema import BriefState

from tests.brains.conftest import ScriptedChatClient


BRAIN_CLASSES = {
    "wireless": WirelessBrain,
    "low_voltage_cabling": LowVoltageCablingBrain,
    "rack_and_stack": RackAndStackBrain,
    "datacenter": DatacenterBrain,
    "imac": ImacBrain,
}


@pytest.fixture
def briefing_brief() -> BriefState:
    return BriefState(
        project_id="bp1",
        compile_id="bc1",
        generated_at="2026-01-01T00:00:00Z",
        pack_activations=(
            {"pack_id": "wireless", "status": "active", "confidence": 0.9, "rationale": ""},  # type: ignore[arg-type]
        ),
        sites=(),
        claims=(),
        contradictions=(),
        review_flags=(),
        orchestration=(),
        model_used="qwen3:14b",
        tier="default",
        escalation_log={"metrics": {"pack_margin": 0.5}},
        token_cost={},
    )


def _packet(pid: str, family: str, *, atom_text: dict[str, str]) -> PacketSnippet:
    return PacketSnippet(
        packet_id=pid,
        family=family,
        anchor_type="generic",
        anchor_key=family,
        status="active",
        confidence=0.9,
        governing_atom_ids=tuple(atom_text.keys()),
        atom_text=atom_text,
    )


@pytest.fixture
def briefing_bundle() -> RetrievalBundle:
    return RetrievalBundle(
        project_id="bp1",
        compile_id="bc1",
        packets_by_family={
            "scope_inclusion": (
                _packet("p1", "scope_inclusion", atom_text={"a1": "Predictive wireless survey for 12 buildings."}),
            ),
            "scope_exclusion": (
                _packet("p2", "scope_exclusion", atom_text={"a2": "AP install hardware out of scope."}),
            ),
            "compliance_clause": (
                _packet("p3", "compliance_clause", atom_text={"a3": "All gear must satisfy FCC Part 15."}),
            ),
            "missing_info": (
                _packet("p4", "missing_info", atom_text={"a4": "Ceiling height per building unspecified."}),
            ),
        },
    )


def _payload(domain_id: str) -> str:
    """Build a payload that uses each section at least once with valid grounding."""
    item = lambda i, sec, pkt, atom: {
        "id": f"{sec}_{i:03d}",
        "statement": f"{sec.replace('_', ' ').capitalize()} statement {i}.",
        "supporting_packet_ids": [pkt],
        "supporting_atom_ids": [atom],
        "confidence": 0.85,
        "metadata": {},
    }
    return json.dumps({
        "project_id": "bp1",
        "compile_id": "bc1",
        "generated_at": "2026-01-01T00:00:00Z",
        "domain_id": domain_id,
        "scope_overview":              [item(1, "scope_overview", "p1", "a1")],
        "detailed_scope_of_services":  [item(1, "detailed_scope_of_services", "p1", "a1")],
        "deliverables":                [item(1, "deliverables", "p1", "a1")],
        "assumptions":                 [item(1, "assumptions", "p3", "a3")],
        "customer_responsibilities":   [item(1, "customer_responsibilities", "p1", "a1")],
        "out_of_scope":                [item(1, "out_of_scope", "p2", "a2")],
        "risks_or_dependencies":       [item(1, "risks_or_dependencies", "p4", "a4")],
        "completion_criteria":         [item(1, "completion_criteria", "p1", "a1")],
        "open_items":                  [item(1, "open_items", "p4", "a4")],
    })


# ───── known config registry sanity ─────


def test_workbook_lists_five_briefing_domains() -> None:
    """The bundled YAML must list the five Phase-7.5 domains."""
    domains = set(known_briefing_domains())
    assert {
        "wireless",
        "low_voltage_cabling",
        "rack_and_stack",
        "datacenter",
        "imac",
    } <= domains, domains


def test_each_domain_has_all_nine_canonical_fields() -> None:
    """Every briefing domain's config must populate all 9 canonical fields."""
    for d in BRAIN_CLASSES:
        cfg = load_briefing_config(d)
        missing = [s for s in CANONICAL_SECTIONS if s not in cfg.fields]
        assert not missing, f"{d}: missing fields {missing}"
        # And each has at least one guidance bullet.
        for s in CANONICAL_SECTIONS:
            assert cfg.guidance_for(s), f"{d}/{s}: empty guidance"


def test_wireless_workbook_normalization_loaded() -> None:
    """Wireless ships rich normalization vocabularies straight from the workbook."""
    cfg = load_briefing_config("wireless")
    assert "survey_type_labels" in cfg.normalization
    assert "delivery_model_labels" in cfg.normalization
    assert "common_wireless_terms" in cfg.normalization
    assert "Predictive Survey" in cfg.normalization["survey_type_labels"]


# ───── per-brain compose() ─────


@pytest.mark.parametrize("domain_id, brain_cls", list(BRAIN_CLASSES.items()))
def test_brain_compose_returns_validated_briefing_state(
    domain_id: str,
    brain_cls: type,
    briefing_brief: BriefState,
    briefing_bundle: RetrievalBundle,
) -> None:
    """Happy path per brain: scripted-LLM payload → validated BriefingState."""
    chat = ScriptedChatClient(replies=[_payload(domain_id)])
    brain: BriefingBrain = brain_cls(chat_client=chat)
    result = brain.compose(briefing_brief, briefing_bundle)
    assert isinstance(result.state, BriefingState)
    assert result.state.domain_id == domain_id
    assert result.fallback_used is False
    # Provenance stamped post-call.
    assert result.state.model_used == "qwen3:14b"
    assert result.state.token_cost["total_tokens"] > 0
    # Every section emitted exactly one item.
    for section in CANONICAL_SECTIONS:
        items = result.state.section_items(section)
        assert len(items) == 1, f"{domain_id}/{section}: expected 1 item"


@pytest.mark.parametrize("domain_id, brain_cls", list(BRAIN_CLASSES.items()))
def test_brain_fallback_skeleton_validates(
    domain_id: str,
    brain_cls: type,
    briefing_brief: BriefState,
    briefing_bundle: RetrievalBundle,
) -> None:
    """LLM returns garbage twice → deterministic skeleton, still schema-valid."""
    chat = ScriptedChatClient(replies=["nope", "still nope"])
    brain: BriefingBrain = brain_cls(chat_client=chat)
    result = brain.compose(briefing_brief, briefing_bundle)
    assert result.fallback_used is True
    assert isinstance(result.state, BriefingState)
    assert result.state.domain_id == domain_id
    assert len(result.state.open_items) == 1
    assert result.state.open_items[0].id == "open_q_fallback"


def test_brain_strips_unresolved_packet_citations(
    briefing_brief: BriefState, briefing_bundle: RetrievalBundle
) -> None:
    """An item citing a packet not in the bundle → dropped + surfaced on state."""
    payload = json.loads(_payload("wireless"))
    payload["scope_items"] = []  # Unused key, ignored by schema (extra=forbid would catch — schema has no scope_items).
    payload["scope_overview"].append({
        "id": "scope_overview_002",
        "statement": "Bogus citation.",
        "supporting_packet_ids": ["pkt_does_not_exist"],
        "supporting_atom_ids": [],
        "confidence": 0.9,
        "metadata": {},
    })
    # Remove the unused junk key (BriefingState has extra=forbid).
    payload.pop("scope_items", None)
    chat = ScriptedChatClient(replies=[json.dumps(payload)])
    brain = WirelessBrain(chat_client=chat)
    result = brain.compose(briefing_brief, briefing_bundle)
    ids = {it.id for it in result.state.scope_overview}
    assert "scope_overview_002" not in ids
    assert "pkt_does_not_exist" in result.unresolved_packet_ids


def test_briefing_item_requires_packet_grounding() -> None:
    from pydantic import ValidationError as PVE

    with pytest.raises(PVE):
        BriefingItem(
            id="x",
            statement="ungrounded",
            supporting_packet_ids=(),
            confidence=0.5,
        )
