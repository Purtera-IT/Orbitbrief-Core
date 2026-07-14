"""Evidence-first customer question engine — mode gate, suppress, feedback, cap."""
from __future__ import annotations

from orbitbrief_core.pm_handoff.models import GapCard, SiteSummary
from orbitbrief_core.pm_handoff.question_engine import (
    MODE_NETWORK_EDGE_INSTALL,
    MODE_NETWORK_OPS,
    build_customer_questions,
    detect_project_mode,
)
from orbitbrief_core.pm_handoff.question_feedback import (
    ACTION_ADD,
    ACTION_DISMISS,
    ACTION_WRONG_FOR_PROJECT,
    QuestionFeedbackEvent,
    compile_feedback_policy,
    fingerprint_question,
)


def _sites(n: int = 13) -> list[SiteSummary]:
    return [
        SiteSummary(name=f"Site {i}", kind="physical_site", publishable=True)
        for i in range(n)
    ]


def _sodexo_atoms() -> list[dict]:
    return [
        {
            "id": "a1",
            "atom_type": "scope_item",
            "raw_text": (
                "Need help with Remote Hands for 13 corporate offices "
                "Transitioning from MPLS to SDWAN Meraki MX devices "
                "Turning on circuits at each location"
            ),
        },
        {
            "id": "a2",
            "atom_type": "open_question",
            "raw_text": "Once we know is it going to be one device per site?",
        },
        {
            "id": "a3",
            "atom_type": "deal_metadata",
            "raw_text": (
                "Will probably not do the other site in Montreal — keep everything on US paper"
            ),
        },
        {
            "id": "a4",
            "atom_type": "bom_line",
            "raw_text": "Meraki MX × 13",
        },
        {
            "id": "a5",
            "atom_type": "scope_item",
            "raw_text": "Maybe we can do a site survey charge for the walkthrough",
        },
        {
            "id": "a6",
            "atom_type": "decision",
            "raw_text": "POC site with customer; revise SOP during visit",
        },
        {
            "id": "a7",
            "atom_type": "open_question",
            "raw_text": "Quinton, do you have a copy of those sites that you can send to them?",
        },
        {
            "id": "a8",
            "atom_type": "risk",
            "raw_text": "Taken a little longer for them to get the circuits spun up there",
        },
    ]


def _ops_junk_gaps() -> list[GapCard]:
    return [
        GapCard(
            rule_id="network_maintenance.firmware_baseline_missing",
            domain_id="network_maintenance",
            domain_label="Network maintenance",
            label="Gold image",
            severity="warning",
            message="Gold image missing",
            suggested_open_question=(
                "What is the gold-image firmware baseline per device family "
                "(IOS-XE, NX-OS, JunOS, PAN-OS, ArubaOS) and how is drift detected?"
            ),
        ),
        GapCard(
            rule_id="network_maintenance.vlan_port_audit_cadence_missing",
            domain_id="network_maintenance",
            domain_label="Network maintenance",
            label="VLAN audit",
            severity="warning",
            message="VLAN audit missing",
            suggested_open_question="What recurring VLAN and port audit cadence is required?",
        ),
        GapCard(
            rule_id="global.commercial_structure",
            domain_id="global",
            domain_label="Global",
            label="Commercial",
            severity="warning",
            message="No commercial model",
            suggested_open_question="What is the commercial model: fixed fee, T&M, NTE?",
        ),
    ]


def test_detect_network_edge_install_mode():
    mode = detect_project_mode(
        atoms=_sodexo_atoms(),
        service_routing={
            "enabled": True,
            "primary": "network_maintenance",
            "confidence": 0.78,
            "source": "service_router_network_install_override",
            "override_reason": "sdwan_meraki_network_install_evidence",
        },
    )
    assert mode == MODE_NETWORK_EDGE_INSTALL


