"""Core must be able to route even when the parser did not record its input.

Measured 2026-08-14: two of three deals had NO `scope_summary` key on
envelope.service_routing, because the deployed worker bundles a parser ref
without cd6a6d1. The LLM rung recorded `skipped / empty_scope_summary` and never
ran; #54 then correctly drops the distrusted head, and the keyword cascade
decided — a structured-cabling deal came out `wireless_install`.
"""
from __future__ import annotations

from orbitbrief_core.pm_handoff.builder import _derive_scope_summary

ATOMS = [
    {"id": f"p{i}", "atom_type": "pricing_assumption", "text": f"Line item {i} at $10 each"}
    for i in range(60)
] + [
    {"id": "s1", "atom_type": "scope_item",
     "text": "Install 300ft CAT6a plenum cable from IDF to each drop location."},
    {"id": "s2", "atom_type": "scope_item",
     "text": "Terminate and test every drop to TIA-568 and provide certification results."},
    {"id": "x1", "atom_type": "exclusion",
     "text": "Pathway, conduit and drywall patching are excluded."},
]
ENV = {"documents": [{"filename": "B704 Premise Wiring proposal.pdf"}], "atoms": ATOMS}


def test_a_summary_is_produced():
    s = _derive_scope_summary(ENV)
    assert len(s) > 100


def test_filenames_lead_because_they_often_name_the_service():
    s = _derive_scope_summary(ENV)
    assert s.startswith("FILES:") and "Premise Wiring" in s


def test_scope_bearing_atoms_beat_pricing_noise():
    """60 pricing lines vs 3 scope atoms — the scope must survive."""
    s = _derive_scope_summary(ENV)
    assert "CAT6a plenum" in s
    assert "TIA-568" in s


def test_artifacts_spelling_also_works():
    env = {"artifacts": [{"filename": "AP Swap.xlsx"}], "atoms": ATOMS}
    assert "AP Swap" in _derive_scope_summary(env)


def test_empty_envelope_yields_empty_not_an_error():
    assert _derive_scope_summary({}) == ""
    assert _derive_scope_summary({"atoms": []}) == ""
    assert _derive_scope_summary(None) == ""


def test_output_is_bounded():
    big = {"documents": [], "atoms": [
        {"id": str(i), "atom_type": "scope_item", "text": "x" * 500} for i in range(500)
    ]}
    assert len(_derive_scope_summary(big)) <= 8000
