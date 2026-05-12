from __future__ import annotations

from typing import Any, Mapping


_PROFILE_CONFIG: dict[str, dict[str, Any]] = {
    "control_legend_profile": {
        "favored_classes": {"telecomm_jack_tag"},
        "suppressed_classes": {
            "data_outlet",
            "door_contact_marker",
            "riser_endpoint",
            "equipment_rack_front",
            "ladder_rack_cable_runway",
            "j_hook_pathway_symbol",
        },
        "class_threshold_delta": {
            "telecomm_jack_tag": 0.08,
            "data_outlet": 0.18,
            "door_contact_marker": 0.16,
            "riser_endpoint": 0.2,
            "ladder_rack_cable_runway": 0.17,
            "equipment_rack_front": 0.22,
            "j_hook_pathway_symbol": 0.2,
        },
        "class_score_delta": {
            "telecomm_jack_tag": -0.22,
            "data_outlet": -1.25,
            "door_contact_marker": -1.2,
            "riser_endpoint": -1.3,
            "ladder_rack_cable_runway": -1.25,
            "equipment_rack_front": -1.4,
            "j_hook_pathway_symbol": -1.32,
        },
        "suppression_margin": 0.6,
    },
    "plan_body_profile": {
        "favored_classes": {
            "data_outlet",
            "door_contact_marker",
            "telecomm_jack_tag",
            "wireless_access_point_marker",
            "wireless_node_wall_outlet",
            "zigbee_node_ceiling_outlet",
        },
        "suppressed_classes": {"equipment_rack_front", "ladder_rack_cable_runway"},
        "class_threshold_delta": {
            "data_outlet": -0.03,
            "door_contact_marker": 0.03,
            "telecomm_jack_tag": 0.04,
            "riser_endpoint": 0.08,
            "ladder_rack_cable_runway": 0.1,
            "equipment_rack_front": 0.18,
            "j_hook_pathway_symbol": 0.08,
        },
        "class_score_delta": {
            "data_outlet": 0.1,
            "door_contact_marker": 0.05,
            "telecomm_jack_tag": -0.18,
            "riser_endpoint": -0.2,
            "ladder_rack_cable_runway": -0.3,
            "equipment_rack_front": -0.5,
            "j_hook_pathway_symbol": -0.24,
        },
        "suppression_margin": 0.85,
    },
    "detail_installation_profile": {
        "favored_classes": {
            "door_contact_marker",
            "j_hook_pathway_symbol",
            "telecomm_jack_tag",
            "riser_endpoint",
        },
        "suppressed_classes": {"equipment_rack_front"},
        "class_threshold_delta": {
            "data_outlet": 0.03,
            "door_contact_marker": -0.04,
            "riser_endpoint": -0.05,
            "telecomm_jack_tag": 0.05,
            "j_hook_pathway_symbol": -0.08,
            "ladder_rack_cable_runway": -0.03,
            "equipment_rack_front": 0.12,
        },
        "class_score_delta": {
            "data_outlet": -0.08,
            "door_contact_marker": 0.1,
            "riser_endpoint": 0.15,
            "telecomm_jack_tag": -0.12,
            "j_hook_pathway_symbol": 0.24,
            "ladder_rack_cable_runway": 0.12,
            "equipment_rack_front": -0.32,
        },
        "suppression_margin": 0.8,
    },
    "equipment_room_profile": {
        "favored_classes": {"equipment_rack_front", "patch_panel_row", "ladder_rack_cable_runway"},
        "suppressed_classes": {"door_contact_marker", "wireless_node_wall_outlet", "zigbee_node_ceiling_outlet"},
        "class_threshold_delta": {
            "data_outlet": 0.12,
            "door_contact_marker": 0.16,
            "riser_endpoint": 0.08,
            "telecomm_jack_tag": 0.08,
            "ladder_rack_cable_runway": -0.08,
            "equipment_rack_front": -0.12,
            "j_hook_pathway_symbol": 0.08,
            "patch_panel_row": -0.08,
        },
        "class_score_delta": {
            "data_outlet": -0.45,
            "door_contact_marker": -0.55,
            "riser_endpoint": -0.18,
            "telecomm_jack_tag": -0.22,
            "ladder_rack_cable_runway": 0.2,
            "equipment_rack_front": 0.35,
            "j_hook_pathway_symbol": -0.18,
            "patch_panel_row": 0.25,
        },
        "suppression_margin": 0.7,
    },
    "rack_detail_profile": {
        "favored_classes": {"equipment_rack_front", "patch_panel_row", "ladder_rack_cable_runway"},
        "suppressed_classes": {"data_outlet", "door_contact_marker", "wireless_node_wall_outlet", "zigbee_node_ceiling_outlet"},
        "class_threshold_delta": {
            "data_outlet": 0.14,
            "door_contact_marker": 0.18,
            "riser_endpoint": 0.06,
            "telecomm_jack_tag": 0.09,
            "ladder_rack_cable_runway": -0.12,
            "equipment_rack_front": -0.15,
            "j_hook_pathway_symbol": 0.05,
            "patch_panel_row": -0.1,
        },
        "class_score_delta": {
            "data_outlet": -0.55,
            "door_contact_marker": -0.65,
            "riser_endpoint": -0.15,
            "telecomm_jack_tag": -0.24,
            "ladder_rack_cable_runway": 0.25,
            "equipment_rack_front": 0.4,
            "j_hook_pathway_symbol": -0.12,
            "patch_panel_row": 0.3,
        },
        "suppression_margin": 0.65,
    },
    "riser_profile": {
        "favored_classes": {"riser_endpoint", "j_hook_pathway_symbol", "ladder_rack_cable_runway"},
        "suppressed_classes": {"data_outlet", "door_contact_marker", "equipment_rack_front"},
        "class_threshold_delta": {
            "data_outlet": 0.18,
            "door_contact_marker": 0.2,
            "riser_endpoint": -0.14,
            "telecomm_jack_tag": 0.12,
            "ladder_rack_cable_runway": -0.05,
            "equipment_rack_front": 0.2,
            "j_hook_pathway_symbol": -0.08,
        },
        "class_score_delta": {
            "data_outlet": -0.65,
            "door_contact_marker": -0.7,
            "riser_endpoint": 0.45,
            "telecomm_jack_tag": -0.3,
            "ladder_rack_cable_runway": 0.2,
            "equipment_rack_front": -0.6,
            "j_hook_pathway_symbol": 0.2,
        },
        "suppression_margin": 0.65,
    },
    "mixed_detail_profile": {
        "favored_classes": {
            "data_outlet",
            "telecomm_jack_tag",
            "riser_endpoint",
            "equipment_rack_front",
            "j_hook_pathway_symbol",
        },
        "suppressed_classes": set(),
        "class_threshold_delta": {
            "data_outlet": 0.03,
            "door_contact_marker": 0.04,
            "riser_endpoint": -0.03,
            "telecomm_jack_tag": 0.04,
            "ladder_rack_cable_runway": -0.02,
            "equipment_rack_front": -0.05,
            "j_hook_pathway_symbol": -0.05,
        },
        "class_score_delta": {
            "data_outlet": 0.0,
            "door_contact_marker": -0.05,
            "riser_endpoint": 0.15,
            "telecomm_jack_tag": -0.1,
            "ladder_rack_cable_runway": 0.12,
            "equipment_rack_front": 0.15,
            "j_hook_pathway_symbol": 0.2,
        },
        "suppression_margin": 0.8,
    },
}


