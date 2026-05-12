from __future__ import annotations

from collections import Counter, defaultdict
from math import hypot
from typing import Any

from orbitbrief_core.parser.site_schematic.models import (
    SiteSchematicRiserEdge,
    SiteSchematicSymbolInstance,
    SiteSchematicSymbolLink,
    SiteSchematicTopologyEndpoint,
    SiteSchematicTopologyRelation,
    SiteSchematicTopologySegment,
)
from orbitbrief_core.parser.site_schematic.symbols.profile_routing import select_profile_for_context

_TOPOLOGY_CLASS_TO_KIND = {
    "riser_endpoint": "riser_endpoint",
    "ladder_rack_cable_runway": "pathway_runway",
    "j_hook_pathway_symbol": "pathway_support",
    "equipment_rack_front": "rack_component",
    "patch_panel_row": "rack_component",
    "telecomm_jack_tag": "termination_point",
    "data_outlet": "termination_point",
    "door_contact_marker": "security_endpoint",
}

_PROFILE_ALLOWED_CLASSES = {
    "riser_profile": {"riser_endpoint", "ladder_rack_cable_runway", "j_hook_pathway_symbol", "telecomm_jack_tag"},
    "rack_detail_profile": {"equipment_rack_front", "patch_panel_row", "ladder_rack_cable_runway", "telecomm_jack_tag"},
    "equipment_room_profile": {"equipment_rack_front", "patch_panel_row", "ladder_rack_cable_runway", "riser_endpoint"},
    "detail_installation_profile": {"j_hook_pathway_symbol", "ladder_rack_cable_runway", "telecomm_jack_tag", "data_outlet"},
    "mixed_detail_profile": {"riser_endpoint", "ladder_rack_cable_runway", "j_hook_pathway_symbol", "equipment_rack_front", "patch_panel_row"},
    "plan_body_profile": {"data_outlet", "telecomm_jack_tag", "door_contact_marker"},
    "control_legend_profile": set(),
}

_PROFILE_NOTE_TOKENS = {
    "riser_profile": ("riser", "vertical", "backbone", "trunk", "branch"),
    "rack_detail_profile": ("rack", "patch panel", "runway", "ladder", "cabinet"),
    "equipment_room_profile": ("idf", "mdf", "equipment room", "rack", "runway"),
    "detail_installation_profile": ("j-hook", "ladder", "support", "pathway", "termination"),
    "mixed_detail_profile": ("riser", "rack", "pathway", "detail", "installation"),
}

_CLASS_NOTE_TOKENS = {
    "riser_endpoint": ("riser", "trunk", "backbone"),
    "ladder_rack_cable_runway": ("ladder", "runway", "pathway"),
    "j_hook_pathway_symbol": ("j-hook", "pathway", "support"),
    "patch_panel_row": ("patch panel", "rack"),
    "equipment_rack_front": ("rack", "cabinet"),
}

_PROFILE_RELATION_DISTANCE_MAX = {
    "riser_profile": 0.62,
    "rack_detail_profile": 0.44,
    "equipment_room_profile": 0.50,
    "detail_installation_profile": 0.46,
    "mixed_detail_profile": 0.52,
}

_PROFILE_RELATION_MIN_SCORE = {
    "riser_profile": 0.72,
    "rack_detail_profile": 0.74,
    "equipment_room_profile": 0.74,
    "detail_installation_profile": 0.73,
    "mixed_detail_profile": 0.75,
}

_PROFILE_ENDPOINT_MIN_SCORE = {
    "riser_profile": 0.68,
    "rack_detail_profile": 0.70,
    "equipment_room_profile": 0.70,
    "detail_installation_profile": 0.69,
    "mixed_detail_profile": 0.72,
    "plan_body_profile": 0.84,
    "control_legend_profile": 1.0,
}

_STRUCTURAL_PROFILES = {
    "riser_profile",
    "rack_detail_profile",
    "equipment_room_profile",
    "detail_installation_profile",
    "mixed_detail_profile",
}


def _append_capped(samples: list[dict[str, Any]], row: dict[str, Any], cap: int = 64) -> None:
    if len(samples) < cap:
        samples.append(row)


