"""Per-engagement token cost telemetry; default tier under budget.

Phase-4 verify gate: every BriefState carries a ``token_cost``
dict (prompt/completion/total/latency) and the default-tier total
sits under a configured budget. We use the scripted chat client's
fixed 600-token usage as a stand-in for the real LLM accounting
so the test stays fast and deterministic.
"""
from __future__ import annotations

import json

from orbitbrief_core.inference.client import ChatUsage
from orbitbrief_core.world_model.planner import Planner

from tests.world_model.planner.conftest import (
    ScriptedChatClient,
    _valid_brief_payload,
)


# Default-tier budget per engagement. Tune as you scale; the
# scripted fixture uses 600 tokens which sits well below this.
DEFAULT_TIER_TOKEN_BUDGET = 8000


def test_state_carries_token_cost(substrate_factory, wireless_envelope) -> None:
    """Every successful compose() call returns token_cost with the four standard fields."""
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

    cost = result.state.token_cost
    assert {"prompt_tokens", "completion_tokens", "total_tokens", "latency_ms"} <= cost.keys()
    assert cost["total_tokens"] > 0
    assert cost["total_tokens"] == result.usage.total_tokens


def test_default_tier_under_budget(substrate_factory, wireless_envelope) -> None:
    """Default-tier (qwen3:14b) compose stays under the per-engagement budget."""
    rt, pp, sr = substrate_factory(wireless_envelope)
    payload = _valid_brief_payload(
        project_id=rt.default_key.project_id,
        compile_id=rt.default_key.compile_id,
        pack_ids=(pp.top_pack_id,),
        cluster_ids=(),
        atom_ids=[a["id"] for a in wireless_envelope["atoms"]],
    )
    chat = ScriptedChatClient(
        replies=[json.dumps(payload)],
        fixed_usage=ChatUsage(
            prompt_tokens=2400, completion_tokens=600, total_tokens=3000, latency_ms=1200
        ),
    )
    planner = Planner.with_default_registry(chat_client=chat)
    result = planner.compose(rt, pack_prior=pp, site_reality=sr)
    assert result.escalation.tier.value == "default"
    assert result.state.token_cost["total_tokens"] < DEFAULT_TIER_TOKEN_BUDGET


def test_retry_accumulates_token_cost(substrate_factory, wireless_envelope) -> None:
    """When the planner retries, token_cost is the sum across attempts."""
    rt, pp, sr = substrate_factory(wireless_envelope)
    bad = "this is not json"
    good = json.dumps(
        _valid_brief_payload(
            project_id=rt.default_key.project_id,
            compile_id=rt.default_key.compile_id,
            pack_ids=(pp.top_pack_id,),
            cluster_ids=(),
            atom_ids=[a["id"] for a in wireless_envelope["atoms"]],
        )
    )
    fixed = ChatUsage(
        prompt_tokens=500, completion_tokens=100, total_tokens=600, latency_ms=200
    )
    chat = ScriptedChatClient(replies=[bad, good], fixed_usage=fixed)
    planner = Planner.with_default_registry(chat_client=chat)
    result = planner.compose(rt, pack_prior=pp, site_reality=sr)
    assert len(chat.call_log) == 2
    assert result.state.token_cost["total_tokens"] == 1200
    assert result.state.token_cost["prompt_tokens"] == 1000
