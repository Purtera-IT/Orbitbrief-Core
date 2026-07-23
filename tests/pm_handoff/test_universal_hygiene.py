"""Universal fact + evidence hygiene (P/O rules)."""
from __future__ import annotations

from orbitbrief_core.pm_handoff.fact_quality import (
    filter_pm_visible_atoms,
    is_av_install_gold_fact,
    is_marketing_or_chrome_fact,
    is_speculative_risk_fact,
    polish_fact_claim,
    unwrap_fact_text,
)
from orbitbrief_core.pm_handoff.question_engine import (
    _score_atom_for_evidence,
    detect_project_mode,
)


def test_unwrap_and_drop_marketing_from_facts():
    assert unwrap_fact_text('["The image shows Behind TV 1."]').startswith("The image")
    assert is_marketing_or_chrome_fact("Quotes in 24–48 hours")
    assert is_marketing_or_chrome_fact("AI-driven PMO oversight that improves communication")
    assert polish_fact_claim("Quotes in 24–48 hours") is None
    assert polish_fact_claim(
        "Cables run across the floor, approximately 10 feet to a network receptacle."
    )


def test_filter_drops_stubs_chrome_spec_risks():
    atoms = [
        {
            "id": "stub",
            "atom_type": "deal_metadata",
            "text": "[Image extracted - awaiting OCR / vision] page8/image64",
        },
        {
            "id": "chrome",
            "atom_type": "scope_item",
            "text": "Quotes in 24–48 hours",
        },
        {
            "id": "risk",
            "atom_type": "risk",
            "text": "The floor is carpeted, which may pose a slight trip hazard if cables are not properly managed.",
        },
        {
            "id": "good",
            "atom_type": "scope_item",
            "text": "HDMI over Ethernet adapter and HDMI Replicator retained as part of the Yealink system.",
        },
        {
            "id": "excl",
            "atom_type": "exclusion",
            "text": "AI-driven PMO oversight that improves communication, quality, and transaction speed",
        },
    ]
    kept, meta = filter_pm_visible_atoms(atoms)
    ids = {a["id"] for a in kept}
    assert "good" in ids
    assert "stub" not in ids
    assert "chrome" not in ids
    assert "risk" not in ids
    assert "excl" not in ids
    assert meta["fact_quality_dropped_pre"] >= 3


def test_evidence_prefers_image_fact_over_blurb():
    question = (
        "Confirm the floor network path method: poke-through / floor box "
        "vs surface raceway for the ~10ft run to the receptacle."
    )
    import re

    trigger = re.compile(
        r"\b(?:across\s+the\s+floor|floor\s+network|floor\s+(?:box|receptacle)|"
        r"10\s+(?:ft|feet)|trip\s+hazard)\b",
        re.I,
    )
    blurb = {
        "atom_type": "deal_metadata",
        "text": (
            '["The image depicts a conference room setup with a focus on AV/UC equipment. '
            'The room is rectangular with a large U-shaped table covered in a black tablecloth."]'
        ),
        "value": {
            "via": "pdf_image_vision",
            "fact_kind": "image_description",
            "evidence_rank": "blurb",
        },
    }
    fact = {
        "atom_type": "scope_item",
        "text": "Cables run across the floor, approximately 10 feet to a network receptacle.",
        "value": {
            "via": "pdf_image_vision",
            "fact_kind": "image_fact:cable",
            "evidence_rank": "fact",
        },
    }
    s_blurb = _score_atom_for_evidence(blurb, trigger=trigger, question=question)
    s_fact = _score_atom_for_evidence(fact, trigger=trigger, question=question)
    assert s_fact > 0.5
    assert s_fact > s_blurb
    assert s_blurb == 0.0  # vague room overview rejected

    keep_tv = {
        "atom_type": "scope_item",
        "text": "These 4 TVs to Stay in Place – will remain on floor in this position.",
        "value": {
            "via": "pdf_image_vision",
            "fact_kind": "image_fact:annotation",
            "evidence_rank": "fact",
        },
    }
    s_keep = _score_atom_for_evidence(keep_tv, trigger=trigger, question=question)
    assert s_fact > s_keep


def test_av_install_gold_displaces_sow_boilerplate_in_risks_lane():
    """VESA / ceiling gold must appear even when verified SOW risks fill the cap."""
    from orbitbrief_core.pm_handoff.builder import MAX_FACTS_PER_CATEGORY, _build_fact_cards

    atoms: list[dict] = []
    for i in range(MAX_FACTS_PER_CATEGORY + 2):
        atoms.append(
            {
                "id": f"sow_risk_{i}",
                "atom_type": "risk",
                "verified": "verified",
                "confidence": 0.9,
                "text": (
                    f"Schedule changes requested by the customer that are not "
                    f"discussed in the Status Meeting variant {i}."
                ),
            }
        )
    atoms.append(
        {
            "id": "vesa_gold",
            "atom_type": "scope_item",
            "confidence": 0.67,
            "text": (
                "MOUNTS / HARDWARE: Fixed wall mount for the TV, "
                "visible VESA plate and mounting bracket."
            ),
        }
    )
    atoms.append(
        {
            "id": "ceiling_gold",
            "atom_type": "scope_item",
            "confidence": 0.62,
            "text": "Ceiling tiles as they are hard to get.",
        }
    )
    facts, _meta = _build_fact_cards({"atoms": atoms}, {})
    risk_texts = [c.text for c in (facts.get("risks") or [])]
    joined = " ".join(risk_texts).lower()
    assert "vesa" in joined
    assert "ceiling tiles" in joined or "hard to get" in joined


def test_av_dense_beats_wireless_abstain_and_network_noise():
    blob = (
        "Neat bar Yealink conference room VESA mount HDMI over Ethernet "
        "behind the wall display mount. Also mentions WiFi in a capability matrix."
    )
    mode = detect_project_mode(
        service_routing={
            "enabled": True,
            "primary": None,
            "abstained": True,
            "abstain_reason": "missing_evidence_anchors",
            "neural_primary": "wireless",
        },
        blob=blob,
    )
    assert mode == "av_install"


def test_abstained_router_does_not_force_staff_aug():
    blob = (
        "Yealink codec Neat bar HDMI over Ethernet conference room AV install "
        "displays stay in place behind the wall"
    )
    mode = detect_project_mode(
        service_routing={
            "enabled": True,
            "primary": None,
            "abstained": True,
            "abstain_reason": "missing_evidence_anchors",
            "neural_primary": "staff_augmentation",
            "confidence": 0.78,
        },
        blob=blob,
    )
    assert mode == "av_install"


def test_speculative_risk_helper():
    assert is_speculative_risk_fact(
        "HVAC elements are visible in the ceiling, potentially affecting camera field of view."
    )
    assert is_speculative_risk_fact(
        "A backpack is placed on the floor near a chair, which could pose a minor obstruction or trip hazard."
    )
    assert is_speculative_risk_fact(
        "The loose cables on the floor pose a potential trip hazard, as noted in the annotations."
    )
    assert is_speculative_risk_fact(
        "The cables under the table are not fully concealed, which may affect the room's aesthetic."
    )
    assert not is_speculative_risk_fact(
        "Replication cable should be moved behind the wall for drywall patch."
    )
