"""Every claim in :class:`BriefState` traces to ≥1 atom (and via the atom, a source_ref).

Phase-4 verify gate: claim grounding is non-empty and resolves in
the runtime. The :class:`Claim` schema enforces non-empty
``supporting_atom_ids`` at validation time; the refiner enforces
that the ids actually resolve in the runtime.
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from orbitbrief_core.world_model.planner import (
    Claim,
    Planner,
    PlannerEscalationReason,
)
from orbitbrief_core.world_model.planner.schema import BriefState
from orbitbrief_core.world_model.refiner import refine_brief

from tests.world_model.planner.conftest import (
    ScriptedChatClient,
    _valid_brief_payload,
)


def test_claim_requires_atom_grounding() -> None:
    """A :class:`Claim` with empty ``supporting_atom_ids`` is rejected at validation."""
    with pytest.raises(ValidationError) as exc:
        Claim(
            id="c0",
            statement="ungrounded claim",
            supporting_atom_ids=(),
            confidence=0.5,
        )
    assert "supporting_atom_ids" in str(exc.value)


def test_planner_claims_resolve_in_runtime(
    substrate_factory, wireless_envelope
) -> None:
    """Every claim's atom ids must resolve to a real atom in the runtime."""
    rt, pp, sr = substrate_factory(wireless_envelope)
    payload = _valid_brief_payload(
        project_id=rt.default_key.project_id,
        compile_id=rt.default_key.compile_id,
        pack_ids=(pp.top_pack_id,),
        cluster_ids=(),
        atom_ids=[a["id"] for a in wireless_envelope["atoms"]],
    )
    chat = ScriptedChatClient(replies=[json.dumps(payload)])
    planner = Planner.with_default_registry(chat_client=chat)
    result = planner.compose(rt, pack_prior=pp, site_reality=sr)
    valid = {a["id"] for a in wireless_envelope["atoms"]}
    for claim in result.state.claims:
        assert claim.supporting_atom_ids, claim.id
        for aid in claim.supporting_atom_ids:
            assert rt.get_atom(aid) is not None, (
                f"claim {claim.id} cites unknown atom {aid}"
            )
            assert aid in valid


def test_refiner_drops_claims_with_unknown_atoms(
    substrate_factory, wireless_envelope
) -> None:
    """If the LLM hallucinates an atom id, the refiner drops the claim."""
    rt, pp, sr = substrate_factory(wireless_envelope)
    real_atoms = [a["id"] for a in wireless_envelope["atoms"]]
    # Mix one good claim + one with a bogus atom id.
    payload = _valid_brief_payload(
        project_id=rt.default_key.project_id,
        compile_id=rt.default_key.compile_id,
        pack_ids=(pp.top_pack_id,),
        cluster_ids=(),
        atom_ids=real_atoms,
    )
    payload["claims"].append(
        {
            "id": "claim_bogus",
            "statement": "fabricated claim",
            "supporting_atom_ids": ["atom_does_not_exist"],
            "supporting_packet_ids": [],
            "confidence": 0.9,
            "pack_id": pp.top_pack_id,
        }
    )
    chat = ScriptedChatClient(replies=[json.dumps(payload)])
    planner = Planner.with_default_registry(chat_client=chat)
    result = planner.compose(rt, pack_prior=pp, site_reality=sr)
    pre_refine_count = len(result.state.claims)
    assert pre_refine_count >= 2
    refined = refine_brief(
        result.state,
        runtime=rt,
        pack_prior=pp,
        site_reality=sr,
    )
    assert any(
        d["claim_id"] == "claim_bogus" for d in refined.dropped_claims
    ), refined.dropped_claims
    # All surviving claims must have resolvable atoms.
    for claim in refined.state.claims:
        for aid in claim.supporting_atom_ids:
            assert rt.get_atom(aid) is not None


def test_refiner_collapses_duplicate_claims(
    substrate_factory, wireless_envelope
) -> None:
    """Same statement + same atom set → one claim survives."""
    rt, pp, sr = substrate_factory(wireless_envelope)
    real_atoms = [a["id"] for a in wireless_envelope["atoms"]]
    payload = _valid_brief_payload(
        project_id=rt.default_key.project_id,
        compile_id=rt.default_key.compile_id,
        pack_ids=(pp.top_pack_id,),
        cluster_ids=(),
        atom_ids=real_atoms,
    )
    # Add a duplicate of the first claim.
    if payload["claims"]:
        payload["claims"].append(
            {
                **payload["claims"][0],
                "id": "claim_dup",
            }
        )
    chat = ScriptedChatClient(replies=[json.dumps(payload)])
    planner = Planner.with_default_registry(chat_client=chat)
    result = planner.compose(rt, pack_prior=pp, site_reality=sr)
    refined = refine_brief(
        result.state,
        runtime=rt,
        pack_prior=pp,
        site_reality=sr,
    )
    assert refined.duplicate_claims_collapsed >= 1
    statements = [c.statement for c in refined.state.claims]
    assert len(statements) == len(set(statements))
