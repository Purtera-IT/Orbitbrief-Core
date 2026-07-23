"""Neural + lexical gate for PM-visible fact cards."""
from __future__ import annotations

from orbitbrief_core.pm_handoff.business_labels import classify_fact_category
from orbitbrief_core.pm_handoff.fact_quality import (
    filter_pm_visible_atoms,
    is_lexical_conversation_filler,
    is_marked_conversation_meta,
)
from orbitbrief_core.retrieval.embedder import DeterministicHashEmbedder


def test_lexical_drops_greeting_and_soft_prompt():
    assert is_lexical_conversation_filler("But, Nick, how you doing?")
    assert is_lexical_conversation_filler("I mean, what are your thoughts?")
    assert is_lexical_conversation_filler("So what are your thoughts on that?")
    assert not is_lexical_conversation_filler(
        "Confirm CDW US paper for Montreal sites and who approves the PO."
    )


def test_structured_conversation_meta_flag():
    atom = {
        "atom_type": "deal_metadata",
        "text": "But, Nick, how you doing?",
        "structured": {
            "kind": "conversation_meta",
            "role": "greeting",
            "non_deal": True,
            "head_exclude": True,
        },
    }
    assert is_marked_conversation_meta(atom)


def test_filter_drops_010101_chat_atoms_keeps_commercial():
    atoms = [
        {
            "id": "a1",
            "atom_type": "deal_metadata",
            "text": "I mean, what are your thoughts?",
            "structured": {
                "kind": "conversation_meta",
                "role": "filler",
                "non_deal": True,
                "head_exclude": True,
            },
        },
        {
            "id": "a2",
            "atom_type": "deal_metadata",
            "text": "But, Nick, how you doing?",
            "structured": {
                "kind": "conversation_meta",
                "role": "greeting",
                "non_deal": True,
                "head_exclude": True,
            },
        },
        {
            "id": "a3",
            "atom_type": "deal_metadata",
            "text": (
                "Montreal / Canada sites stay on CDW US paper; confirm who "
                "approves vs defer those sites."
            ),
        },
        {
            "id": "a4",
            "atom_type": "scope_item",
            "text": "Meraki MX devices for SD-WAN install",
        },
        {
            "id": "a5",
            "atom_type": "deal_metadata",
            "text": (
                "They said that they have an SOP that they can send over to us "
                "for the corporate SD-WAN sites."
            ),
            "structured": {
                "kind": "conversation_meta",
                "role": "filler",
                "non_deal": True,
                "head_exclude": True,
                "suppressed_as": "soft_transcript_commitment",
            },
        },
    ]
    kept, meta = filter_pm_visible_atoms(
        atoms, embedder=DeterministicHashEmbedder(dim=256)
    )
    texts = {str(a.get("text")) for a in kept}
    assert "I mean, what are your thoughts?" not in texts
    assert "But, Nick, how you doing?" not in texts
    assert any("CDW US paper" in t for t in texts)
    assert any("Meraki MX" in t for t in texts)
    assert any("SOP" in t for t in texts)
    assert meta["fact_quality_dropped_pre"] >= 2
    assert meta["fact_quality_kept"] >= 3


def test_deal_metadata_not_blanket_commercial():
    assert (
        classify_fact_category("deal_metadata", "But, Nick, how you doing?")
        != "commercial"
    )
    assert (
        classify_fact_category(
            "deal_metadata",
            "Survey charge is a separate per-site fee on the CDW quote.",
        )
        == "commercial"
    )