def _detail_locality_match(left: SiteSchematicTopologyEndpoint, right: SiteSchematicTopologyEndpoint) -> bool:
    if left.detail_region_id and right.detail_region_id and left.detail_region_id == right.detail_region_id:
        return True
    if left.subregion_id and right.subregion_id and left.subregion_id == right.subregion_id:
        return True
    if left.pseudo_page_id and right.pseudo_page_id and left.pseudo_page_id == right.pseudo_page_id:
        return True
    if left.region_id and right.region_id and left.region_id == right.region_id:
        return True
    return False


def _infer_topology_detector_class(*, token: str, text: str, profile_id: str) -> str:
    token_upper = token.upper().strip()
    text_upper = text.upper().strip()
    in_riserish = profile_id in {"riser_profile", "mixed_detail_profile"}
    in_rackish = profile_id in {"rack_detail_profile", "equipment_room_profile", "detail_installation_profile"}
    if token_upper in {"RIS", "RISER"} and in_riserish:
        return "riser_endpoint"
    if token_upper in {"PP", "PATCH", "PATCH PANEL"} and (in_riserish or in_rackish):
        return "patch_panel_row"
    if token_upper in {"LADDER", "RUNWAY", "RW"} and (in_riserish or in_rackish):
        return "ladder_rack_cable_runway"
    if token_upper in {"J-HOOK", "JHOOK", "JH"} and profile_id in {"detail_installation_profile", "riser_profile", "mixed_detail_profile"}:
        return "j_hook_pathway_symbol"
    if token_upper in {"RACK", "CAB"} and in_rackish:
        return "equipment_rack_front"
    if token_upper in {"JACK"} and profile_id in {"detail_installation_profile", "riser_profile", "plan_body_profile"}:
        return "telecomm_jack_tag"
    if "PATCH PANEL" in text_upper and (in_riserish or in_rackish):
        return "patch_panel_row"
    if "LADDER" in text_upper and (in_riserish or in_rackish):
        return "ladder_rack_cable_runway"
    if "J-HOOK" in text_upper and profile_id in {"detail_installation_profile", "riser_profile", "mixed_detail_profile"}:
        return "j_hook_pathway_symbol"
    return ""


def _center(bbox: tuple[float, float, float, float] | None) -> tuple[float, float] | None:
    if bbox is None:
        return None
    x0, y0, x1, y1 = bbox
    return ((float(x0) + float(x1)) / 2.0, (float(y0) + float(y1)) / 2.0)


def _distance(a: tuple[float, float] | None, b: tuple[float, float] | None) -> float:
    if a is None or b is None:
        return 1.0
    return hypot(a[0] - b[0], a[1] - b[1])


def _normalized_center(
    bbox: tuple[float, float, float, float] | None,
    *,
    scale_x: float,
    scale_y: float,
) -> tuple[float, float] | None:
    c = _center(bbox)
    if c is None:
        return None
    sx = max(scale_x, 1.0)
    sy = max(scale_y, 1.0)
    if sx <= 1.5 and sy <= 1.5:
        return c
    return (c[0] / sx, c[1] / sy)


