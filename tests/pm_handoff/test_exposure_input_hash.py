"""Attribute the generator's run-to-run variance to input or to the model.

The same deal produced 8, 8, 8 then 0 candidates with different questions each
time. `temperature` is ALREADY 0 (OpenAIChatClient defaults it and sends it in
the payload), so "set temperature to 0" is a no-op — the cause is either our
input changing between runs or the hosted model not being deterministic at
temperature 0, which is true of DeepSeek and most hosted MoE serving.

Those need opposite fixes, so the diagnostic hashes what was actually sent.
"""
from __future__ import annotations

from orbitbrief_core.pm_handoff.question_llm import candidates_from_llm

ATOMS = [
    {"id": f"atm_{i}", "atom_type": "rate_card", "text": f"line item {i} at $10"}
    for i in range(5)
]


class _Chat:
    def __init__(self, reply="[]"):
        self.reply = reply
        self.calls = 0

    def complete(self, messages, *, model, **kw):
        self.calls += 1
        return self.reply


def _run(atoms, diag):
    return candidates_from_llm(
        atoms=atoms,
        project_mode="staff_augmentation",
        existing_questions=[],
        chat=_Chat(),
        model="deepseek-chat",
        deal_label="X",
        diagnostics=diag,
    )


def test_identical_input_hashes_identically():
    a, b = {}, {}
    _run(ATOMS, a)
    _run(ATOMS, b)
    assert a["input_sha"] == b["input_sha"]
    assert a["atom_ids_sha"] == b["atom_ids_sha"]


def test_changed_atom_text_changes_the_hash():
    a, b = {}, {}
    _run(ATOMS, a)
    altered = [dict(x) for x in ATOMS]
    altered[0]["text"] = "line item 0 at $99"
    _run(altered, b)
    assert a["input_sha"] != b["input_sha"]
    # same ids, different text — so the id hash must NOT move
    assert a["atom_ids_sha"] == b["atom_ids_sha"]


def test_different_atom_set_changes_both_hashes():
    a, b = {}, {}
    _run(ATOMS, a)
    _run(ATOMS[:3], b)
    assert a["input_sha"] != b["input_sha"]
    assert a["atom_ids_sha"] != b["atom_ids_sha"]