def test_sodexo_like_questions_are_real_pm_asks_not_ops_junk():
    cards, meta = build_customer_questions(
        gaps=_ops_junk_gaps(),
        sites=_sites(),
        envelope={
            "atoms": _sodexo_atoms(),
            "service_routing": {
                "enabled": True,
                "primary": "network_maintenance",
                "confidence": 0.78,
                "source": "service_router_network_install_override",
                "override_reason": "sdwan_meraki_network_install_evidence",
            },
        },
        feedback_events=[],
        cap=8,
    )
    assert meta["project_mode"] == MODE_NETWORK_EDGE_INSTALL
    questions = [c.suggested_open_question.lower() for c in cards]
    joined = " | ".join(questions)
    assert "gold-image" not in joined and "gold image" not in joined
    assert "vlan" not in joined or "audit cadence" not in joined
    assert len(cards) <= 8
    assert len(cards) >= 3
    # Topology / phase / survey should surface
    assert any("per site" in q or "topology" in q for q in questions)
    assert any("montreal" in q or "phase" in q or "deferred" in q for q in questions)
    # Site-list copy chatter suppressed when sites already published
    assert not any("copy of those sites" in q for q in questions)


def test_ops_mode_allows_ops_family_questions():
    atoms = [
        {
            "id": "o1",
            "atom_type": "scope_item",
            "raw_text": (
                "Ongoing network maintenance: SmartNet coverage, monthly firmware "
                "patch window, VLAN audit cadence for the estate"
            ),
        }
    ]
    cards, meta = build_customer_questions(
        gaps=_ops_junk_gaps(),
        sites=_sites(2),
        envelope={
            "atoms": atoms,
            "service_routing": {
                "enabled": True,
                "primary": "network_maintenance",
                "confidence": 0.9,
            },
        },
        feedback_events=[],
        cap=8,
    )
    assert meta["project_mode"] == MODE_NETWORK_OPS
    joined = " ".join(c.suggested_open_question.lower() for c in cards)
    assert "coverage" in joined or "patch" in joined or "change window" in joined


def test_dismiss_feedback_suppresses_rule_immediately():
    dismiss = QuestionFeedbackEvent(
        deal_id="deal-1",
        action=ACTION_DISMISS,
        project_mode=MODE_NETWORK_EDGE_INSTALL,
        rule_id="mode.network_edge_install.survey_commercial",
        question_text="Is the site survey a separate charge?",
        fingerprint=fingerprint_question("Is the site survey a separate charge?"),
    )
    cards, _ = build_customer_questions(
        gaps=[],
        sites=_sites(),
        envelope={
            "atoms": _sodexo_atoms(),
            "service_routing": {
                "enabled": True,
                "primary": "network_maintenance",
                "override_reason": "sdwan_meraki_network_install_evidence",
            },
        },
        feedback_events=[dismiss],
        cap=8,
    )
    assert all(c.rule_id != "mode.network_edge_install.survey_commercial" for c in cards)


def test_gold_add_promotes_on_same_mode():
    gold = QuestionFeedbackEvent(
        deal_id="prior-deal",
        action=ACTION_ADD,
        project_mode=MODE_NETWORK_EDGE_INSTALL,
        rule_id="pm_gold.isp_demarc",
        question_text="Is the ISP demarc ready and labeled at each site before smart-hands arrival?",
    )
    cards, _ = build_customer_questions(
        gaps=[],
        sites=_sites(),
        envelope={
            "atoms": _sodexo_atoms(),
            "service_routing": {
                "enabled": True,
                "primary": "network_maintenance",
                "override_reason": "sdwan_meraki_network_install_evidence",
            },
        },
        feedback_events=[gold],
        cap=8,
    )
    assert any("isp demarc" in c.suggested_open_question.lower() for c in cards)


def test_wrong_for_project_mode_scoped():
    policy = compile_feedback_policy(
        [
            QuestionFeedbackEvent(
                deal_id="d",
                action=ACTION_WRONG_FOR_PROJECT,
                project_mode=MODE_NETWORK_EDGE_INSTALL,
                rule_id="network_maintenance.firmware_baseline_missing",
            )
        ]
    )
    assert (
        MODE_NETWORK_EDGE_INSTALL,
        "network_maintenance.firmware_baseline_missing",
    ) in policy.suppressed_mode_rules
