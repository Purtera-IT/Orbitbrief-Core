"""Quality gate for the exec-summary neural head.

Proves the production-safety contract: no-op when the flag is off, never ships a
degenerate headline, generates the right shape when wired, and survives bad model
output. Pure unit test — no network, no model download.
"""
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest


@dataclass
class FakeHandoff:
    gaps: list = field(default_factory=list)
    executive_summary: dict = field(default_factory=dict)


class FakeChat:
    def __init__(self, text):
        self._t = text

    def complete_with_usage(self, messages, **kw):
        return SimpleNamespace(text=self._t)


ENV = {
    "service_routing": {"primary": "audio_visual"},
    "project_vitals": {"score_100": 55.9, "band": "orange"},
    "sow_readiness_scorecard": {"readiness_score": 0.667, "grade": "almost_ready"},
    "pm_dashboard": {"money_summary": {"total": 134912.0}},
}


def test_noop_when_flag_off(monkeypatch):
    monkeypatch.delenv("ORBITBRIEF_NEURAL_HEADS", raising=False)
    from orbitbrief_core.neural_heads import apply_neural_heads
    h = FakeHandoff()
    assert apply_neural_heads(h, ENV, chat_client=FakeChat("{}")) is h  # untouched


def test_no_client_is_noop():
    from orbitbrief_core.neural_heads.exec_summary import apply_exec_summary
    h = FakeHandoff(gaps=[{"severity": "blocker", "label": "x"}])
    assert apply_exec_summary(h, ENV, chat_client=None) is h


def test_generates_grounded(monkeypatch):
    monkeypatch.setenv("ORBITBRIEF_NEURAL_HEADS", "1")
    from orbitbrief_core.neural_heads import apply_neural_heads
    h = FakeHandoff(gaps=[{"severity": "blocker", "label": "Wall scope conflict"}])
    chat = FakeChat('{"headline":"Audio Visual deal $134,912, almost ready with 1 blocker",'
                    '"health_line":"Wall scope conflict is the top risk.",'
                    '"next_action":"Clarify wall scope with customer."}')
    out = apply_neural_heads(h, ENV, chat_client=chat)
    es = out.executive_summary
    assert es["headline"].startswith("Audio Visual deal $134,912")
    assert es["next_action"] == "Clarify wall scope with customer."
    assert es["source"] == "neural_heads.exec_summary"


def test_safe_fallback_on_bad_json(monkeypatch):
    monkeypatch.setenv("ORBITBRIEF_NEURAL_HEADS", "1")
    from orbitbrief_core.neural_heads import apply_neural_heads
    h = FakeHandoff(gaps=[{"severity": "blocker", "label": "x"}])
    out = apply_neural_heads(h, ENV, chat_client=FakeChat("garbage, no json here"))
    hl = out.executive_summary["headline"]
    assert hl and "deal across no confirmed" not in hl  # never degenerate
    assert "$134,912" in hl                               # safe fallback uses real facts


def test_never_leaks_internal_jargon(monkeypatch):
    monkeypatch.setenv("ORBITBRIEF_NEURAL_HEADS", "1")
    from orbitbrief_core.neural_heads import apply_neural_heads
    h = FakeHandoff(gaps=[])
    out = apply_neural_heads(h, ENV, chat_client=FakeChat("not json"))  # forces fallback
    hl = out.executive_summary["headline"].lower()
    assert "atoms" not in hl and "packets" not in hl and "uuid" not in hl
