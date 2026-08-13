"""An unchanged deal must produce the same exposure questions.

Measured: two back-to-back runs on an unchanged deal sent a byte-identical
prompt (input_sha 86281b59e5cca1d0 both times) and returned three entirely
DISJOINT questions. temperature is already 0; DeepSeek is a hosted MoE and does
not promise determinism at temperature 0.

The PM cost is real -- a brief that changes when the deal did not, and
correction feedback bound to rule_ids that may never reappear.
"""
from __future__ import annotations

import json

import pytest

from orbitbrief_core.pm_handoff.question_llm import candidates_from_llm

ATOMS = [
    {"id": f"atm_{i}", "atom_type": "rate_card", "text": f"cancellation fee tier {i}: $100"}
    for i in range(6)
]

REPLY_A = json.dumps([
    {"question": "Who absorbs the cost of an aborted site visit on this deal?",
     "label": "Aborted visit", "why": "cost", "severity": "warning", "atom_ids": ["E1"]}
])
REPLY_B = json.dumps([
    {"question": "What triggers the travel surcharge across the site footprint?",
     "label": "Travel surcharge", "why": "cost", "severity": "warning", "atom_ids": ["E1"]}
])


class _Chat:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = 0

    def complete(self, messages, *, model, **kw):
        self.calls += 1
        return self.replies[min(self.calls - 1, len(self.replies) - 1)]


def _run(chat, tmp_path, diag=None):
    return candidates_from_llm(
        atoms=ATOMS, project_mode="staff_augmentation", existing_questions=[],
        chat=chat, model="deepseek-chat", deal_label="D",
        diagnostics=diag if diag is not None else {}, case_dir=tmp_path,
    )


def test_unchanged_deal_returns_the_same_questions(tmp_path):
    """The whole point: a flip-flopping model must not flip the brief."""
    chat = _Chat(REPLY_A, REPLY_B)  # model would answer differently the 2nd time
    first = _run(chat, tmp_path)
    second = _run(chat, tmp_path)
    assert [c.suggested_open_question for c in first] == [
        c.suggested_open_question for c in second
    ]
    assert chat.calls == 1, "second run must not call the model at all"


def test_cache_hit_is_reported(tmp_path):
    chat = _Chat(REPLY_A)
    d1, d2 = {}, {}
    _run(chat, tmp_path, d1)
    _run(chat, tmp_path, d2)
    assert d1["cache"] == "miss"
    assert d2["cache"] == "hit"


def test_changed_deal_regenerates(tmp_path):
    chat = _Chat(REPLY_A, REPLY_B)
    _run(chat, tmp_path)
    changed = [dict(a) for a in ATOMS]
    changed[0]["text"] = "cancellation fee tier 0: $500"   # deal actually changed
    out = candidates_from_llm(
        atoms=changed, project_mode="staff_augmentation", existing_questions=[],
        chat=chat, model="deepseek-chat", deal_label="D",
        diagnostics={}, case_dir=tmp_path,
    )
    assert chat.calls == 2, "changed atoms must re-ask the model"
    assert "travel surcharge" in out[0].suggested_open_question.lower()


def test_an_empty_answer_is_never_frozen(tmp_path):
    """One run returned []. Caching that would pin an empty brief indefinitely."""
    chat = _Chat("[]", REPLY_A)
    assert _run(chat, tmp_path) == []
    second = _run(chat, tmp_path)
    assert chat.calls == 2, "an empty result must not be served from cache"
    assert len(second) == 1


def test_cache_can_be_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("ORBITBRIEF_EXPOSURE_CACHE", "0")
    chat = _Chat(REPLY_A, REPLY_B)
    _run(chat, tmp_path)
    _run(chat, tmp_path)
    assert chat.calls == 2


def test_corrupt_cache_file_does_not_break_the_compile(tmp_path):
    (tmp_path / ".orbitbrief_exposure_cache.json").write_text("{not json", encoding="utf-8")
    chat = _Chat(REPLY_A)
    out = _run(chat, tmp_path)
    assert len(out) == 1
