"""Every fixture must produce a schema-valid :class:`BriefState`.

Phase-4 verify gate: failures are 0.

Three layers exercised:

* Direct Pydantic validation of a hand-built payload.
* Planner.compose() with a scripted chat client returning a valid
  payload — the runner must stamp provenance and return a typed
  :class:`BriefState`.
* Planner fallback path (LLM returns garbage twice) — the
  deterministic skeleton must still validate against the schema.
"""
from __future__ import annotations

import json

import pytest

from orbitbrief_core.world_model.pack_prior import PackPrior
from orbitbrief_core.world_model.planner import BriefState, Planner
from orbitbrief_core.world_model.site_reality import SiteRealityEngine

from tests.world_model.planner.conftest import (
    ScriptedChatClient,
    _valid_brief_payload,
)


def test_handcrafted_payload_validates(wireless_envelope) -> None:
    """The reference fixture round-trips through :class:`BriefState` validation."""
    env = wireless_envelope
    payload = _valid_brief_payload(
        project_id=env["project_id"],
        compile_id=env["compile_id"],
        pack_ids=("wireless",),
        cluster_ids=(),
        atom_ids=[a["id"] for a in env["atoms"]],
    )
    state = BriefState.model_validate(payload)
    assert state.project_id == env["project_id"]
    assert len(state.claims) == len(env["atoms"])


def test_planner_compose_returns_valid_brief(
    substrate_factory, wireless_envelope
) -> None:
    """When the LLM returns valid JSON, the planner emits a typed :class:`BriefState`."""
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
    assert isinstance(result.state, BriefState)
    assert result.fallback_used is False
    # Provenance was stamped by the runner, not the LLM.
    assert result.state.model_used == "qwen3:14b"
    assert result.state.tier == "default"
    assert result.state.token_cost["total_tokens"] > 0


def test_planner_fallback_payload_validates(
    substrate_factory, wireless_envelope
) -> None:
    """When LLM returns garbage, the fallback :class:`BriefState` still validates."""
    rt, pp, sr = substrate_factory(wireless_envelope)
    chat = ScriptedChatClient(replies=["this is not json", "still not json"])
    planner = Planner.with_default_registry(chat_client=chat)
    result = planner.compose(rt, pack_prior=pp, site_reality=sr)
    # Both attempts consumed → fallback used.
    assert result.fallback_used is True
    assert isinstance(result.state, BriefState)
    # Skeleton has no claims but at least one BLOCKER review flag.
    assert result.state.claims == ()
    assert any(f.severity.value == "blocker" for f in result.state.review_flags)


def test_planner_retries_once_on_validation_error(
    substrate_factory, wireless_envelope
) -> None:
    """Invalid JSON → planner re-prompts with the validation message; second reply wins."""
    rt, pp, sr = substrate_factory(wireless_envelope)
    bad = json.dumps({"project_id": "x", "compile_id": "y"})
    good_payload = _valid_brief_payload(
        project_id=rt.default_key.project_id,
        compile_id=rt.default_key.compile_id,
        pack_ids=(pp.top_pack_id,),
        cluster_ids=(),
        atom_ids=[a["id"] for a in wireless_envelope["atoms"]],
    )
    chat = ScriptedChatClient(replies=[bad, json.dumps(good_payload)])
    planner = Planner.with_default_registry(chat_client=chat)
    result = planner.compose(rt, pack_prior=pp, site_reality=sr)
    assert result.fallback_used is False
    assert isinstance(result.state, BriefState)
    # Two LLM calls — first failed validation, second succeeded.
    assert len(chat.call_log) == 2
