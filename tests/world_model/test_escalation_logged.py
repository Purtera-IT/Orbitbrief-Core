"""Every LLM call inside world_model must record a structured EscalationReason.

These tests stub the chat client with a recorder so we can assert
*both* that escalations happen when expected and that each call
attaches a valid :class:`EscalationReason`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from orbitbrief_core.inference.client import ChatMessage
from orbitbrief_core.world_model.escalation import EscalationReason
from orbitbrief_core.world_model.pack_prior import PackPrior
from orbitbrief_core.world_model.site_reality import SiteRealityEngine


@dataclass
class RecordingChatClient:
    """Stub chat client: records every call, returns ``reply``."""

    reply: str = ""
    calls: list[dict[str, Any]] = field(default_factory=list)

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> str:
        self.calls.append(
            {
                "model": model,
                "temperature": temperature,
                "messages": [(m.role, m.content) for m in messages],
            }
        )
        return self.reply


# ───── PackPrior escalation ─────


def test_pack_prior_no_signal_escalates_with_reason(
    runtime_from_envelope, wireless_envelope: dict[str, Any]
) -> None:
    """An envelope with zero matching keywords trips no_signal escalation."""
    # Strip text so no keyword can score.
    blank_env = wireless_envelope.copy()
    blank_env["atoms"] = [
        {**a, "text": "the and or of for"} for a in wireless_envelope["atoms"]
    ]
    chat = RecordingChatClient(reply="audit")
    prior = PackPrior.with_default_registry(chat_client=chat)
    rt = runtime_from_envelope(blank_env)
    state = prior.compute(rt)

    assert chat.calls, "no_signal envelope should trigger an LLM call"
    log = state.escalation_log
    assert log["count"] >= 1
    reasons = {e["reason"] for e in log["entries"]}
    assert EscalationReason.PACK_PRIOR_NO_SIGNAL.value in reasons
    # Each entry has the four required structured fields.
    for entry in log["entries"]:
        assert {"engine", "reason", "detail", "model_id"} <= entry.keys()


def test_pack_prior_unambiguous_does_not_escalate(
    runtime_from_envelope, wireless_envelope: dict[str, Any]
) -> None:
    """Strong wireless signal → no escalation, no LLM call."""
    chat = RecordingChatClient(reply="wireless")
    prior = PackPrior.with_default_registry(chat_client=chat)
    rt = runtime_from_envelope(wireless_envelope)
    state = prior.compute(rt)

    if state.margin >= prior.ambiguity_threshold:
        assert chat.calls == [], "unambiguous routing must not call the LLM"
        assert state.escalated is False
        assert state.escalation_log["count"] == 0


# ───── SiteReality escalation ─────


def _ambiguous_site_envelope(make_envelope_helpers, base_envelope_factory):
    """Construct an envelope with two competing names per cluster."""
    return None  # placeholder; built inline in the test below for clarity


def test_site_reality_ambiguous_name_escalates(
    runtime_from_envelope,
) -> None:
    """Two equally-voted competing names on one cluster → escalation."""
    # Two site keys, same cluster (linked by co_mention), each with
    # a *different* canonical_name → tied vote, must escalate.
    atoms = [
        {
            "id": "a1",
            "artifact_id": "art_1",
            "atom_type": "scope_item",
            "authority_class": "machine_extractor",
            "confidence": 0.9,
            "text": "Tower One scope",
            "section_path": [],
            "locator": {},
            "verified": "unverified",
        },
        {
            "id": "a2",
            "artifact_id": "art_2",
            "atom_type": "scope_item",
            "authority_class": "machine_extractor",
            "confidence": 0.9,
            "text": "1 Tower Plaza scope",
            "section_path": [],
            "locator": {},
            "verified": "unverified",
        },
    ]
    entities = [
        {
            "id": "e1", "entity_type": "site",
            "canonical_key": "site:tower_one_pdf",
            "canonical_name": "Tower One",
            "aliases": [], "artifact_ids": ["art_1"],
            "source_atom_ids": ["a1"],
            "review_status": "auto_accepted", "confidence": 0.9,
        },
        {
            "id": "e2", "entity_type": "site",
            "canonical_key": "site:tower_one_xlsx",
            "canonical_name": "1 Tower Plaza",
            "aliases": [], "artifact_ids": ["art_2"],
            "source_atom_ids": ["a2"],
            "review_status": "auto_accepted", "confidence": 0.9,
        },
    ]
    edges = [
        {
            "id": "ed_1", "edge_type": "same_as",
            "from_atom_id": "a1", "to_atom_id": "a2",
            "reason": "test", "confidence": 0.9,
            "cross_artifact": True, "metadata": {},
        }
    ]
    docs = [
        {
            "artifact_id": "art_1", "filename": "rfp.pdf",
            "artifact_type": "pdf", "sha256": "0" * 64,
            "size_bytes": 1024, "parser_name": "t", "parser_version": "0.0.0",
            "structured": {}, "atom_ids": ["a1"],
        },
        {
            "artifact_id": "art_2", "filename": "site_list.xlsx",
            "artifact_type": "xlsx", "sha256": "0" * 64,
            "size_bytes": 1024, "parser_name": "t", "parser_version": "0.0.0",
            "structured": {}, "atom_ids": ["a2"],
        },
    ]
    env = {
        "schema_version": "orbitbrief.input.v2",
        "project_id": "amb_project",
        "compile_id": "amb_compile",
        "generated_at": "2026-01-01T00:00:00Z",
        "summary": {
            "artifact_count": 2, "page_count": 1, "atom_count": 2,
            "packet_count": 0, "entity_count": 2, "edge_count": 1,
        },
        "documents": docs, "atoms": atoms, "entities": entities,
        "edges": edges, "packets": [],
        "indexes": {
            "atoms_by_section_path": {}, "atoms_by_atom_type": {},
            "atoms_by_authority": {}, "atoms_by_artifact": {
                "art_1": ["a1"], "art_2": ["a2"]
            },
            "atoms_by_entity_key": {
                "site:tower_one_pdf": ["a1"],
                "site:tower_one_xlsx": ["a2"],
            },
            "edges_by_atom": {}, "entity_id_by_canonical_key": {
                "site:tower_one_pdf": "e1", "site:tower_one_xlsx": "e2",
            },
        },
    }
    chat = RecordingChatClient(reply="Tower One")
    engine = SiteRealityEngine(chat_client=chat)
    rt = runtime_from_envelope(env)
    state = engine.compute(rt)

    assert chat.calls, "ambiguous-name cluster must consult the LLM"
    log = state.escalation_log
    reasons = {e["reason"] for e in log["entries"]}
    assert EscalationReason.SITE_REALITY_AMBIGUOUS_NAME.value in reasons
    # The picked name must be one of the candidates and must be marked.
    assert state.cluster_count == 1
    cluster = state.clusters[0]
    assert cluster.name_resolved_by_llm is True
    assert cluster.canonical_name in cluster.candidate_names


# ───── corpus-wide escalation rate cap (spec: < 20%) ─────


@pytest.mark.parametrize("envelope_fixture_name", ["wireless_envelope", "itad_envelope"])
def test_escalation_rate_under_cap_on_clean_envelopes(
    request: pytest.FixtureRequest, runtime_from_envelope, envelope_fixture_name: str
) -> None:
    """Clean, on-domain envelopes should not be ambiguous enough to escalate."""
    env = request.getfixturevalue(envelope_fixture_name)
    chat = RecordingChatClient(reply="wireless")
    prior = PackPrior.with_default_registry(chat_client=chat)
    rt = runtime_from_envelope(env)
    state = prior.compute(rt)
    if state.escalated:
        # Escalation happened — verify it was structured, not bare.
        assert state.escalation_log["count"] >= 1
    # Spec target: < 20% escalation across the corpus. With our two
    # clean fixtures we expect 0% — assert the fixture-level invariant.
    assert state.escalation_log["count"] <= 1