def build_topology_for_page(
    *,
    page_index: int,
    sheet_type: str,
    symbol_instances: tuple[SiteSchematicSymbolInstance, ...],
    symbol_links: tuple[SiteSchematicSymbolLink, ...],
    note_clauses: tuple[str, ...],
    vector_graph_diagnostics: dict[str, Any] | None = None,
) -> tuple[
    tuple[SiteSchematicTopologyEndpoint, ...],
    tuple[SiteSchematicTopologyRelation, ...],
    tuple[SiteSchematicTopologySegment, ...],
    tuple[SiteSchematicRiserEdge, ...],
    dict[str, Any],
]:
    links_by_instance = {row.instance_id: row for row in symbol_links}
    symbols_by_id = {row.instance_id: row for row in symbol_instances}
    bbox_x_max = max((float(row.bbox[2]) for row in symbol_instances if row.bbox), default=1.0)
    bbox_y_max = max((float(row.bbox[3]) for row in symbol_instances if row.bbox), default=1.0)
    center_by_symbol_id = {
        row.instance_id: _normalized_center(row.bbox, scale_x=bbox_x_max, scale_y=bbox_y_max)
        for row in symbol_instances
    }
    note_text = " ".join(note_clauses).lower()
    endpoints: list[SiteSchematicTopologyEndpoint] = []
    endpoint_by_symbol: dict[str, SiteSchematicTopologyEndpoint] = {}
    diagnostics = {
        "profile_endpoint_counts": Counter(),
        "profile_relation_counts": Counter(),
        "profile_abstain_counts": Counter(),
        "endpoint_bridge_promotions": Counter(),
        "accepted_endpoint_samples": [],
        "rejected_endpoint_samples": [],
        "promoted_endpoint_samples": [],
        "accepted_relation_samples": [],
        "rejected_relation_samples": [],
    }
    for idx, symbol in enumerate(symbol_instances, start=1):
        metadata = dict(symbol.metadata or {})
        detector_class_id = str(metadata.get("detector_class_id", "")).strip()
        profile_id = str(metadata.get("detector_profile_id", "")).strip()
        if not profile_id:
            profile_id, _ = select_profile_for_context(
                sheet_type=sheet_type,
                region_kind=str(metadata.get("region_kind", "")),
                detail_kind=str(metadata.get("detail_kind", "")),
                subregion_role=str(metadata.get("subregion_role", "")),
                pseudo_role=str(metadata.get("pseudo_page_role", "")),
                local_text=symbol.text,
            )
        derived_detector_class_id = ""
        if not detector_class_id:
            derived_detector_class_id = _infer_topology_detector_class(
                token=symbol.token,
                text=symbol.text,
                profile_id=profile_id,
            )
            detector_class_id = derived_detector_class_id
        endpoint_kind = _TOPOLOGY_CLASS_TO_KIND.get(detector_class_id)
        if not endpoint_kind:
            continue
        allowed_classes = set(_PROFILE_ALLOWED_CLASSES.get(profile_id, set()))
        link = links_by_instance.get(symbol.instance_id)
        link_confidence = link.confidence if link else 0.0
        has_legend = bool(link and link.legend_entry_id)
        profile_tokens = _PROFILE_NOTE_TOKENS.get(profile_id, ())
        class_tokens = _CLASS_NOTE_TOKENS.get(detector_class_id, ())
        profile_note_support = any(token in note_text for token in profile_tokens)
        class_note_support = any(token in note_text for token in class_tokens)
        note_support = profile_note_support or class_note_support
        link_status = str(link.status if link else "missing").strip()
        in_context_region = str(metadata.get("region_kind", "")).strip() in {
            "riser_region",
            "equipment_room_region",
            "detail_region",
            "installation_region",
        }
        in_context_pseudo = str(metadata.get("pseudo_page_role", "")).strip() in {
            "riser",
            "rack",
            "equipment_room",
            "installation_detail",
        }
        evidence_score = 0.0
        evidence_reasons: list[str] = []
        evidence_score += symbol.confidence * 0.55
        if link:
            evidence_score += link_confidence * 0.3
        if detector_class_id in allowed_classes:
            evidence_score += 0.16
            evidence_reasons.append("profile_allowed_class")
        else:
            evidence_score -= 0.24
            evidence_reasons.append("profile_disallowed_class")
        if link_status == "linked":
            evidence_score += 0.14
            evidence_reasons.append("linked_symbol")
        elif link_status == "weakly_linked":
            evidence_score += 0.06
            evidence_reasons.append("weakly_linked_symbol")
        elif link_status in {"detected_but_unmapped", "unresolved", "conflicting"}:
            evidence_score -= 0.05
            evidence_reasons.append(f"link_status:{link_status}")
        if has_legend:
            evidence_score += 0.05
            evidence_reasons.append("legend_support")
        if note_support:
            evidence_score += 0.07
            evidence_reasons.append("note_support")
        if in_context_region or in_context_pseudo:
            evidence_score += 0.05
            evidence_reasons.append("region_or_pseudo_context")
        confidence = max(0.05, min(0.97, evidence_score))
        min_score = _PROFILE_ENDPOINT_MIN_SCORE.get(profile_id, 0.78)
        strong_grounding = link_status in {"linked", "weakly_linked"} and link_confidence >= 0.55
        structural_promotion = (
            profile_id in _STRUCTURAL_PROFILES
            and detector_class_id in allowed_classes
            and note_support
            and symbol.confidence >= 0.78
            and confidence >= (min_score - 0.02)
            and link_status in {"detected_but_unmapped", "unresolved", "weakly_linked", "linked"}
        )
        strong_context = note_support and (in_context_region or in_context_pseudo or structural_promotion)
        if structural_promotion:
            evidence_reasons.append("structural_profile_context_support")
        status = (
            "inferred"
            if confidence >= min_score
            and detector_class_id in allowed_classes
            and (strong_grounding or strong_context)
            else "unresolved"
        )
        if status == "unresolved":
            diagnostics["profile_abstain_counts"][profile_id] += 1
            _append_capped(
                diagnostics["rejected_endpoint_samples"],
                {
                    "symbol_instance_id": symbol.instance_id,
                    "profile_id": profile_id,
                    "detector_class_id": detector_class_id,
                    "score": round(confidence, 4),
                    "min_score": min_score,
                    "link_status": link_status,
                    "reasons": evidence_reasons,
                },
            )
            if confidence < 0.48:
                continue
        endpoint = SiteSchematicTopologyEndpoint(
            endpoint_id=f"topo_ep:p{page_index}:{idx}",
            page_index=page_index,
            profile_id=profile_id,
            endpoint_kind=endpoint_kind,
            detector_class_id=detector_class_id,
            symbol_instance_ids=(symbol.instance_id,),
            region_id=symbol.region_id,
            detail_region_id=str(metadata.get("detail_region_id", "")),
            subregion_id=str(metadata.get("subregion_id", "")),
            pseudo_page_id=symbol.pseudo_page_id or str(metadata.get("pseudo_page_id", "")),
            confidence=round(confidence, 4),
            status=status,
            metadata={
                "sheet_type": sheet_type,
                "link_status": link_status,
                "legend_entry_id": link.legend_entry_id if link else "",
                "has_note_support": note_support,
                "profile_note_support": profile_note_support,
                "class_note_support": class_note_support,
                "in_context_region": in_context_region,
                "in_context_pseudo": in_context_pseudo,
                "structural_promotion": structural_promotion,
                "evidence_score": round(confidence, 4),
                "evidence_reasons": tuple(evidence_reasons),
                "derived_detector_class_id": derived_detector_class_id,
            },
        )
        endpoints.append(endpoint)
        endpoint_by_symbol[symbol.instance_id] = endpoint
        diagnostics["profile_endpoint_counts"][profile_id] += 1
        _append_capped(
            diagnostics["accepted_endpoint_samples"],
            {
                "endpoint_id": endpoint.endpoint_id,
                "symbol_instance_id": symbol.instance_id,
                "profile_id": profile_id,
                "detector_class_id": detector_class_id,
                "derived_detector_class_id": derived_detector_class_id,
                "status": status,
                "score": round(confidence, 4),
                "link_status": link_status,
                "reasons": evidence_reasons,
            },
        )

    # Targeted micro-pass: detail_installation grounding/topology bridge promotions.
    promoted_endpoints: list[SiteSchematicTopologyEndpoint] = []
    install_support_endpoints = [
        row
        for row in endpoints
        if row.profile_id == "detail_installation_profile"
        and row.status == "inferred"
        and row.endpoint_kind in {"pathway_support", "pathway_runway"}
    ]
    for endpoint in endpoints:
        if (
            endpoint.profile_id != "detail_installation_profile"
            or endpoint.status == "inferred"
            or endpoint.endpoint_kind != "termination_point"
        ):
            promoted_endpoints.append(endpoint)
            continue
        metadata = dict(endpoint.metadata or {})
        if not bool(metadata.get("has_note_support", False)):
            promoted_endpoints.append(endpoint)
            continue
        if metadata.get("link_status", "") not in {"detected_but_unmapped", "weakly_linked", "linked"}:
            promoted_endpoints.append(endpoint)
            continue
        if float(endpoint.confidence) < 0.64:
            promoted_endpoints.append(endpoint)
            continue
        endpoint_symbol_id = endpoint.symbol_instance_ids[0] if endpoint.symbol_instance_ids else ""
        endpoint_center = center_by_symbol_id.get(endpoint_symbol_id) if endpoint_symbol_id else None
        nearby_support: list[tuple[str, float]] = []
        for support in install_support_endpoints:
            if not _detail_locality_match(endpoint, support):
                continue
            support_symbol_id = support.symbol_instance_ids[0] if support.symbol_instance_ids else ""
            support_center = center_by_symbol_id.get(support_symbol_id) if support_symbol_id else None
            dist = _distance(endpoint_center, support_center)
            if dist <= 0.34:
                nearby_support.append((support.endpoint_id, round(dist, 4)))
        if not nearby_support:
            promoted_endpoints.append(endpoint)
            continue
        reason_codes = list(metadata.get("evidence_reasons", ()))
        if "detail_installation_topology_bridge" not in reason_codes:
            reason_codes.append("detail_installation_topology_bridge")
        promoted = SiteSchematicTopologyEndpoint(
            endpoint_id=endpoint.endpoint_id,
            page_index=endpoint.page_index,
            profile_id=endpoint.profile_id,
            endpoint_kind=endpoint.endpoint_kind,
            detector_class_id=endpoint.detector_class_id,
            symbol_instance_ids=endpoint.symbol_instance_ids,
            region_id=endpoint.region_id,
            detail_region_id=endpoint.detail_region_id,
            subregion_id=endpoint.subregion_id,
            pseudo_page_id=endpoint.pseudo_page_id,
            confidence=endpoint.confidence,
            status="inferred",
            metadata={
                **metadata,
                "evidence_reasons": tuple(reason_codes),
                "grounding_topology_bridge_rule": "detail_installation_termination_locality_bridge_v1",
                "bridge_support_endpoint_ids": tuple(endpoint_id for endpoint_id, _ in nearby_support[:4]),
                "bridge_min_distance": min(dist for _, dist in nearby_support),
                "bridge_locality_confirmed": True,
                "bridge_promoted_from_status": endpoint.status,
            },
        )
        promoted_endpoints.append(promoted)
        diagnostics["endpoint_bridge_promotions"]["detail_installation_profile"] += 1
        _append_capped(
            diagnostics["promoted_endpoint_samples"],
            {
                "endpoint_id": promoted.endpoint_id,
                "profile_id": promoted.profile_id,
                "detector_class_id": promoted.detector_class_id,
                "bridge_rule": "detail_installation_termination_locality_bridge_v1",
                "score": promoted.confidence,
                "support_endpoint_ids": [endpoint_id for endpoint_id, _ in nearby_support[:4]],
                "min_distance": min(dist for _, dist in nearby_support),
            },
        )
    endpoints = promoted_endpoints

    relations: list[SiteSchematicTopologyRelation] = []
    segments: list[SiteSchematicTopologySegment] = []
    riser_edges: list[SiteSchematicRiserEdge] = []
    endpoint_pairs_by_profile: dict[str, list[SiteSchematicTopologyEndpoint]] = defaultdict(list)
    for row in endpoints:
        endpoint_pairs_by_profile[row.profile_id].append(row)
    relation_idx = 0
    for profile_id, rows in endpoint_pairs_by_profile.items():
        for left_idx in range(len(rows)):
            left = rows[left_idx]
            for right in rows[left_idx + 1 :]:
                dist = _distance(
                    center_by_symbol_id.get(left.symbol_instance_ids[0]) if left.symbol_instance_ids else None,
                    center_by_symbol_id.get(right.symbol_instance_ids[0]) if right.symbol_instance_ids else None,
                )
                relation_kind = ""
                if profile_id == "riser_profile" and {"riser_endpoint", "pathway_runway"} & {left.endpoint_kind, right.endpoint_kind}:
                    relation_kind = "riser_continuity"
                elif profile_id in {"rack_detail_profile", "equipment_room_profile"} and {"rack_component", "pathway_runway"} & {left.endpoint_kind, right.endpoint_kind}:
                    relation_kind = "rack_connectivity"
                elif profile_id == "detail_installation_profile" and {"pathway_support", "termination_point"} & {left.endpoint_kind, right.endpoint_kind}:
                    relation_kind = "pathway_attachment"
                elif profile_id == "mixed_detail_profile" and {"riser_endpoint", "rack_component", "pathway_runway"} & {left.endpoint_kind, right.endpoint_kind}:
                    relation_kind = "mixed_detail_continuity"
                if not relation_kind:
                    continue
                relation_score = (left.confidence + right.confidence) / 2.0
                relation_reasons = [f"relation_kind:{relation_kind}"]
                class_pair = {left.detector_class_id, right.detector_class_id}
                if left.region_id and right.region_id and left.region_id == right.region_id:
                    relation_score += 0.08
                    relation_reasons.append("same_region")
                if left.pseudo_page_id and right.pseudo_page_id and left.pseudo_page_id == right.pseudo_page_id:
                    relation_score += 0.07
                    relation_reasons.append("same_pseudo_page")
                if _detail_locality_match(left, right):
                    relation_score += 0.05
                    relation_reasons.append("same_detail_locality")
                if dist <= 0.2:
                    relation_score += 0.12
                    relation_reasons.append("very_close")
                elif dist <= 0.35:
                    relation_score += 0.06
                    relation_reasons.append("close")
                profile_note_support = any(token in note_text for token in _PROFILE_NOTE_TOKENS.get(profile_id, ()))
                if profile_note_support:
                    relation_score += 0.05
                    relation_reasons.append("profile_note_support")
                detail_bridge_ok = False
                if profile_id == "detail_installation_profile":
                    relation_pair_compatible = (
                        {"j_hook_pathway_symbol", "ladder_rack_cable_runway"} & class_pair
                        and {"telecomm_jack_tag", "data_outlet"} & class_pair
                    )
                    if relation_pair_compatible:
                        relation_score += 0.06
                        relation_reasons.append("detail_installation_family_compatible")
                    legend_support = bool((left.metadata or {}).get("legend_entry_id")) or bool((right.metadata or {}).get("legend_entry_id"))
                    note_support = bool((left.metadata or {}).get("has_note_support")) and bool((right.metadata or {}).get("has_note_support"))
                    detail_bridge_ok = relation_pair_compatible and note_support and (_detail_locality_match(left, right) or legend_support)
                    if detail_bridge_ok:
                        relation_score += 0.05
                        relation_reasons.append("detail_installation_grounding_bridge")
                max_dist = _PROFILE_RELATION_DISTANCE_MAX.get(profile_id, 0.45)
                min_rel_score = _PROFILE_RELATION_MIN_SCORE.get(profile_id, 0.76)
                confidence = max(0.1, min(0.95, relation_score))
                status = (
                    "inferred"
                    if confidence >= min_rel_score
                    and dist <= max_dist
                    and left.status == "inferred"
                    and right.status == "inferred"
                    and (profile_id != "detail_installation_profile" or detail_bridge_ok)
                    else "unresolved"
                )
                relation_idx += 1
                relation = SiteSchematicTopologyRelation(
                    relation_id=f"topo_rel:p{page_index}:{relation_idx}",
                    page_index=page_index,
                    profile_id=profile_id,
                    relation_kind=relation_kind,
                    source_endpoint_id=left.endpoint_id,
                    target_endpoint_id=right.endpoint_id,
                    confidence=round(confidence, 4),
                    status=status,
                    metadata={
                        "distance": round(dist, 4),
                        "distance_max": max_dist,
                        "min_relation_score": min_rel_score,
                        "left_kind": left.endpoint_kind,
                        "right_kind": right.endpoint_kind,
                        "left_detector_class_id": left.detector_class_id,
                        "right_detector_class_id": right.detector_class_id,
                        "profile_note_support": profile_note_support,
                        "detail_installation_bridge_ok": detail_bridge_ok,
                        "relation_reasons": tuple(relation_reasons),
                    },
                )
                relations.append(relation)
                diagnostics["profile_relation_counts"][profile_id] += 1
                if status != "inferred":
                    diagnostics["profile_abstain_counts"][profile_id] += 1
                    _append_capped(
                        diagnostics["rejected_relation_samples"],
                        {
                            "relation_id": relation.relation_id,
                            "profile_id": profile_id,
                            "relation_kind": relation_kind,
                            "score": round(confidence, 4),
                            "min_score": min_rel_score,
                            "distance": round(dist, 4),
                            "distance_max": max_dist,
                            "reasons": relation_reasons,
                            "left_endpoint_id": left.endpoint_id,
                            "right_endpoint_id": right.endpoint_id,
                        },
                    )
                if status == "inferred":
                    _append_capped(
                        diagnostics["accepted_relation_samples"],
                        {
                            "relation_id": relation.relation_id,
                            "profile_id": profile_id,
                            "relation_kind": relation_kind,
                            "score": round(confidence, 4),
                            "distance": round(dist, 4),
                            "left_endpoint_id": left.endpoint_id,
                            "right_endpoint_id": right.endpoint_id,
                            "reasons": relation_reasons,
                        },
                    )
                    segments.append(
                        SiteSchematicTopologySegment(
                            segment_id=f"topo_seg:p{page_index}:{relation_idx}",
                            page_index=page_index,
                            text=f"{relation_kind}:{left.endpoint_kind}->{right.endpoint_kind}",
                            confidence=round(confidence, 4),
                            status="inferred",
                            metadata={
                                "profile_id": profile_id,
                                "source_endpoint_id": left.endpoint_id,
                                "target_endpoint_id": right.endpoint_id,
                                "relation_kind": relation_kind,
                            },
                        )
                    )
                    if relation_kind in {"riser_continuity", "mixed_detail_continuity"} and (
                        left.detector_class_id == "riser_endpoint" or right.detector_class_id == "riser_endpoint"
                    ):
                        riser_edges.append(
                            SiteSchematicRiserEdge(
                                edge_id=f"riser_topo:p{page_index}:{relation_idx}",
                                page_index=page_index,
                                source_label=left.detector_class_id,
                                target_label=right.detector_class_id,
                                medium="inferred_pathway",
                                confidence=round(confidence, 4),
                                status="inferred",
                                metadata={
                                    "profile_id": profile_id,
                                    "source_endpoint_id": left.endpoint_id,
                                    "target_endpoint_id": right.endpoint_id,
                                    "relation_kind": relation_kind,
                                },
                            )
                        )
    diagnostics_dict = {
        "profile_endpoint_counts": dict(diagnostics["profile_endpoint_counts"]),
        "profile_relation_counts": dict(diagnostics["profile_relation_counts"]),
        "profile_abstain_counts": dict(diagnostics["profile_abstain_counts"]),
        "endpoint_bridge_promotions": dict(diagnostics["endpoint_bridge_promotions"]),
        "accepted_endpoint_samples": diagnostics["accepted_endpoint_samples"],
        "rejected_endpoint_samples": diagnostics["rejected_endpoint_samples"],
        "promoted_endpoint_samples": diagnostics["promoted_endpoint_samples"],
        "accepted_relation_samples": diagnostics["accepted_relation_samples"],
        "rejected_relation_samples": diagnostics["rejected_relation_samples"],
        "vector_leader_candidate_count": int((vector_graph_diagnostics or {}).get("leader_candidate_count", 0)),
        "vector_connector_candidate_count": int((vector_graph_diagnostics or {}).get("connector_candidate_count", 0)),
        "vector_dimension_candidate_count": int((vector_graph_diagnostics or {}).get("dimension_candidate_count", 0)),
    }
    return (
        tuple(endpoints),
        tuple(relations),
        tuple(segments),
        tuple(riser_edges),
        diagnostics_dict,
    )

