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


def test_payment_gate_canonical_wording():
    from orbitbrief_core.pm_handoff.pm_ask_rewrite import PAYMENT_GATE_ASK, family_key_for_question

    q = specialize_coverage_question(
        "payment_gate",
        blob="50% deposit due on order; Net 30 on remainder",
        project_mode="av_install",
        site_names=[],
    )
    assert q == PAYMENT_GATE_ASK
    assert family_key_for_question(q, "assumption.pay") == "payment"


def test_bom_strips_meter_chrome():
    from orbitbrief_core.pm_handoff.pm_ask_rewrite import rewrite_bom

    assert rewrite_bom("Access Point | 5 | Meter device access point quantity 5") is None
    assert rewrite_bom("Meter Shipping | 0 | Meter quantity 0") is None
    q = rewrite_bom("Meraki MS150-24MP-4X Cloud Managed Switch qty 2")
    assert q and "Meraki MS150" in q and "Meter" not in q


def test_assessment_mode_beats_access_control_primary():
    from orbitbrief_core.pm_handoff.question_engine import (
        MODE_ASSESSMENT,
        detect_project_mode,
    )

    mode = detect_project_mode(
        service_routing={"primary": "access_control", "enabled": True},
        blob=(
            "Azure AD Entra ID conditional access MFA pentest "
            "rules of engagement backup vault immutable storage"
        ),
    )
    assert mode == MODE_ASSESSMENT


def test_deal_flavor_rejects_hyphen_prose_and_prefers_header():
    from orbitbrief_core.pm_handoff.pm_ask_rewrite import (
        extract_deal_flavor,
        inject_site_anchor,
        is_hq_only_generic,
    )

    # Hyphenated "customer-negotiated…" must never become flavor.
    assert extract_deal_flavor(
        "customer-negotiated windows within roughly two weeks of deal close"
    ) is None
    # Structured header line wins.
    assert extract_deal_flavor("customer: Tillys\nbilling_type: T&M") == "Tillys"
    assert extract_deal_flavor("Customer: Dollar Tree\nBerwick PA") == "Dollar Tree"
    assert extract_deal_flavor("GRUBBRR kiosk install at restaurant") == "GRUBBRR"

    pinned = inject_site_anchor(
        "What hardware is customer-furnished vs PurTera-furnished — and who stages it to site?",
        ["Alpharetta GA", "Berwick PA"],
        blob="customer: Tillys\nMeraki MR46 APs",
    )
    assert "Tillys" in pinned or "Meraki" in pinned
    assert "Alpharetta" not in pinned  # HQ skipped when real site/flavor exists

    assert is_hq_only_generic(
        "Confirm remote/no-travel delivery — which sites would trigger travel billing "
        "if needed — at Alpharetta GA?"
    )
    assert not is_hq_only_generic(
        "Confirm remote/no-travel delivery — which sites would trigger travel billing "
        "if needed — Tillys · at Berwick PA?"
    )


def test_scope_suppresses_pentest_on_av_install():
    q = rewrite_scope(
        "Deliver penetration test executive summary and assessment report",
        "scope_item",
        project_mode="av_install",
    )
    assert q is None