def available_detector_profiles() -> tuple[str, ...]:
    return tuple(_PROFILE_CONFIG.keys())


def get_detector_profile(profile_id: str) -> Mapping[str, Any]:
    return _PROFILE_CONFIG.get(profile_id, _PROFILE_CONFIG["mixed_detail_profile"])


def _contains_any(value: str, tokens: tuple[str, ...]) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in tokens)


def select_profile_for_context(
    *,
    sheet_type: str,
    region_kind: str = "",
    detail_kind: str = "",
    subregion_role: str = "",
    pseudo_role: str = "",
    local_text: str = "",
) -> tuple[str, tuple[str, ...]]:
    reasons: list[str] = []
    joined = " ".join([sheet_type, region_kind, detail_kind, subregion_role, pseudo_role, local_text]).lower()
    if sheet_type in {"legend_symbol", "notes_spec", "schedule_sheet"} or _contains_any(joined, ("legend", "abbreviation", "notes/spec", "schedule", "title block", "revision")):
        reasons.append("control_or_legend_context")
        return ("control_legend_profile", tuple(reasons))
    if sheet_type == "riser_diagram" or _contains_any(joined, ("riser", "backbone", "vertical riser", "fiber riser", "coax riser")):
        reasons.append("riser_context")
        return ("riser_profile", tuple(reasons))
    if sheet_type == "rack_detail" or _contains_any(joined, ("rack", "cabinet", "patch panel", "ladder rack", "wire manager")):
        reasons.append("rack_context")
        return ("rack_detail_profile", tuple(reasons))
    if sheet_type == "equipment_room_layout" or _contains_any(joined, ("equipment room", "idf", "mdf", "telecom room")):
        reasons.append("equipment_room_context")
        return ("equipment_room_profile", tuple(reasons))
    if sheet_type == "installation_detail" or _contains_any(joined, ("installation detail", "pathway detail", "grounding detail")):
        reasons.append("installation_detail_context")
        return ("detail_installation_profile", tuple(reasons))
    if sheet_type in {"floorplan_overall", "floorplan_detail"} and _contains_any(joined, ("equipment", "riser", "detail", "mixed")):
        reasons.append("mixed_floorplan_context")
        return ("mixed_detail_profile", tuple(reasons))
    reasons.append("plan_body_default")
    return ("plan_body_profile", tuple(reasons))


def select_profile_for_candidate_row(row: Mapping[str, Any]) -> tuple[str, tuple[str, ...]]:
    return select_profile_for_context(
        sheet_type=str(row.get("sheet_type", "")),
        region_kind=str(row.get("region_kind", "")),
        detail_kind=str(row.get("detail_kind", "")),
        subregion_role=str(row.get("subregion_role", "")),
        pseudo_role=str(row.get("pseudo_page_role", "")),
        local_text=str(row.get("local_text_context", "")),
    )


def profile_threshold_delta(profile_id: str, detector_class_id: str) -> float:
    profile = get_detector_profile(profile_id)
    return float(dict(profile.get("class_threshold_delta", {})).get(detector_class_id, 0.0))


def profile_score_adjustment(profile_id: str, detector_class_id: str) -> float:
    profile = get_detector_profile(profile_id)
    favored = set(profile.get("favored_classes", set()))
    suppressed = set(profile.get("suppressed_classes", set()))
    class_score_delta = float(dict(profile.get("class_score_delta", {})).get(detector_class_id, 0.0))
    if detector_class_id in favored:
        return 0.55 + class_score_delta
    if detector_class_id in suppressed:
        return -0.95 + class_score_delta
    return class_score_delta


def is_class_suppressed(profile_id: str, detector_class_id: str) -> bool:
    profile = get_detector_profile(profile_id)
    suppressed = set(profile.get("suppressed_classes", set()))
    return detector_class_id in suppressed


def profile_suppression_margin(profile_id: str) -> float:
    profile = get_detector_profile(profile_id)
    return float(profile.get("suppression_margin", 0.8))

