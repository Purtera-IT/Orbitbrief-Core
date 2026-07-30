"""Sharpness gate: reject Confirm-pastes / email chrome; keep real PM asks."""
from __future__ import annotations

from orbitbrief_core.pm_handoff.pm_ask_rewrite import (
    rewrite_assumption,
    rewrite_instruction,
    rewrite_scope,
)
from orbitbrief_core.pm_handoff.question_quality import validate_question_card


def _card(q: str, rid: str = "t.1") -> dict:
    return {
        "rule_id": rid,
        "suggested_open_question": q,
        "sources": [
            {
                "filename": "sow.pdf",
                "snippet": "Pathway by others; AP home runs TBD in survey.",
            }
        ],
    }


def test_rejects_confirm_paste():
    viols = validate_question_card(
        _card("Confirm customer instruction: Hope you are having a great week?")
    )
    codes = {v.code for v in viols}
    assert "confirm_paste" in codes or "email_chrome" in codes


def test_rejects_assumption_paste():
    viols = validate_question_card(
        _card(
            "Confirm pricing assumption is still valid: Labor Sell Rate, USD per hour | 110?"
        )
    )
    assert any(v.code in {"confirm_paste", "table_row"} for v in viols)


def test_keeps_sharp_pm_ask():
    viols = validate_question_card(
        _card(
            "For the new APs — new home runs/pulls, or terminate to existing port availability only?"
        )
    )
    assert viols == []


def test_rewrite_instruction_no_paste():
    q = rewrite_instruction(
        "For the 6 new APs, does it include new home runs / pulls? "
        "The SOW only indicates terminating to existing port availability."
    )
    assert q is not None
    assert "home run" in q.lower()
    assert not q.lower().startswith("confirm customer instruction:")


def test_rewrite_skips_email_chrome():
    assert rewrite_instruction("Hope you are all having a great start to the week!") is None
    assert rewrite_assumption("Form W-9 must be completed by either party.") is None


def test_rewrite_scope_include_exclude():
    q = rewrite_scope("Configure Azure Backup vault for immutable retention.", "task")
    assert q is not None
    assert "azure" in q.lower() or "backup" in q.lower()
