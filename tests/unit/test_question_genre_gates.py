"""Universal question genre gates — deal-agnostic wrong-genre drops."""

from __future__ import annotations

from orbitbrief_core.pm_handoff.question_engine import detect_project_mode
from orbitbrief_core.pm_handoff.question_genre_gates import (
    detect_lift_access_conflicts,
    should_drop_question_card,
)


def test_field_sensor_blob_not_av_mode() -> None:
    blob = (
        "ANOVA tank monitoring installations across three customer locations. "
        "three site surveys and eight tank monitor installations. "
        "DPW900 telemetry RTU chemical bulk tank. Provide access to all tanks. "
        "Fixed fee survey and tank install. "
    )
    assert detect_project_mode(blob=blob) != "av_install"


def test_drop_av_keep_remove_on_change_order_boilerplate() -> None:
    card = {
        "rule_id": "mode.av_install.keep_vs_remove_displays",
        "label": "Existing displays keep vs remove",
        "message": "Keep/remove for existing AV gear is still open",
        "suggested_open_question": "Confirm which existing TVs/displays stay mounted?",
        "observed_summary": "Evidence: change_order_rule",
        "sources": [
            {
                "snippet": (
                    "No change or modification to this SOW shall be effective or "
                    "binding except for billing the actual Time and Material hours."
                )
            }
        ],
    }
    deal = "ANOVA tank monitoring eight tank installs DPW900 RTU telemetry survey"
    reason = should_drop_question_card(card, project_mode="av_install", deal_blob=deal)
    assert reason is not None


def test_drop_sap_helpdesk_chrome() -> None:
    card = {
        "rule_id": "assumption.sap",
        "label": "Constraint",
        "message": "Requirement/constraint needs PM confirmation.",
        "suggested_open_question": "Confirm which telemetry / SAP dependencies are in-scope?",
        "sources": [
            {
                "snippet": (
                    "If you encounter any SAP S4 issues, please be sure you have "
                    "Shipment and Delivery numbers, screen shots of issues, user id."
                )
            }
        ],
    }
    assert should_drop_question_card(card) is not None


def test_drop_user_manual_part_number() -> None:
    card = {
        "rule_id": "scope.dpa968",
        "label": "Scope — scope item",
        "message": "Scope commitment needs PM confirmation before quoting.",
        "suggested_open_question": "Does DPA968L remain in fixed fee?",
        "sources": [
            {
                "filename": "DW900 Series User Guide.pdf",
                "snippet": "3.5.4 DPA968L — Mains Power Supply (with Heater). part number dpa968l",
            }
        ],
    }
    assert should_drop_question_card(card) is not None


def test_lift_conflict_emitted() -> None:
    atoms = [
        {
            "atom_id": "a1",
            "type": "assumption",
            "text": "No lift, ladder truck, scaffolding, or other rented access equipment is required.",
        },
        {
            "atom_id": "a2",
            "type": "customer_instruction",
            "text": "need to rent a lift.",
        },
    ]
    rows = detect_lift_access_conflicts(atoms)
    assert len(rows) == 1
    assert "lift" in rows[0]["label"].lower()
    assert len(rows[0]["sources"]) == 2


def test_real_av_keep_remove_kept() -> None:
    card = {
        "rule_id": "mode.av_install.keep_vs_remove_displays",
        "label": "Existing displays keep vs remove",
        "message": "Keep/remove open",
        "suggested_open_question": "Confirm which TVs stay mounted and which codecs are removed?",
        "sources": [
            {
                "snippet": (
                    "Existing TVs to stay in place on the VESA mount; codecs will be removed "
                    "and replaced with Neat Bar."
                )
            }
        ],
    }
    deal = "Neat Bar conference room Teams Room soundbar HDMI install"
    assert should_drop_question_card(card, project_mode="av_install", deal_blob=deal) is None
