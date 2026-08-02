"""Claim polish + display label for PM fact cards / headlines."""
from __future__ import annotations

from orbitbrief_core.pm_handoff.fact_quality import (
    display_case_label,
    polish_fact_claim,
)


def test_drop_open_questions_as_facts():
    assert polish_fact_claim("Do you have a copy of their SOP by chance?") is None
    assert polish_fact_claim("Who do you get approval from?") is None


def test_rewrite_change_order_survey():
    claim = polish_fact_claim(
        "So if we want to do the site survey with anticipations of a change "
        "order in order to loop in the rest of these once they get."
    )
    assert claim is not None
    assert "change order" in claim.lower()
    assert "survey" in claim.lower()


def test_display_label_prefers_deal_number_over_uuid():
    label = display_case_label(
        "66f5f6fb-78d4-44d4-953d-6094813244a4",
        report={
            "envelope": {
                "documents": [
                    {"filename": "010101-hs-note-112781068077-Different.txt"}
                ]
            }
        },
        case_dir_name="_audit010101",
    )
    assert label == "010101"


def test_display_label_never_returns_uuid():
    label = display_case_label("66f5f6fb-78d4-44d4-953d-6094813244a4")
    assert "66f5f6fb" not in label
