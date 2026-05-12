from __future__ import annotations

import re

from orbitbrief_core.parser.site_schematic.packet_expected_family_deriver import KEYWORD_TO_FAMILY

_MEANING_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"wireless access point|\\bwap\\b|\\bap\\b", "wireless_access_point"),
    (r"security camera|cctv|video surveillance", "camera_device"),
    (r"card reader|proximity reader", "card_reader_device"),
    (r"door contact", "door_contact_marker"),
    (r"glass break", "glass_break_sensor"),
    (r"motion sensor|motion detector", "motion_sensor"),
    (r"intercom", "intercom_endpoint"),
    (r"telephone|wall ?phone|voice outlet", "telecom_voice_outlet"),
    (r"data outlet|communications outlet|telecommunications outlet", "telecom_data_outlet"),
    (r"television|catv|coax", "television_data_combo_outlet"),
    (r"junction box", "junction_box"),
    (r"pull box", "pull_box"),
    (r"ground busbar|tmgb|tgb", "ground_bar"),
    (r"equipment rack|rack elevation|patch panel", "equipment_rack_front"),
    (r"riser", "riser_endpoint"),
)


def _canonicalize(text: str) -> str:
    text = " ".join((text or "").lower().split())
    text = re.sub(r"[^a-z0-9\\s/_-]", " ", text)
    return re.sub(r"\\s+", " ", text).strip()


def derive_grounded_family(
    *,
    legend_text: str = "",
    mapped_semantic_text: str = "",
    outlet_definition_text: str = "",
    page_title: str = "",
    page_type: str = "",
    connector_context_score: float = 0.0,
    room_device_association_score: float = 0.0,
    allowed_families: list[str] | tuple[str, ...] = (),
) -> str:
    text = _canonicalize(" | ".join(
        (
            legend_text or "",
            mapped_semantic_text or "",
            outlet_definition_text or "",
            page_title or "",
        )
    ))
    allowed = set(allowed_families)
    matches: list[str] = []

    for pattern, family in _MEANING_PATTERNS:
        if re.search(pattern, text) and (not allowed or family in allowed):
            matches.append(family)

    for keyword, family in KEYWORD_TO_FAMILY.items():
        if _canonicalize(keyword) in text and (not allowed or family in allowed):
            matches.append(family)
    if matches:
        # Prefer the first deterministic match after de-duplication.
        return next(iter(dict.fromkeys(matches)))

    if connector_context_score >= 0.55 or room_device_association_score >= 0.55:
        if page_type == "riser_diagram" and (not allowed or "riser_endpoint" in allowed):
            return "riser_endpoint"
        if page_type == "equipment_room_layout" and (not allowed or "equipment_rack_front" in allowed):
            return "equipment_rack_front"
    return ""
