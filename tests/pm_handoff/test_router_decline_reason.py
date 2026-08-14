"""A declined router rung must say why.

The LLM rung decided `staff_augmentation` for 02557291 on one run and declined
on the next, with identical inputs. Nothing recorded the difference: it logs at
warning level into a stream dominated by Azure SDK chatter, and the artifact
carried only the outcome. #54 stopped the distrusted head from winning on a
decline; this makes the decline itself legible.
"""
from __future__ import annotations

from orbitbrief_core.pm_handoff.question_engine import _routing_provenance
from orbitbrief_core.world_model.scope_router import classify_scope, resolve_routing

PACKS = [("wireless", "Wireless"), ("staff_augmentation", "Staff augmentation")]


class _Boom:
    def complete(self, messages, *, model, **kw):
        raise TimeoutError("read timed out")


class _Garbage:
    def complete(self, messages, *, model, **kw):
        return "I think this is probably a networking job of some kind."


class _Good:
    def complete(self, messages, *, model, **kw):
        return "staff_augmentation"


def test_timeout_is_named():
    d: dict = {}
    assert classify_scope(scope_summary="dispatch techs", packs=PACKS,
                          chat=_Boom(), model="m", diagnostics=d) is None
    assert d["llm_rung"] == "error"
    assert "TimeoutError" in d["reason"]


def test_unparseable_reply_keeps_a_sample():
    d: dict = {}
    assert classify_scope(scope_summary="dispatch techs", packs=PACKS,
                          chat=_Garbage(), model="m", diagnostics=d) is None
    assert d["llm_rung"] == "unparseable"
    assert "networking job" in d["sample_reply"]


def test_empty_scope_summary_is_distinguished_from_a_failure():
    d: dict = {}
    classify_scope(scope_summary="   ", packs=PACKS, chat=_Good(), model="m", diagnostics=d)
    assert d["reason"] == "empty_scope_summary"


def test_success_records_the_choice():
    d: dict = {}
    out = classify_scope(scope_summary="dispatch techs", packs=PACKS,
                         chat=_Good(), model="m", diagnostics=d)
    assert out is not None and d["llm_rung"] == "decided" and d["chose"] == "staff_augmentation"


def test_resolve_records_which_rung_answered():
    d: dict = {}
    out = resolve_routing(envelope_routing={"primary": "wireless", "confidence": 0.8},
                          scope_summary="dispatch techs", packs=PACKS,
                          chat=_Good(), model="m", diagnostics=d)
    assert out["primary"] == "staff_augmentation"
    assert d["rung"] == "llm"


def test_decline_records_the_head_it_refused():
    d: dict = {}
    out = resolve_routing(envelope_routing={"primary": "wireless", "confidence": 0.8},
                          scope_summary="dispatch techs", packs=PACKS,
                          chat=_Boom(), model="m", diagnostics=d)
    assert out == {}
    assert d["rung"] == "none"
    assert d["head_primary"] == "wireless"
    assert d["llm_rung"] == "error"


def test_reason_survives_when_the_answer_is_discarded():
    """The decline drops service_routing, so the reason must live elsewhere."""
    prov = _routing_provenance({}, {"rung": "none", "llm_rung": "error",
                                    "reason": "TimeoutError: read timed out"})
    assert prov["decided"] is False
    assert prov["diagnostics"]["llm_rung"] == "error"
