"""One routing answer, resolved from a ladder, that can never be worse than none.

The system already had two routers disagreeing and the third one winning. This
component exists to collapse that into a single decision, so the tests are
mostly about what it REFUSES to do: never invent a pack, never override on a
weak signal, never let a dead endpoint fail a compile.
"""
from __future__ import annotations

import pytest

from orbitbrief_core.world_model.scope_router import (
    classify_scope,
    resolve_routing,
)

PACKS = [
    ("staff_augmentation", "Staff augmentation"),
    ("wireless", "Wireless / WLAN"),
    ("low_voltage_cabling", "Low-voltage cabling"),
    ("audio_visual", "Audio visual"),
    ("datacenter", "Datacenter"),
]
CLAYTON = (
    "FILES: Clayton_Dispatch_Readiness | Exhibit A - Retail Locations\n"
    "SCOPE ATOMS:\n- Onsite technician dispatch to 437 retail stores\n"
    "- Collect store SSID and wifi credentials on arrival"
)


class _Chat:
    def __init__(self, reply, boom=False):
        self.reply, self.boom, self.calls = reply, boom, 0

    def complete(self, messages, *, model, **kwargs):
        self.calls += 1
        if self.boom:
            raise RuntimeError("connection refused")
        return self.reply


# ── the LLM path ─────────────────────────────────────────────────────────

def test_the_model_decides_the_pack():
    d = classify_scope(scope_summary=CLAYTON, packs=PACKS,
                       chat=_Chat("staff_augmentation"), model="deepseek-chat")
    assert d is not None and d.primary == "staff_augmentation"
    assert d.source == "llm_scope_router"


@pytest.mark.parametrize("reply", [
    "staff_augmentation",
    "  staff_augmentation\n",
    "The primary pack is staff_augmentation.",
    "```\nstaff_augmentation\n```",
    "<think>the deal dispatches techs</think> staff_augmentation",
])
def test_the_reply_is_read_through_whatever_padding_the_model_adds(reply):
    d = classify_scope(scope_summary=CLAYTON, packs=PACKS,
                       chat=_Chat(reply), model="m")
    assert d is not None and d.primary == "staff_augmentation"


def test_a_pack_that_does_not_exist_is_not_invented():
    assert classify_scope(scope_summary=CLAYTON, packs=PACKS,
                          chat=_Chat("banana_farming"), model="m") is None


def test_a_dead_endpoint_never_fails_the_compile():
    assert classify_scope(scope_summary=CLAYTON, packs=PACKS,
                          chat=_Chat("", boom=True), model="m") is None


def test_no_client_means_no_call():
    chat = _Chat("wireless")
    assert classify_scope(scope_summary=CLAYTON, packs=PACKS, chat=None, model="m") is None
    assert chat.calls == 0


# ── the ladder ───────────────────────────────────────────────────────────

def test_the_model_outranks_a_confident_head():
    """Clayton exactly: the head says wireless at 0.8, the model says dispatch."""
    out = resolve_routing(
        envelope_routing={"primary": "wireless", "confidence": 0.8},
        scope_summary=CLAYTON, packs=PACKS,
        chat=_Chat("staff_augmentation"), model="deepseek-chat",
    )
    assert out["primary"] == "staff_augmentation"
    assert out["source"] == "llm_scope_router"


def test_the_head_is_used_when_there_is_no_model():
    out = resolve_routing(
        envelope_routing={"primary": "wireless", "confidence": 0.9},
        scope_summary=CLAYTON, packs=PACKS, chat=None, model="",
    )
    assert out["primary"] == "wireless"


def test_a_weak_head_is_not_worth_overriding_evidence_for():
    """0.529 held-out means a sub-threshold head is noise. Empty result =
    the keyword cascade decides, exactly as it does today."""
    assert resolve_routing(
        envelope_routing={"primary": "wireless", "confidence": 0.55},
        scope_summary=CLAYTON, packs=PACKS,
    ) == {}


def test_an_abstaining_head_is_respected():
    assert resolve_routing(
        envelope_routing={"primary": "wireless", "confidence": 0.99, "abstained": True},
        scope_summary=CLAYTON, packs=PACKS,
    ) == {}


def test_no_routing_at_all_is_a_valid_answer():
    assert resolve_routing(envelope_routing=None, scope_summary=CLAYTON, packs=PACKS) == {}
    assert resolve_routing(envelope_routing={}, scope_summary="", packs=PACKS) == {}


def test_a_dead_model_falls_back_to_the_head_rather_than_to_nothing():
    out = resolve_routing(
        envelope_routing={"primary": "wireless", "confidence": 0.9},
        scope_summary=CLAYTON, packs=PACKS,
        chat=_Chat("", boom=True), model="deepseek-chat",
    )
    assert out["primary"] == "wireless"


def test_the_emitted_shape_is_the_one_downstream_already_reads():
    out = resolve_routing(
        envelope_routing=None, scope_summary=CLAYTON, packs=PACKS,
        chat=_Chat("audio_visual"), model="m",
    )
    for field in ("enabled", "primary", "secondary", "confidence", "source", "abstained"):
        assert field in out
