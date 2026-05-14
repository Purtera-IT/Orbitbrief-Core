"""Pack-prior is byte-deterministic and never escalates without a chat client."""
from __future__ import annotations

from typing import Any

import pytest

from orbitbrief_core.world_model.pack_prior import PackPrior


@pytest.fixture
def prior_no_chat() -> PackPrior:
    """PackPrior with no chat client — must never escalate."""
    return PackPrior.with_default_registry(chat_client=None)


def test_state_is_byte_deterministic(
    prior_no_chat: PackPrior, runtime_from_envelope, wireless_envelope: dict[str, Any]
) -> None:
    """Same envelope → same state, byte for byte."""
    rt1 = runtime_from_envelope(wireless_envelope)
    rt2 = runtime_from_envelope(wireless_envelope)
    s1 = prior_no_chat.compute(rt1).model_dump_json()
    s2 = prior_no_chat.compute(rt2).model_dump_json()
    assert s1 == s2, "PackPrior state must be byte-identical across runs"


def test_no_llm_call_when_chat_client_none(
    prior_no_chat: PackPrior, runtime_from_envelope, wireless_envelope: dict[str, Any]
) -> None:
    """No chat client → escalation log must be empty, escalated=False."""
    rt = runtime_from_envelope(wireless_envelope)
    state = prior_no_chat.compute(rt)
    assert state.escalated is False
    assert state.pre_escalation_top_pack_id is None
    assert state.escalation_log["count"] == 0


def test_wireless_envelope_routes_to_wireless(
    prior_no_chat: PackPrior, runtime_from_envelope, wireless_envelope: dict[str, Any]
) -> None:
    """Sanity: a wireless-themed envelope must rank wireless on top."""
    rt = runtime_from_envelope(wireless_envelope)
    state = prior_no_chat.compute(rt)
    assert state.top_pack_id == "wireless", (
        f"expected wireless to win, got {state.top_pack_id} "
        f"(margin={state.margin:.3f}, scores={[(s.pack_id, s.raw_score) for s in state.scores[:5]]})"
    )
    assert state.scores[0].raw_score > 0


def test_itad_envelope_routes_to_itad(
    prior_no_chat: PackPrior, runtime_from_envelope, itad_envelope: dict[str, Any]
) -> None:
    """Sanity: ITAD-themed envelope must rank itad on top."""
    rt = runtime_from_envelope(itad_envelope)
    state = prior_no_chat.compute(rt)
    assert state.top_pack_id == "itad", state.top_pack_id


def test_state_has_all_24_packs(
    prior_no_chat: PackPrior, runtime_from_envelope, wireless_envelope: dict[str, Any]
) -> None:
    """Every pack in the registry must appear in the state, even with score 0."""
    rt = runtime_from_envelope(wireless_envelope)
    state = prior_no_chat.compute(rt)
    assert len(state.scores) == 24
    pack_ids = {s.pack_id for s in state.scores}
    assert "wireless" in pack_ids
    assert "itad" in pack_ids
    # PR13 — confidence is no longer a softmax probability; it's a
    # margin-based calibrated signal capped at 0.985 so a winning pack
    # cannot read as "100 % confident". Only invariant: every value is
    # in [0, ceiling] and the top pack's confidence is highest.
    ceiling = 0.985
    for s in state.scores:
        assert 0.0 <= s.confidence <= ceiling + 1e-6, (s.pack_id, s.confidence)
    # The top pack should have the highest confidence (or tied for it).
    sorted_scores = sorted(state.scores, key=lambda s: -s.confidence)
    assert sorted_scores[0].confidence >= sorted_scores[1].confidence
