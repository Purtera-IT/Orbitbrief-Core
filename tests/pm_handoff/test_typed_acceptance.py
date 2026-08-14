"""Acceptance criteria stated as prose must reach the PM — QA rows must not.

build_acceptance_checks only read structured spreadsheet cells, so it found
criteria ONLY when they arrived as a table with an exit_criteria column. Prose
criteria — how most SOWs state them — were typed `acceptance_criterion` by the
parser and dropped, leaving the handoff field and the SOW section empty on every
deal audited 2026-08-13.

Switching it on naively is worse than leaving it off: one real deal's 13
`acceptance_criterion` atoms were a Dispatch_Readiness workbook's QA_Checks
sheet validating its own import, and another's was a signature block.
"""
from __future__ import annotations

from orbitbrief_core.pm_handoff.reconciliation import build_acceptance_checks


def _report(atoms):
    return {"artifacts": [{"artifact_id": "art_1", "filename": "SOW.pdf", "atoms": atoms}]}


REAL = {
    "id": "a1", "atom_type": "acceptance_criterion",
    "section_path": ["ACCEPTANCE CRITERIA"],
    "text": "Each site is accepted when all APs report to the controller and a "
            "post-install signal survey shows -67 dBm or better in all covered areas.",
}
QA_ROW = {
    "id": "a2", "atom_type": "acceptance_criterion",
    "section_path": ["QA_Checks"],
    "text": "Pending rows with valid HC imported | PASS | 428 | Expected 428 valid "
            "HC rows after excluding malformed/non-site rows",
}
SIGNATURE = {
    "id": "a3", "atom_type": "acceptance_criterion",
    "section_path": ["ACCEPTANCE CRITERIA"],
    "text": "By Customer signature below, Customer accepts this SOW as issued by "
            "PurTera and agrees to the terms, provisions and conditions.",
}


def test_prose_criterion_now_reaches_the_pm():
    out = build_acceptance_checks(_report([REAL]))
    assert len(out) == 1
    assert "-67 dBm" in out[0].criterion


def test_internal_qa_rows_are_excluded():
    out = build_acceptance_checks(_report([QA_ROW]))
    assert out == [], "parser QA of its own import must never read as acceptance"


def test_signature_block_is_excluded():
    out = build_acceptance_checks(_report([SIGNATURE]))
    assert out == [], "a signature block is a formality, not a testable criterion"


def test_mixed_input_keeps_only_the_real_one():
    out = build_acceptance_checks(_report([QA_ROW, REAL, SIGNATURE]))
    assert len(out) == 1 and "-67 dBm" in out[0].criterion


def test_structured_rows_still_work():
    """The original path must be untouched."""
    atom = {
        "id": "s1", "atom_type": "schedule_row",
        "structured": {"canonical_cells": {
            "name": "Cutover", "exit_criteria": "All circuits pass BERT",
            "owner": "PurTera"}},
    }
    out = build_acceptance_checks(_report([atom]))
    assert len(out) == 1 and "BERT" in out[0].criterion


def test_duplicate_prose_is_collapsed():
    out = build_acceptance_checks(_report([REAL, dict(REAL, id="a9")]))
    assert len(out) == 1
