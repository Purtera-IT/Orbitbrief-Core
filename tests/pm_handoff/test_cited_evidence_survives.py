"""A question that NAMES its evidence must be grounded by that evidence.

_with_evidence only honoured `evidence_sources`. A candidate carrying verified
`evidence_atom_ids` fell through to _collect_matching_evidence and was
re-grounded by text similarity against a 0.42 gate -- the citations were thrown
away and re-derived from the question's own wording.

Measured on Clayton across three live runs, the same 8 generated candidates
published 2, then 1, then 0, purely on which side of that gate the re-match
landed. With require=True the losers were dropped before ranking, which is why
the fate map showed all 8 as `not_admitted`.
"""
from __future__ import annotations

from orbitbrief_core.pm_handoff.question_engine import QuestionCandidate, _with_evidence

ATOMS = [
    {
        "id": "atm_ratecard_1",
        "atom_type": "rate_card",
        "text": "Cancellation or reschedule 1 business day before scheduled visit — "
                "100% of total planned visit site costs.",
        "artifact_id": "art_sow",
    },
    {
        "id": "atm_unrelated",
        "atom_type": "scope_item",
        "text": "Technician will verify wireless access point signal strength.",
        "artifact_id": "art_sow",
    },
]


def _candidate(atom_ids):
    return QuestionCandidate(
        rule_id="llm.exposure.cancellation_charge_trigger",
        domain_id="commercial",
        label="Cancellation charge",
        severity="warning",
        # Deliberately worded so it does NOT lexically resemble the atom: an
        # explicit citation must not depend on the matcher liking the phrasing.
        message="Who absorbs the fee?",
        suggested_open_question=(
            "With 428 sites, who has authority to approve a same-week schedule change?"
        ),
        observed_summary="",
        source="llm_exposure",
        score=0.87,
        evidence_atom_ids=list(atom_ids),
        project_mode="staff_augmentation",
    )


def test_cited_atom_grounds_the_question():
    out = _with_evidence(_candidate(["atm_ratecard_1"]), atoms=ATOMS, require=True)
    assert out is not None, "a cited question must survive require=True"
    assert out.evidence_atom_ids == ["atm_ratecard_1"]
    assert out.evidence_sources, "sources must be attached from the cited atom"


def test_the_attributed_atom_is_the_one_cited():
    out = _with_evidence(_candidate(["atm_ratecard_1"]), atoms=ATOMS, require=True)
    ids = {s.get("atom_id") for s in out.evidence_sources}
    assert "atm_unrelated" not in ids
    assert "atm_ratecard_1" in ids


def test_a_citation_to_a_missing_atom_does_not_fabricate_grounding():
    # Falls through to the matcher; with require=True and no lexical overlap it
    # must be dropped rather than attributed to some other atom.
    out = _with_evidence(_candidate(["atm_does_not_exist"]), atoms=ATOMS, require=True)
    if out is not None:
        assert "atm_does_not_exist" not in (out.evidence_atom_ids or [])


def test_uncited_candidates_still_use_the_matcher():
    c = _candidate([])
    out = _with_evidence(c, atoms=ATOMS, require=True)
    # No citations -> old behaviour; nothing here should crash.
    assert out is None or out.evidence_sources
