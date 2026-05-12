"""100% schema validity for the managed-services brain.

Phase-5 verify gate: every fixture passing through the brain
produces a schema-valid :class:`ManagedServicesScopeState` and
the post-call validator surfaces unresolved citations rather than
mutating the schema.
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from orbitbrief_core.brains.managed_services import (
    ManagedServicesBrain,
    ManagedServicesScopeState,
    OpenQuestion,
)

from tests.brains.conftest import ScriptedChatClient


def test_handcrafted_payload_validates(valid_brain_payload) -> None:
    """The reference payload round-trips through the schema."""
    state = ManagedServicesScopeState.model_validate_json(valid_brain_payload())
    assert state.scope_items
    assert state.dispatch_readiness_flags
    assert all(f.severity.value in {"green", "yellow", "red"} for f in state.dispatch_readiness_flags)


def test_brain_compose_returns_valid_state(
    msp_brief, msp_bundle, valid_brain_payload
) -> None:
    """Happy path: scripted-LLM returns valid JSON; brain emits typed state."""
    chat = ScriptedChatClient(replies=[valid_brain_payload()])
    brain = ManagedServicesBrain(chat_client=chat)
    result = brain.compose(msp_brief, msp_bundle)
    assert isinstance(result.state, ManagedServicesScopeState)
    assert result.fallback_used is False
    assert result.state.model_used == "qwen3:14b"
    # Provenance was stamped post-call.
    assert result.state.token_cost["total_tokens"] > 0
    # No items were stripped (the payload is fully bundle-grounded).
    assert result.unresolved_packet_ids == ()
    assert result.unresolved_atom_ids == ()


def test_brain_fallback_is_schema_valid(msp_brief, msp_bundle) -> None:
    """When the LLM never returns valid JSON, the deterministic skeleton still validates."""
    chat = ScriptedChatClient(replies=["totally not json", "still not json"])
    brain = ManagedServicesBrain(chat_client=chat)
    result = brain.compose(msp_brief, msp_bundle)
    assert result.fallback_used is True
    assert isinstance(result.state, ManagedServicesScopeState)
    assert result.state.scope_items == ()
    assert len(result.state.open_questions) == 1
    fallback_q = result.state.open_questions[0]
    assert fallback_q.id == "open_q_fallback"
    assert fallback_q.addressee == "brain_admin"


def test_item_requires_packet_grounding() -> None:
    """A grounded item with empty supporting_packet_ids is rejected at validation."""
    with pytest.raises(ValidationError) as exc:
        OpenQuestion(
            id="x",
            statement="ungrounded",
            supporting_packet_ids=(),
            confidence=0.5,
        )
    assert "supporting_packet_ids" in str(exc.value)


def test_brain_strips_unresolved_packet_citations(
    msp_brief, msp_bundle, valid_brain_payload
) -> None:
    """An item citing a packet not in the bundle is dropped; id surfaces in unresolved."""
    payload = json.loads(valid_brain_payload())
    payload["scope_items"].append(
        {
            "id": "scope_bogus",
            "statement": "bogus scope citing a nonexistent packet",
            "supporting_packet_ids": ["pkt_does_not_exist"],
            "supporting_atom_ids": [],
            "confidence": 0.9,
            "category": "phantom",
        }
    )
    chat = ScriptedChatClient(replies=[json.dumps(payload)])
    brain = ManagedServicesBrain(chat_client=chat)
    result = brain.compose(msp_brief, msp_bundle)
    ids_in_state = {it.id for it in result.state.scope_items}
    assert "scope_bogus" not in ids_in_state
    assert "pkt_does_not_exist" in result.unresolved_packet_ids


def test_brain_drops_atom_citations_not_in_packet(
    msp_brief, msp_bundle, valid_brain_payload
) -> None:
    """An item citing a real packet but a foreign atom keeps the item, drops the bad atom."""
    payload = json.loads(valid_brain_payload())
    payload["scope_items"][0]["supporting_atom_ids"] = ["a_scope_1", "a_alien_atom"]
    chat = ScriptedChatClient(replies=[json.dumps(payload)])
    brain = ManagedServicesBrain(chat_client=chat)
    result = brain.compose(msp_brief, msp_bundle)
    surviving_atoms = result.state.scope_items[0].supporting_atom_ids
    assert "a_scope_1" in surviving_atoms
    assert "a_alien_atom" not in surviving_atoms
    assert "a_alien_atom" in result.unresolved_atom_ids
