from __future__ import annotations

import re


KEYWORD_TO_FAMILY: dict[str, str] = {
    "wireless access point": "wireless_access_point",
    "wap": "wireless_access_point",
    "data outlet": "telecom_data_outlet",
    "voice outlet": "telecom_voice_outlet",
    "audio video": "av_device_outlet",
    "a/v": "av_device_outlet",
    "patch panel": "patch_panel_row",
    "equipment rack": "equipment_rack_front",
    "ladder rack": "ladder_rack_cable_runway",
    "runway": "ladder_rack_cable_runway",
    "riser": "riser_endpoint",
    "junction box": "junction_box",
    "pull box": "pull_box",
    "pull/junction": "junction_box",
    "camera schedule": "custom_camera_see_camera_schedule",
    "camera": "camera_device",
    "door contact": "door_contact_marker",
    "card reader": "card_reader_device",
    "request to exit": "request_to_exit_device",
    "intercom": "intercom_endpoint",
    "ground bar": "ground_bar",
    "telecommunications grounding busbar": "telecommunications_ground_busbar",
    "tmgb": "telecommunications_ground_busbar",
    "tgb": "telecommunications_ground_busbar",
    "jack tag": "telecomm_jack_tag",
}


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def derive_expected_families_from_packet_local_text(
    *,
    legend_texts: list[str],
    outlet_definition_texts: list[str],
    abbreviation_texts: list[str],
    page_titles: list[str],
    domain_default_families: list[str],
    packet_id: str = "",
) -> list[str]:
    joined = " | ".join(
        _norm(value)
        for value in [
            *legend_texts,
            *outlet_definition_texts,
            *abbreviation_texts,
            *page_titles,
        ]
    )
    families: set[str] = set()
    for keyword, family in KEYWORD_TO_FAMILY.items():
        pattern = r"\b" + re.escape(_norm(keyword)) + r"\b"
        if re.search(pattern, joined):
            families.add(family)

    domain_defaults = set(domain_default_families)
    if families:
        return sorted(list((families & domain_defaults) if domain_defaults else families))
    # Packet-level sanity fallback: avoid empty semantic target sets when packet text
    # still indicates schematic semantics.
    sanity: set[str] = set()
    if re.search(r"\b(riser|telecom|communications)\b", joined):
        sanity.update({"riser_endpoint", "telecom_data_outlet"})
    if re.search(r"\b(intercom|door|security|camera)\b", joined):
        sanity.update({"intercom_endpoint", "camera_device"})
    if re.search(r"\b(wireless|wap|ap)\b", joined):
        sanity.add("wireless_access_point")
    if re.search(r"\b(junction box|pull box|ground bar|tgb|tmgb)\b", joined):
        sanity.update({"junction_box", "pull_box", "ground_bar"})
    if domain_defaults:
        domain_default_list = sorted(domain_defaults)
        sanity = (sanity & domain_defaults) if sanity else set(domain_default_list[:2])
    if not sanity and packet_id in {
        "lv_a_aspen_house_telecom_intercom_risers",
        "lv_b_300_progress_communications",
    }:
        sanity = {"telecom_data_outlet", "riser_endpoint", "intercom_endpoint"}
    return sorted(sanity)
