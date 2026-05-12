from __future__ import annotations

import re

PACKET_ALIAS_TO_FAMILY: dict[str, dict[str, str]] = {
    "wireless_current_pair": {
        "WAP": "wireless_access_point",
        "AP": "wireless_access_point",
        "INT": "intercom_endpoint",
        "INTERCOM": "intercom_endpoint",
        "IC": "intercom_endpoint",
        "PB": "pull_box",
        "PBX": "pull_box",
        "JBOX": "junction_box",
    },
    "low_voltage_current_pair": {
        "DC": "door_contact",
        "DA": "duress_alarm_button",
        "CR": "card_reader",
        "CAM": "custom_camera_see_camera_schedule",
        "TV": "television_data_combo_outlet",
        "D": "communications_outlet",
        "A": "communications_outlet",
        "F": "fiber_outlet",
        "B": "telephone_outlet",
        "E": "telephone_outlet",
        "PHONE": "telephone_outlet",
        "ZN": "zigbee_node_outlet",
        "ZIGBEE": "zigbee_node_outlet",
    },
    "lv_c_union_street_telecom_grounding_intercom": {
        "D": "telecom_data_outlet",
        "DATA": "telecom_data_outlet",
        "INT": "intercom_endpoint",
        "IC": "intercom_endpoint",
        "WAP": "wireless_access_point",
    },
    "lv_e_columbus_library_technology_security": {
        "WAP": "wireless_access_point",
        "JB": "junction_box",
        "JBOX": "junction_box",
        "TGB": "telecommunications_ground_busbar",
        "TMGB": "telecommunications_ground_busbar",
        "KP": "keypad",
        "PA": "speaker",
    },
    "lv_a_aspen_house_telecom_intercom_risers": {
        "INT": "intercom_endpoint",
        "IC": "intercom_endpoint",
        "DATA": "telecom_data_outlet",
        "D": "telecom_data_outlet",
        "R": "riser_endpoint",
    },
    "lv_b_300_progress_communications": {
        "INT": "intercom_endpoint",
        "INTERCOM": "intercom_endpoint",
        "IC": "intercom_endpoint",
        "DATA": "telecom_data_outlet",
        "D": "telecom_data_outlet",
        "R": "riser_endpoint",
    },
}


def packet_alias_family(packet_id: str, alias_token: str) -> str | None:
    packet_map = PACKET_ALIAS_TO_FAMILY.get(packet_id, {})
    alias = (alias_token or "").strip().upper()
    if not alias:
        return None
    return packet_map.get(alias)


def infer_family_from_packet_context(
    *,
    packet_id: str,
    sheet_type: str,
    alias_tokens: tuple[str, ...],
    text_hints: tuple[str, ...],
) -> str:
    for token in alias_tokens:
        mapped = packet_alias_family(packet_id, token)
        if mapped:
            return mapped

    text = " ".join(str(tok) for tok in text_hints).lower()
    if re.search(r"\bintercom\b", text):
        return "intercom_endpoint"
    if re.search(r"\bwireless\b|\bwap\b|\baccess point\b", text):
        return "wireless_access_point"
    if re.search(r"\bjunction box\b|\bjbox\b|\bjb\b", text):
        return "junction_box"
    if re.search(r"\bpull box\b|\bpb\b", text):
        return "pull_box"
    if re.search(r"\btmgb\b|\btgb\b|\bground busbar\b", text):
        return "telecommunications_ground_busbar"
    if re.search(r"\bspeaker\b|\bpa\b", text):
        return "speaker"
    if re.search(r"\bdoor contact\b|\bdc\b", text):
        return "door_contact"
    if re.search(r"\bcamera schedule\b|\bcctv\b|\bcamera\b", text):
        if packet_id == "low_voltage_current_pair":
            return "custom_camera_see_camera_schedule"
        return "camera_endpoint"
    if sheet_type == "riser_diagram" or re.search(r"\briser\b", text):
        return "riser_endpoint"
    if re.search(r"\btelecom\b|\bcommunications\b|\bdata outlet\b", text):
        return "telecom_data_outlet"
    if packet_id in {"wireless_current_pair", "lv_b_300_progress_communications"} and sheet_type in {
        "floorplan_overall",
        "riser_diagram",
        "installation_detail",
    }:
        return "intercom_endpoint"
    return ""
