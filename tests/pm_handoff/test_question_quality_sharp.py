"""Sharpness gate: reject wraps / chrome / naked coverage; keep real PM asks."""
from __future__ import annotations

from orbitbrief_core.pm_handoff.pm_ask_rewrite import (
    rewrite_assumption,
    rewrite_instruction,
    rewrite_requirement,
    rewrite_scope,
    specialize_coverage_question,
)
from orbitbrief_core.pm_handoff.question_quality import validate_question_card


def _card(q: str, rid: str = "t.1") -> dict:
    return {
        "rule_id": rid,
        "suggested_open_question": q,
        "sources": [
            {
                "filename": "sow.pdf",
                "snippet": "Pathway by others; AP home runs TBD in survey notes.",
            }
        ],
    }


def test_rejects_confirm_paste():
    viols = validate_question_card(
        _card("Confirm customer instruction: Hope you are having a great week?")
    )
    codes = {v.code for v in viols}
    assert codes & {"confirm_paste", "email_chrome", "meta_ask"}


def test_rejects_include_wrap_and_ellipsis():
    viols = validate_question_card(
        _card('Include in this quote, or exclude: "Total Fees due under this SOW…"')
    )
    codes = {v.code for v in viols}
    assert "confirm_paste" in codes or "truncated" in codes or "boilerplate" in codes


def test_rejects_naked_coverage():
    viols = validate_question_card(
        _card(
            "Which sites are in this quote wave — confirm the authoritative address list and any deferrals."
        )
    )
    assert any(v.code == "naked_coverage" for v in viols)


def test_rejects_url_stem():
    viols = validate_question_card(
        _card(
            "Confirm the authoritative quantity where sources disagree: "
            "https://d5-klx04.na1.hs-sales-engage.com/Ctc/x?"
        )
    )
    assert any(v.code == "url_stem" for v in viols)


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


def test_rewrite_skips_email_chrome_and_boilerplate():
    assert rewrite_instruction("Hope you are all having a great start to the week!") is None
    assert rewrite_assumption("Form W-9 must be completed by either party.") is None
    assert rewrite_scope("This document is a draft intended only for use in the review of text.", "scope_item") is None
    assert rewrite_requirement("Any Services not expressly set forth in the Project Scope will be…", "exclusion") is None


def test_coverage_specializes_or_suppresses():
    # No sites / weak trigger → suppressed
    assert (
        specialize_coverage_question(
            "site_list_lock", blob="general project notes", project_mode="generic", site_names=[]
        )
        is None
    )
    # Wireless without AP evidence on AV mode → suppressed
    assert (
        specialize_coverage_question(
            "wireless_design",
            blob="display mount hdmi codec",
            project_mode="av_install",
            site_names=["Kennesaw"],
        )
        is None
    )
    # Real AP evidence → specialized
    q = specialize_coverage_question(
        "wireless_design",
        blob="Install 12 access points with SSID redesign",
        project_mode="wireless_install",
        site_names=["Alpharetta GA"],
    )
    assert q and "AP" in q
