from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable

from orbitbrief_core.parser.site_schematic.models import (
    SiteSchematicAnchorReconciliationSuggestion,
    SiteSchematicConsistencyCheck,
    SiteSchematicContradictionFlag,
    SiteSchematicFamilyConsistencySummary,
    SiteSchematicGraph,
    SiteSchematicPacketReasoningSummary,
    SiteSchematicProfileQASummary,
    SiteSchematicReasoningFinding,
    SiteSchematicReviewQueueSummary,
    SiteSchematicSymbolInstance,
    SiteSchematicSymbolLink,
    SiteSchematicTopologyEndpoint,
    SiteSchematicTopologyRelation,
    SiteSchematicTopologyCoverageSummary,
    SiteSchematicTopologyReviewSuggestion,
)


def _clean(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _norm_key(link: SiteSchematicSymbolLink) -> str:
    if link.legend_label.strip():
        return _clean(link.legend_label).lower()
    if link.symbol_token.strip():
        return _clean(link.symbol_token).lower()
    return "unknown"


def _edge_ids_for_nodes(graph: SiteSchematicGraph, node_ids: Iterable[str]) -> tuple[str, ...]:
    node_set = set(node_ids)
    return tuple(
        edge.edge_id
        for edge in graph.edges
        if edge.source_node_id in node_set or edge.target_node_id in node_set
    )[:16]


_HIGH_PRESSURE_FAMILIES = {
    "data_outlet",
    "riser_endpoint",
    "telecomm_jack_tag",
    "patch_panel_row",
}

_TOPOLOGY_PRESSURE_FAMILIES = _HIGH_PRESSURE_FAMILIES | {
    "ladder_rack_cable_runway",
    "equipment_rack_front",
    "j_hook_pathway_symbol",
}

_STRUCTURAL_PROFILES = {
    "riser_profile",
    "rack_detail_profile",
    "equipment_room_profile",
    "detail_installation_profile",
    "mixed_detail_profile",
}

_PROFILE_INCOMPATIBLE_BY_FAMILY: dict[str, set[str]] = {
    "data_outlet": {"riser_profile", "rack_detail_profile"},
    "riser_endpoint": {"control_legend_profile", "plan_body_profile"},
    "telecomm_jack_tag": {"riser_profile"},
    "patch_panel_row": {"plan_body_profile", "control_legend_profile"},
}

_EXPECTED_RELATION_KINDS_BY_FAMILY: dict[str, set[str]] = {
    "riser_endpoint": {"riser_continuity", "mixed_detail_continuity"},
    "patch_panel_row": {"rack_connectivity", "mixed_detail_continuity"},
    "equipment_rack_front": {"rack_connectivity", "mixed_detail_continuity"},
    "ladder_rack_cable_runway": {"rack_connectivity", "pathway_attachment", "mixed_detail_continuity", "riser_continuity"},
    "j_hook_pathway_symbol": {"pathway_attachment", "mixed_detail_continuity"},
    "telecomm_jack_tag": {"pathway_attachment", "mixed_detail_continuity"},
    "data_outlet": {"pathway_attachment", "mixed_detail_continuity"},
}

_RELATION_KIND_COMPATIBLE_FAMILIES: dict[str, set[str]] = {
    "pathway_attachment": {
        "telecomm_jack_tag",
        "data_outlet",
        "j_hook_pathway_symbol",
        "ladder_rack_cable_runway",
    },
    "riser_continuity": {"riser_endpoint", "ladder_rack_cable_runway"},
    "rack_connectivity": {"patch_panel_row", "equipment_rack_front", "ladder_rack_cable_runway"},
    "termination_attachment": {"telecomm_jack_tag", "data_outlet", "patch_panel_row"},
}

_RELATION_KIND_INCOMPATIBLE_FAMILIES: dict[str, set[str]] = {
    "pathway_attachment": {"patch_panel_row", "equipment_rack_front", "riser_endpoint"},
    "riser_continuity": {"data_outlet", "door_contact_marker", "j_hook_pathway_symbol"},
    "rack_connectivity": {"data_outlet", "door_contact_marker"},
    "termination_attachment": {"riser_endpoint", "equipment_rack_front"},
}


def _family_for_instance(
    symbol_by_id: dict[str, SiteSchematicSymbolInstance],
    instance_id: str,
    endpoint_ids_by_symbol: dict[str, list[str]] | None = None,
    endpoint_by_id: dict[str, SiteSchematicTopologyEndpoint] | None = None,
) -> str:
    symbol = symbol_by_id.get(instance_id)
    family = str((symbol.metadata or {}).get("detector_class_id", "")).strip() if symbol is not None else ""
    if family:
        return family
    if endpoint_ids_by_symbol is None or endpoint_by_id is None:
        return ""
    endpoint_families = [
        str(endpoint_by_id[endpoint_id].detector_class_id).strip()
        for endpoint_id in endpoint_ids_by_symbol.get(instance_id, ())
        if endpoint_by_id.get(endpoint_id) is not None and str(endpoint_by_id[endpoint_id].detector_class_id).strip()
    ]
    if not endpoint_families:
        return ""
    inferred_endpoint_families = [
        str(endpoint_by_id[endpoint_id].detector_class_id).strip()
        for endpoint_id in endpoint_ids_by_symbol.get(instance_id, ())
        if endpoint_by_id.get(endpoint_id) is not None
        and endpoint_by_id[endpoint_id].status == "inferred"
        and str(endpoint_by_id[endpoint_id].detector_class_id).strip()
    ]
    fam_counts = Counter(inferred_endpoint_families or endpoint_families)
    return fam_counts.most_common(1)[0][0] if fam_counts else ""


def _priority_score(
    *,
    status: str,
    severity: str,
    confidence: float,
    family: str,
    page_span: int,
    topology_support: bool,
) -> float:
    score = confidence * 60.0
    score += 12.0 if severity == "high" else (6.0 if severity == "medium" else 2.0)
    score += min(15.0, page_span * 2.5)
    if family in _HIGH_PRESSURE_FAMILIES:
        score += 12.0
    if topology_support:
        score += 5.0
    if status == "contradicted":
        score += 14.0
    elif status == "supported":
        score -= 10.0
    return round(max(0.0, min(100.0, score)), 2)


def _triage_bucket(
    *,
    status: str,
    severity: str,
    priority_score: float,
    family: str,
) -> str:
    if status == "contradicted" and priority_score >= 72:
        return "contradiction_high_confidence"
    if status == "abstained":
        return "ambiguity_needs_review"
    if status == "ambiguous":
        return "ambiguity_needs_review" if priority_score >= 45 else "low_priority_review"
    if status == "supported":
        return "informational_supported"
    if status in {"needs_review", "ambiguous"}:
        if priority_score >= 62:
            return "high_priority_review"
        if severity == "high" and priority_score >= 56:
            return "high_priority_review"
        if family in _TOPOLOGY_PRESSURE_FAMILIES and priority_score >= 54:
            return "high_priority_review"
        if priority_score >= 48 or severity == "high":
            return "medium_priority_review"
        return "low_priority_review"
    return "low_priority_review"


def _family_reconciliation_hint(family: str) -> str:
    if family == "data_outlet":
        return "review local legend grounding and verify anchor scope in plan-vs-riser context"
    if family == "riser_endpoint":
        return "inspect topology continuity and riser context alignment"
    if family == "telecomm_jack_tag":
        return "verify packet-local token interpretation and nearby legend entry"
    if family == "patch_panel_row":
        return "inspect rack/detail context and cross-page patch-panel consistency"
    if family == "ladder_rack_cable_runway":
        return "inspect rack/pathway continuity and attachment interpretation"
    if family == "equipment_rack_front":
        return "verify rack-front grounding against rack connectivity evidence"
    if family == "j_hook_pathway_symbol":
        return "inspect installation-detail pathway/support interpretation"
    return "inspect local legend/note/topology context"


def _anchor_grounding_tier(link: SiteSchematicSymbolLink) -> tuple[str, bool]:
    metadata = dict(link.metadata or {})
    strengthened = bool(metadata.get("grounding_strengthened", False))
    if strengthened:
        return "strong", True
    if link.status == "linked" and link.confidence >= 0.72:
        return "strong", False
    if link.status == "weakly_linked" and link.confidence >= 0.76:
        return "strong", False
    return "mixed", False


def build_bounded_graph_reasoning(
    *,
    graph: SiteSchematicGraph,
    symbol_instances: tuple[SiteSchematicSymbolInstance, ...],
    symbol_links: tuple[SiteSchematicSymbolLink, ...],
    topology_endpoints: tuple[SiteSchematicTopologyEndpoint, ...],
    topology_relations: tuple[SiteSchematicTopologyRelation, ...],
) -> tuple[
    tuple[SiteSchematicReasoningFinding, ...],
    tuple[SiteSchematicConsistencyCheck, ...],
    tuple[SiteSchematicContradictionFlag, ...],
    tuple[SiteSchematicAnchorReconciliationSuggestion, ...],
    tuple[SiteSchematicTopologyReviewSuggestion, ...],
    dict[str, object],
]:
    findings: list[SiteSchematicReasoningFinding] = []
    anchor_suggestions: list[SiteSchematicAnchorReconciliationSuggestion] = []
    topology_suggestions: list[SiteSchematicTopologyReviewSuggestion] = []
    symbol_by_id = {row.instance_id: row for row in symbol_instances}
    links_by_instance = {row.instance_id: row for row in symbol_links}
    endpoint_by_id = {row.endpoint_id: row for row in topology_endpoints}
    relation_by_id = {row.relation_id: row for row in topology_relations}
    endpoint_ids_by_symbol: dict[str, list[str]] = defaultdict(list)
    for endpoint in topology_endpoints:
        for symbol_id in endpoint.symbol_instance_ids:
            endpoint_ids_by_symbol[symbol_id].append(endpoint.endpoint_id)
    relation_ids_by_symbol: dict[str, list[str]] = defaultdict(list)
    for relation in topology_relations:
        src = endpoint_by_id.get(relation.source_endpoint_id)
        dst = endpoint_by_id.get(relation.target_endpoint_id)
        for endpoint in (src, dst):
            if endpoint is None:
                continue
            for symbol_id in endpoint.symbol_instance_ids:
                relation_ids_by_symbol[symbol_id].append(relation.relation_id)

    # A) Cross-page agreement / disagreement checks.
    grouped_links: dict[str, list[SiteSchematicSymbolLink]] = defaultdict(list)
    for row in symbol_links:
        grouped_links[_norm_key(row)].append(row)
    idx = 0
    for key, rows in grouped_links.items():
        pages = sorted({row.page_index for row in rows})
        if len(pages) < 2:
            continue
        statuses = {row.status for row in rows}
        symbol_node_ids = tuple(f"symbol:{row.instance_id}" for row in rows[:8])
        edge_ids = _edge_ids_for_nodes(graph, symbol_node_ids)
        family_counts = Counter(_family_for_instance(symbol_by_id, row.instance_id) for row in rows)
        if not family_counts or not next(iter(family_counts.keys()), "").strip():
            family_counts = Counter(
                _family_for_instance(
                    symbol_by_id,
                    row.instance_id,
                    endpoint_ids_by_symbol=endpoint_ids_by_symbol,
                    endpoint_by_id=endpoint_by_id,
                )
                for row in rows
            )
        top_family, top_family_count = family_counts.most_common(1)[0] if family_counts else ("", 0)
        legend_ids = {row.legend_entry_id for row in rows if row.legend_entry_id}
        high_conf_linked = [row for row in rows if row.status == "linked" and row.confidence >= 0.68]
        high_conf_unmapped = [row for row in rows if row.status in {"detected_but_unmapped", "unresolved"} and row.confidence >= 0.6]
        strengthened_rows = [row for row in rows if bool((row.metadata or {}).get("grounding_strengthened", False))]
        strong_rows = [row for row in rows if _anchor_grounding_tier(row)[0] == "strong"]
        group_endpoint_ids = {
            endpoint_id
            for row in rows
            for endpoint_id in endpoint_ids_by_symbol.get(row.instance_id, ())
        }
        inferred_group_endpoint_ids = {
            endpoint_id
            for endpoint_id in group_endpoint_ids
            if endpoint_by_id.get(endpoint_id) is not None and endpoint_by_id[endpoint_id].status == "inferred"
        }
        group_relation_ids = {
            relation_id
            for row in rows
            for relation_id in relation_ids_by_symbol.get(row.instance_id, ())
        }
        inferred_group_relation_ids = {
            relation_id
            for relation_id in group_relation_ids
            if relation_by_id.get(relation_id) is not None and relation_by_id[relation_id].status == "inferred"
        }
        relation_kinds = {
            str(relation_by_id[relation_id].relation_kind).strip()
            for relation_id in inferred_group_relation_ids
            if relation_by_id.get(relation_id) is not None
        }
        incompatible_relation_kinds = {
            kind
            for kind in relation_kinds
            if top_family in _RELATION_KIND_INCOMPATIBLE_FAMILIES.get(kind, set())
        }
        profile_ids = sorted(
            {
                str((symbol_by_id.get(row.instance_id).metadata or {}).get("detector_profile_id", "")).strip()
                for row in rows
                if symbol_by_id.get(row.instance_id) is not None
            }
        )
        structural_profiles = tuple(sorted(profile for profile in profile_ids if profile in _STRUCTURAL_PROFILES))
        status = "supported"
        severity = "low"
        suggested = ""
        confidence = 0.78
        contradiction_reasons: list[str] = []
        if "conflicting" in statuses:
            contradiction_reasons.append("contains_conflicting_status")
        if len(legend_ids) >= 2 and top_family in _HIGH_PRESSURE_FAMILIES and len(high_conf_linked) >= 2:
            contradiction_reasons.append("high_pressure_multi_legend_disagreement")
        if {"linked", "detected_but_unmapped"}.issubset(statuses) and top_family in _HIGH_PRESSURE_FAMILIES and len(pages) >= 2:
            contradiction_reasons.append("high_pressure_cross_page_link_mismatch")
        if (
            top_family in _TOPOLOGY_PRESSURE_FAMILIES
            and inferred_group_endpoint_ids
            and {"linked", "detected_but_unmapped"}.issubset(statuses)
            and len(legend_ids) >= 2
        ):
            contradiction_reasons.append("topology_backed_cross_page_family_disagreement")
        if (
            top_family in _TOPOLOGY_PRESSURE_FAMILIES
            and inferred_group_relation_ids
            and structural_profiles
            and strong_rows
            and high_conf_unmapped
            and len(legend_ids) >= 1
        ):
            contradiction_reasons.append("topology_backed_structural_cross_page_mismatch")
        if (
            top_family in _TOPOLOGY_PRESSURE_FAMILIES
            and inferred_group_relation_ids
            and structural_profiles
            and strengthened_rows
            and incompatible_relation_kinds
            and high_conf_unmapped
        ):
            contradiction_reasons.append("strengthened_anchor_topology_backed_cross_page_mismatch")
        if contradiction_reasons:
            status = "contradicted"
            severity = "high"
            suggested = _family_reconciliation_hint(top_family)
            confidence = 0.84 if top_family in _HIGH_PRESSURE_FAMILIES else 0.8
            if inferred_group_relation_ids:
                confidence = max(confidence, 0.87)
        elif not statuses.issubset({"linked", "weakly_linked"}):
            status = "needs_review"
            severity = "medium"
            suggested = "review unmatched or unresolved cross-page anchors"
            confidence = 0.63
            if top_family in _TOPOLOGY_PRESSURE_FAMILIES and inferred_group_endpoint_ids:
                severity = "high"
                confidence = 0.72
                suggested = "inspect topology-backed cross-page anchor consistency for this family"
            if top_family in _TOPOLOGY_PRESSURE_FAMILIES and inferred_group_relation_ids and structural_profiles:
                severity = "high"
                confidence = max(confidence, 0.76)
                suggested = "review inferred structural continuity against cross-page family grounding"
        priority_score = _priority_score(
            status=status,
            severity=severity,
            confidence=confidence,
            family=top_family,
            page_span=len(pages),
            topology_support=bool(inferred_group_endpoint_ids or inferred_group_relation_ids),
        )
        triage_bucket = _triage_bucket(
            status=status,
            severity=severity,
            priority_score=priority_score,
            family=top_family,
        )
        idx += 1
        findings.append(
            SiteSchematicReasoningFinding(
                finding_id=f"reason:cross_page:{idx}",
                finding_type="cross_page_consistency",
                severity=severity,
                status=status,
                confidence=confidence,
                summary=f"Cross-page consistency check for '{key}' across pages {pages}.",
                triage_bucket=triage_bucket,
                priority_score=priority_score,
                evidence_node_ids=symbol_node_ids,
                evidence_edge_ids=edge_ids,
                evidence_symbol_instance_ids=tuple(row.instance_id for row in rows[:10]),
                evidence_topology_ids=tuple(sorted((inferred_group_endpoint_ids | inferred_group_relation_ids))[:10]),
                page_indices=tuple(pages),
                profile_ids=tuple(profile_ids),
                suggested_action=suggested,
                metadata={
                    "statuses": sorted(statuses),
                    "family_key": key,
                    "family": top_family,
                    "page_span": len(pages),
                    "family_count_in_group": top_family_count,
                    "contradiction_reasons": contradiction_reasons,
                    "strengthened_anchor_count": len(strengthened_rows),
                    "strong_anchor_count": len(strong_rows),
                    "inferred_topology_endpoint_count": len(inferred_group_endpoint_ids),
                    "inferred_topology_relation_count": len(inferred_group_relation_ids),
                    "inferred_topology_relation_kinds": sorted(relation_kinds),
                    "incompatible_relation_kinds": sorted(incompatible_relation_kinds),
                    "structural_profile_ids": list(structural_profiles),
                    "topology_evidence_tier": "strong_inferred" if inferred_group_relation_ids else ("mixed_inferred" if inferred_group_endpoint_ids else "none"),
                },
            )
        )

    # B) Anchor reconciliation suggestions.
    anchor_idx = 0
    for row in symbol_links[:220]:
        symbol = symbol_by_id.get(row.instance_id)
        if symbol is None:
            continue
        detector_class_id = str((symbol.metadata or {}).get("detector_class_id", "")).strip()
        profile_id = str((symbol.metadata or {}).get("detector_profile_id", "")).strip()
        endpoint_ids = tuple(endpoint_ids_by_symbol.get(row.instance_id, ()))
        inferred_endpoint_ids = tuple(
            endpoint_id
            for endpoint_id in endpoint_ids
            if endpoint_by_id.get(endpoint_id) is not None and endpoint_by_id[endpoint_id].status == "inferred"
        )
        unresolved_endpoint_ids = tuple(
            endpoint_id
            for endpoint_id in endpoint_ids
            if endpoint_by_id.get(endpoint_id) is not None and endpoint_by_id[endpoint_id].status != "inferred"
        )
        relation_ids = tuple(relation_ids_by_symbol.get(row.instance_id, ()))
        if not detector_class_id:
            detector_class_id = _family_for_instance(
                symbol_by_id,
                row.instance_id,
                endpoint_ids_by_symbol=endpoint_ids_by_symbol,
                endpoint_by_id=endpoint_by_id,
            )
        inferred_relation_ids = tuple(
            relation_id
            for relation_id in relation_ids
            if relation_by_id.get(relation_id) is not None and relation_by_id[relation_id].status == "inferred"
        )
        unresolved_relation_ids = tuple(
            relation_id
            for relation_id in relation_ids
            if relation_by_id.get(relation_id) is not None and relation_by_id[relation_id].status != "inferred"
        )
        needs_topology = detector_class_id in {
            "riser_endpoint",
            "patch_panel_row",
            "ladder_rack_cable_runway",
            "equipment_rack_front",
            "j_hook_pathway_symbol",
        }
        status = "supported"
        summary = "Anchor/legend evidence is consistent."
        confidence = 0.75
        contradiction_reasons: list[str] = []
        anchor_grounding_tier, anchor_strengthened = _anchor_grounding_tier(row)
        strong_anchor = anchor_grounding_tier == "strong"
        mixed_anchor = anchor_grounding_tier == "mixed"
        inferred_relations = [relation_by_id[relation_id] for relation_id in inferred_relation_ids if relation_by_id.get(relation_id) is not None]
        inferred_relation_kinds = {
            str(relation.relation_kind).strip()
            for relation in inferred_relations
            if str(relation.relation_kind).strip()
        }
        inferred_endpoint_ids_from_relations = {
            endpoint_id
            for relation in inferred_relations
            for endpoint_id in (relation.source_endpoint_id, relation.target_endpoint_id)
            if endpoint_by_id.get(endpoint_id) is not None
        }
        locality_region_ids = sorted(
            {
                endpoint_by_id[endpoint_id].region_id
                for endpoint_id in (set(endpoint_ids) | inferred_endpoint_ids_from_relations)
                if endpoint_by_id.get(endpoint_id) is not None and endpoint_by_id[endpoint_id].region_id
            }
        )
        locality_detail_region_ids = sorted(
            {
                endpoint_by_id[endpoint_id].detail_region_id
                for endpoint_id in (set(endpoint_ids) | inferred_endpoint_ids_from_relations)
                if endpoint_by_id.get(endpoint_id) is not None and endpoint_by_id[endpoint_id].detail_region_id
            }
        )
        locality_subregion_ids = sorted(
            {
                endpoint_by_id[endpoint_id].subregion_id
                for endpoint_id in (set(endpoint_ids) | inferred_endpoint_ids_from_relations)
                if endpoint_by_id.get(endpoint_id) is not None and endpoint_by_id[endpoint_id].subregion_id
            }
        )
        locality_pseudo_page_ids = sorted(
            {
                endpoint_by_id[endpoint_id].pseudo_page_id
                for endpoint_id in (set(endpoint_ids) | inferred_endpoint_ids_from_relations)
                if endpoint_by_id.get(endpoint_id) is not None and endpoint_by_id[endpoint_id].pseudo_page_id
            }
        )
        endpoint_legend_support = any(
            bool((endpoint_by_id.get(endpoint_id).metadata or {}).get("legend_entry_id", ""))
            for endpoint_id in (set(endpoint_ids) | inferred_endpoint_ids_from_relations)
            if endpoint_by_id.get(endpoint_id) is not None
        )
        endpoint_note_support = any(
            bool((endpoint_by_id.get(endpoint_id).metadata or {}).get("has_note_support", False))
            for endpoint_id in (set(endpoint_ids) | inferred_endpoint_ids_from_relations)
            if endpoint_by_id.get(endpoint_id) is not None
        )
        if row.status in {"weakly_linked", "detected_but_unmapped", "unresolved", "conflicting"} and mixed_anchor:
            status = "needs_review"
            summary = "Anchor has weak or unresolved symbol grounding."
            confidence = 0.58
            if row.status in {"conflicting"} and detector_class_id in _HIGH_PRESSURE_FAMILIES:
                contradiction_reasons.append("high_pressure_conflicting_link_status")
            if row.status == "detected_but_unmapped" and detector_class_id in _HIGH_PRESSURE_FAMILIES and row.confidence >= 0.6:
                contradiction_reasons.append("high_pressure_unmapped_with_confident_detection")
        elif needs_topology and not endpoint_ids:
            status = "ambiguous"
            summary = "Anchor is linked but topology continuity evidence is absent."
            confidence = 0.52
            if detector_class_id in _HIGH_PRESSURE_FAMILIES and profile_id in {"riser_profile", "rack_detail_profile", "equipment_room_profile"}:
                contradiction_reasons.append("high_pressure_missing_required_topology_support")
        incompatible_profiles = _PROFILE_INCOMPATIBLE_BY_FAMILY.get(detector_class_id, set())
        if (
            row.status == "linked"
            and row.confidence >= 0.72
            and profile_id in incompatible_profiles
            and strong_anchor
        ):
            contradiction_reasons.append("high_conf_link_in_profile_incompatible_family")
        expected_relation_kinds = _EXPECTED_RELATION_KINDS_BY_FAMILY.get(detector_class_id, set())
        if (
            detector_class_id in _TOPOLOGY_PRESSURE_FAMILIES
            and inferred_relation_kinds
            and expected_relation_kinds
            and inferred_relation_kinds.isdisjoint(expected_relation_kinds)
            and strong_anchor
        ):
            contradiction_reasons.append("inferred_topology_relation_incompatible_with_grounded_family")
        if (
            detector_class_id in _TOPOLOGY_PRESSURE_FAMILIES
            and inferred_relation_ids
            and mixed_anchor
            and profile_id in _STRUCTURAL_PROFILES
            and not contradiction_reasons
        ):
            status = "needs_review"
            summary = "Topology continuity is inferred but symbol grounding remains mixed."
            confidence = 0.74
            contradiction_reasons.append("topology_backed_mixed_grounding_requires_review")
        detail_inferred_pathway = (
            profile_id == "detail_installation_profile"
            and "pathway_attachment" in inferred_relation_kinds
            and bool(inferred_relation_ids)
        )
        if (
            detail_inferred_pathway
            and mixed_anchor
            and endpoint_note_support
            and (locality_detail_region_ids or locality_pseudo_page_ids)
        ):
            status = "needs_review"
            summary = "Inferred detail-installation pathway attachment is strong, but anchor grounding remains mixed."
            confidence = max(confidence, 0.78)
            if "detail_installation_inferred_pathway_mixed_grounding" not in contradiction_reasons:
                contradiction_reasons.append("detail_installation_inferred_pathway_mixed_grounding")
        incompatible_relation_kinds = {
            kind
            for kind in inferred_relation_kinds
            if detector_class_id in _RELATION_KIND_INCOMPATIBLE_FAMILIES.get(kind, set())
        }
        if (
            detail_inferred_pathway
            and incompatible_relation_kinds
            and strong_anchor
            and endpoint_note_support
            and (row.legend_entry_id or endpoint_legend_support)
            and (locality_detail_region_ids or locality_pseudo_page_ids)
        ):
            contradiction_reasons.append("detail_installation_inferred_relation_family_incompatible")
        if (
            anchor_strengthened
            and detail_inferred_pathway
            and incompatible_relation_kinds
            and strong_anchor
            and endpoint_note_support
            and (row.legend_entry_id or endpoint_legend_support)
            and (locality_detail_region_ids or locality_subregion_ids or locality_pseudo_page_ids)
        ):
            contradiction_reasons.append("detail_installation_strengthened_anchor_relation_incompatible")
        elif (
            detector_class_id in _TOPOLOGY_PRESSURE_FAMILIES
            and unresolved_relation_ids
            and mixed_anchor
            and profile_id in _STRUCTURAL_PROFILES
            and not contradiction_reasons
        ):
            status = "needs_review"
            summary = "Unresolved topology suggests structure but evidence is not strong enough."
            confidence = 0.64
        if (
            detector_class_id in _TOPOLOGY_PRESSURE_FAMILIES
            and inferred_relation_ids
            and row.status == "linked"
            and row.confidence >= 0.72
            and profile_id in _STRUCTURAL_PROFILES
            and detector_class_id in _PROFILE_INCOMPATIBLE_BY_FAMILY
            and profile_id in _PROFILE_INCOMPATIBLE_BY_FAMILY.get(detector_class_id, set())
            and strong_anchor
        ):
            contradiction_reasons.append("linked_anchor_conflicts_with_inferred_structural_profile")
        if (
            anchor_strengthened
            and strong_anchor
            and inferred_relation_kinds
            and incompatible_relation_kinds
            and profile_id in _STRUCTURAL_PROFILES
            and (endpoint_note_support or endpoint_legend_support or bool(row.legend_entry_id))
            and (locality_detail_region_ids or locality_subregion_ids or locality_pseudo_page_ids)
        ):
            contradiction_reasons.append("strengthened_anchor_inferred_relation_family_incompatible")
        if contradiction_reasons:
            if any(
                reason in contradiction_reasons
                for reason in {
                    "topology_backed_mixed_grounding_requires_review",
                    "detail_installation_inferred_pathway_mixed_grounding",
                }
            ):
                status = "needs_review"
            else:
                status = "contradicted"
                summary = "Anchor evidence conflicts with deterministic family/context expectations."
                confidence = max(confidence, 0.79)
                if inferred_relation_ids:
                    confidence = max(confidence, 0.86)
        elif detector_class_id in _TOPOLOGY_PRESSURE_FAMILIES and unresolved_endpoint_ids and profile_id in _STRUCTURAL_PROFILES:
            status = "needs_review"
            summary = "Topology context exists but remains unresolved for this anchor."
            confidence = max(confidence, 0.6)
        priority_score = _priority_score(
            status=status,
            severity="high" if status == "contradicted" else ("medium" if status != "supported" else "low"),
            confidence=confidence,
            family=detector_class_id,
            page_span=1,
            topology_support=bool(inferred_endpoint_ids or inferred_relation_ids),
        )
        triage_bucket = _triage_bucket(
            status=status,
            severity="high" if status == "contradicted" else ("medium" if status != "supported" else "low"),
            priority_score=priority_score,
            family=detector_class_id,
        )
        anchor_idx += 1
        finding_id = f"reason:anchor:{anchor_idx}"
        findings.append(
            SiteSchematicReasoningFinding(
                finding_id=finding_id,
                finding_type="anchor_reconciliation",
                severity="high" if status == "contradicted" else ("medium" if status != "supported" else "low"),
                status=status,
                confidence=confidence,
                summary=summary,
                triage_bucket=triage_bucket,
                priority_score=priority_score,
                evidence_node_ids=(f"symbol:{row.instance_id}",) + ((f"legend:{row.legend_entry_id}",) if row.legend_entry_id else ()),
                evidence_edge_ids=_edge_ids_for_nodes(graph, (f"symbol:{row.instance_id}",)),
                evidence_symbol_instance_ids=(row.instance_id,),
                evidence_topology_ids=inferred_endpoint_ids + inferred_relation_ids + unresolved_endpoint_ids + unresolved_relation_ids,
                page_indices=(row.page_index,),
                profile_ids=((profile_id,) if profile_id else ()),
                suggested_action=_family_reconciliation_hint(detector_class_id) if status != "supported" else "",
                metadata={
                    "detector_class_id": detector_class_id,
                    "link_status": row.status,
                    "topology_endpoint_count": len(endpoint_ids),
                    "inferred_topology_endpoint_count": len(inferred_endpoint_ids),
                    "unresolved_topology_endpoint_count": len(unresolved_endpoint_ids),
                    "inferred_topology_relation_count": len(inferred_relation_ids),
                    "unresolved_topology_relation_count": len(unresolved_relation_ids),
                    "topology_relation_kinds": sorted(inferred_relation_kinds),
                    "expected_relation_kinds": sorted(expected_relation_kinds),
                    "incompatible_relation_kinds": sorted(incompatible_relation_kinds),
                    "contradiction_reasons": contradiction_reasons,
                    "topology_evidence_tier": "strong_inferred" if inferred_relation_ids else ("weak_unresolved" if unresolved_relation_ids else "none"),
                    "anchor_grounding_tier": anchor_grounding_tier,
                    "anchor_strengthened": anchor_strengthened,
                    "locality_region_ids": locality_region_ids,
                    "locality_detail_region_ids": locality_detail_region_ids,
                    "locality_subregion_ids": locality_subregion_ids,
                    "locality_pseudo_page_ids": locality_pseudo_page_ids,
                    "endpoint_note_support": endpoint_note_support,
                    "endpoint_legend_support": endpoint_legend_support,
                    "rule_name": (
                        "inferred_topology_family_conflict"
                        if any(
                            reason in contradiction_reasons
                            for reason in {
                                "inferred_topology_relation_incompatible_with_grounded_family",
                                "linked_anchor_conflicts_with_inferred_structural_profile",
                                "detail_installation_inferred_relation_family_incompatible",
                                "detail_installation_strengthened_anchor_relation_incompatible",
                                "strengthened_anchor_inferred_relation_family_incompatible",
                            }
                        )
                        else (
                            "topology_backed_mixed_grounding_review"
                            if any(
                                reason in contradiction_reasons
                                for reason in {
                                    "topology_backed_mixed_grounding_requires_review",
                                    "detail_installation_inferred_pathway_mixed_grounding",
                                }
                            )
                            else "default_anchor_reconciliation"
                        )
                    ),
                },
            )
        )
        anchor_suggestions.append(
            SiteSchematicAnchorReconciliationSuggestion(
                suggestion_id=f"anchor_suggestion:{anchor_idx}",
                status=status if status in {"supported", "needs_review"} else "needs_review",
                confidence=confidence,
                summary=summary,
                symbol_instance_id=row.instance_id,
                legend_entry_id=row.legend_entry_id,
                topology_endpoint_ids=endpoint_ids,
                related_finding_ids=(finding_id,),
                metadata={"profile_id": profile_id, "detector_class_id": detector_class_id},
            )
        )

    # C) Topology continuity review.
    topo_idx = 0
    for rel in topology_relations:
        topo_idx += 1
        is_inferred_topology = rel.status == "inferred"
        status = "supported" if is_inferred_topology and rel.confidence >= 0.6 else "needs_review"
        severity = "low" if status == "supported" else ("medium" if is_inferred_topology else "low")
        summary = (
            f"Topology relation '{rel.relation_kind}' is supported."
            if status == "supported"
            else (
                f"Topology relation '{rel.relation_kind}' is inferred but below support threshold."
                if is_inferred_topology
                else f"Topology relation '{rel.relation_kind}' is unresolved and weak evidence only."
            )
        )
        priority_score = _priority_score(
            status=status,
            severity=severity,
            confidence=rel.confidence,
            family="",
            page_span=1,
            topology_support=True,
        )
        triage_bucket = _triage_bucket(
            status=status,
            severity=severity,
            priority_score=priority_score,
            family="",
        )
        finding_id = f"reason:topology:{topo_idx}"
        findings.append(
            SiteSchematicReasoningFinding(
                finding_id=finding_id,
                finding_type="topology_continuity_review",
                severity=severity,
                status=status,
                confidence=rel.confidence,
                summary=summary,
                triage_bucket=triage_bucket,
                priority_score=priority_score,
                evidence_node_ids=(
                    f"topology_endpoint:{rel.source_endpoint_id}",
                    f"topology_endpoint:{rel.target_endpoint_id}",
                ),
                evidence_edge_ids=_edge_ids_for_nodes(
                    graph,
                    (
                        f"topology_endpoint:{rel.source_endpoint_id}",
                        f"topology_endpoint:{rel.target_endpoint_id}",
                    ),
                ),
                page_indices=(rel.page_index,),
                evidence_topology_ids=(rel.relation_id, rel.source_endpoint_id, rel.target_endpoint_id),
                profile_ids=((rel.profile_id,) if rel.profile_id else ()),
                suggested_action="manual continuity review" if status != "supported" else "",
                metadata={
                    "relation_kind": rel.relation_kind,
                    "relation_status": rel.status,
                    "topology_evidence_tier": "strong_inferred" if is_inferred_topology else "weak_unresolved",
                },
            )
        )
        topology_suggestions.append(
            SiteSchematicTopologyReviewSuggestion(
                suggestion_id=f"topology_review:{topo_idx}",
                status=status,
                confidence=rel.confidence,
                summary=summary,
                profile_id=rel.profile_id,
                topology_relation_id=rel.relation_id,
                topology_endpoint_ids=(rel.source_endpoint_id, rel.target_endpoint_id),
                related_finding_ids=(finding_id,),
                metadata={"relation_kind": rel.relation_kind},
            )
        )
    if not topology_relations and len(topology_endpoints) >= 2:
        priority_score = _priority_score(
            status="abstained",
            severity="low",
            confidence=0.45,
            family="",
            page_span=1,
            topology_support=True,
        )
        findings.append(
            SiteSchematicReasoningFinding(
                finding_id="reason:topology:abstain",
                finding_type="topology_continuity_review",
                severity="low",
                status="abstained",
                confidence=0.45,
                summary="Topology endpoints exist but relation evidence is insufficient.",
                triage_bucket="ambiguity_needs_review",
                priority_score=priority_score,
                evidence_node_ids=tuple(f"topology_endpoint:{row.endpoint_id}" for row in topology_endpoints[:4]),
                evidence_edge_ids=(),
                evidence_topology_ids=tuple(row.endpoint_id for row in topology_endpoints[:4]),
                page_indices=tuple(sorted({row.page_index for row in topology_endpoints[:4]})),
                profile_ids=tuple(sorted({row.profile_id for row in topology_endpoints[:4]})),
                suggested_action="collect stronger continuity evidence before asserting relation",
            )
        )

    # D) Detail/control-sheet consistency check.
    control_linked = [
        row
        for row in symbol_links
        if str((symbol_by_id.get(row.instance_id).metadata or {}).get("detector_profile_id", "")).strip() == "control_legend_profile"
        and row.status == "linked"
    ]
    if control_linked:
        priority_score = _priority_score(
            status="needs_review",
            severity="medium",
            confidence=0.61,
            family="",
            page_span=len({row.page_index for row in control_linked}),
            topology_support=False,
        )
        findings.append(
            SiteSchematicReasoningFinding(
                finding_id="reason:detail_control:1",
                finding_type="detail_control_consistency",
                severity="medium",
                status="needs_review",
                confidence=0.61,
                summary="Linked symbols in control_legend profile require cross-check against plan/detail/riser usage.",
                triage_bucket="medium_priority_review",
                priority_score=priority_score,
                evidence_node_ids=tuple(f"symbol:{row.instance_id}" for row in control_linked[:8]),
                evidence_edge_ids=_edge_ids_for_nodes(graph, tuple(f"symbol:{row.instance_id}" for row in control_linked[:8])),
                evidence_symbol_instance_ids=tuple(row.instance_id for row in control_linked[:8]),
                page_indices=tuple(sorted({row.page_index for row in control_linked[:8]})),
                profile_ids=("control_legend_profile",),
                suggested_action="verify control-sheet links are references, not local topology truth",
            )
        )

    contradictions = [row for row in findings if row.status == "contradicted"]
    contradiction_flags = tuple(
        SiteSchematicContradictionFlag(
            flag_id=f"contradiction:{idx}",
            status="needs_review",
            confidence=min(0.9, row.confidence),
            summary=row.summary,
            related_finding_ids=(row.finding_id,),
            metadata={
                "finding_type": row.finding_type,
                "severity": row.severity,
                "triage_bucket": row.triage_bucket,
                "priority_score": row.priority_score,
            },
        )
        for idx, row in enumerate(contradictions, start=1)
    )

    # Aggregate checks.
    finding_ids = tuple(row.finding_id for row in findings)
    status_counts = Counter(row.status for row in findings)
    check_rows = (
        SiteSchematicConsistencyCheck(
            check_id="consistency:cross_page",
            check_type="cross_page_consistency",
            status="needs_review" if status_counts.get("contradicted", 0) else "supported",
            confidence=0.77 if status_counts.get("contradicted", 0) == 0 else 0.64,
            summary="Cross-page agreement/disagreement consistency sweep.",
            evidence_finding_ids=tuple(row.finding_id for row in findings if row.finding_type == "cross_page_consistency")[:32],
        ),
        SiteSchematicConsistencyCheck(
            check_id="consistency:topology",
            check_type="topology_continuity",
            status="supported" if topology_relations else "abstained",
            confidence=0.72 if topology_relations else 0.46,
            summary="Topology continuity review over additive topology layer.",
            evidence_finding_ids=tuple(row.finding_id for row in findings if row.finding_type == "topology_continuity_review")[:32],
        ),
        SiteSchematicConsistencyCheck(
            check_id="consistency:anchor",
            check_type="anchor_reconciliation",
            status="supported" if status_counts.get("needs_review", 0) < max(3, len(anchor_suggestions) // 3) else "needs_review",
            confidence=0.7,
            summary="Legend-anchor-topology reconciliation check.",
            evidence_finding_ids=tuple(row.finding_id for row in findings if row.finding_type == "anchor_reconciliation")[:32],
        ),
    )
    diagnostics = {
        "finding_count": len(findings),
        "status_counts": dict(status_counts),
        "finding_type_counts": dict(Counter(row.finding_type for row in findings)),
        "triage_bucket_counts": dict(Counter(row.triage_bucket for row in findings)),
        "high_priority_review_count": sum(
            1
            for row in findings
            if row.triage_bucket in {"high_priority_review", "contradiction_high_confidence"}
        ),
        "profile_distribution": dict(
            Counter(profile for row in findings for profile in row.profile_ids if profile)
        ),
        "topology_status_counts": {
            "inferred_endpoint_count": sum(1 for row in topology_endpoints if row.status == "inferred"),
            "unresolved_endpoint_count": sum(1 for row in topology_endpoints if row.status != "inferred"),
            "inferred_relation_count": sum(1 for row in topology_relations if row.status == "inferred"),
            "unresolved_relation_count": sum(1 for row in topology_relations if row.status != "inferred"),
        },
        "topology_aware_contradiction_count": sum(
            1
            for row in findings
            if row.status == "contradicted" and bool(row.evidence_topology_ids)
        ),
        "topology_aware_high_priority_review_count": sum(
            1
            for row in findings
            if row.triage_bucket in {"high_priority_review", "contradiction_high_confidence"}
            and bool(row.evidence_topology_ids)
        ),
        "detail_installation_contradiction_count": sum(
            1
            for row in findings
            if row.status == "contradicted" and "detail_installation_profile" in set(row.profile_ids)
        ),
        "detail_installation_high_priority_review_count": sum(
            1
            for row in findings
            if row.triage_bucket in {"high_priority_review", "contradiction_high_confidence"}
            and "detail_installation_profile" in set(row.profile_ids)
        ),
        "strengthened_anchor_contradiction_count": sum(
            1
            for row in findings
            if row.status == "contradicted"
            and bool((row.metadata or {}).get("anchor_strengthened", False))
        ),
        "strengthened_anchor_high_priority_review_count": sum(
            1
            for row in findings
            if row.triage_bucket in {"high_priority_review", "contradiction_high_confidence"}
            and bool((row.metadata or {}).get("anchor_strengthened", False))
        ),
        "contradiction_count": len(contradiction_flags),
        "anchor_suggestion_count": len(anchor_suggestions),
        "topology_review_suggestion_count": len(topology_suggestions),
        "finding_ids": list(finding_ids[:80]),
    }
    return (
        tuple(findings),
        check_rows,
        contradiction_flags,
        tuple(anchor_suggestions),
        tuple(topology_suggestions),
        diagnostics,
    )


def _dedupe_limited(values: Iterable[str], limit: int = 12) -> tuple[str, ...]:
    rows: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = str(value).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append(key)
        if len(rows) >= limit:
            break
    return tuple(rows)


def build_reasoning_summaries(
    *,
    findings: tuple[SiteSchematicReasoningFinding, ...],
    symbol_links: tuple[SiteSchematicSymbolLink, ...],
    topology_endpoints: tuple[SiteSchematicTopologyEndpoint, ...],
    topology_relations: tuple[SiteSchematicTopologyRelation, ...],
) -> tuple[
    SiteSchematicPacketReasoningSummary,
    tuple[SiteSchematicFamilyConsistencySummary, ...],
    SiteSchematicReviewQueueSummary,
    SiteSchematicTopologyCoverageSummary,
    tuple[SiteSchematicProfileQASummary, ...],
]:
    status_counts = Counter(row.status for row in findings)
    triage_counts = Counter(row.triage_bucket for row in findings)
    high_priority_count = triage_counts.get("high_priority_review", 0) + triage_counts.get("contradiction_high_confidence", 0)
    family_by_finding: dict[str, str] = {}
    for row in findings:
        metadata = dict(row.metadata or {})
        family = str(metadata.get("family", "")).strip() or str(metadata.get("detector_class_id", "")).strip()
        if not family:
            continue
        family_by_finding[row.finding_id] = family
    if not family_by_finding:
        for link in symbol_links:
            family = str((link.metadata or {}).get("grounding_strengthening_detector_class_id", "")).strip()
            if family:
                family_by_finding[link.link_id] = family
    family_rows: list[SiteSchematicFamilyConsistencySummary] = []
    for family in sorted(set(family_by_finding.values())):
        scoped = [row for row in findings if family_by_finding.get(row.finding_id) == family]
        if not scoped:
            continue
        supporting_node_ids = _dedupe_limited(node_id for row in scoped for node_id in row.evidence_node_ids)
        supporting_edge_ids = _dedupe_limited(edge_id for row in scoped for edge_id in row.evidence_edge_ids)
        supporting_symbol_ids = _dedupe_limited(symbol_id for row in scoped for symbol_id in row.evidence_symbol_instance_ids)
        supporting_topology_ids = _dedupe_limited(top_id for row in scoped for top_id in row.evidence_topology_ids)
        profile_ids = _dedupe_limited(profile for row in scoped for profile in row.profile_ids)
        page_indices = tuple(sorted({page for row in scoped for page in row.page_indices}))[:12]
        supported_count = sum(1 for row in scoped if row.status == "supported")
        mixed_count = sum(1 for row in scoped if row.status in {"needs_review", "ambiguous", "abstained"})
        high_priority = sum(1 for row in scoped if row.triage_bucket in {"high_priority_review", "contradiction_high_confidence"})
        topology_supported = sum(1 for row in scoped if bool(row.evidence_topology_ids))
        status = "stable" if mixed_count == 0 else ("review_heavy" if high_priority >= 2 or mixed_count > supported_count else "mixed")
        family_rows.append(
            SiteSchematicFamilyConsistencySummary(
                family=family,
                total_findings=len(scoped),
                supported_count=supported_count,
                mixed_count=mixed_count,
                high_priority_count=high_priority,
                topology_supported_count=topology_supported,
                status=status,
                page_indices=page_indices,
                profile_ids=profile_ids,
                supporting_finding_ids=tuple(row.finding_id for row in scoped[:16]),
                supporting_node_ids=supporting_node_ids,
                supporting_edge_ids=supporting_edge_ids,
                supporting_symbol_ids=supporting_symbol_ids,
                supporting_topology_ids=supporting_topology_ids,
                metadata={
                    "triage_bucket_counts": dict(Counter(row.triage_bucket for row in scoped)),
                    "status_counts": dict(Counter(row.status for row in scoped)),
                },
            )
        )
    family_rows = sorted(family_rows, key=lambda row: (-row.high_priority_count, -row.mixed_count, row.family))
    review_items = [row for row in findings if row.status in {"needs_review", "contradicted", "ambiguous", "abstained"}]
    review_queue = SiteSchematicReviewQueueSummary(
        queue_id="review_queue:packet",
        total_items=len(review_items),
        high_priority_items=high_priority_count,
        medium_priority_items=triage_counts.get("medium_priority_review", 0),
        low_priority_items=triage_counts.get("low_priority_review", 0),
        queue_buckets=dict(triage_counts),
        top_families=_dedupe_limited(family_by_finding.get(row.finding_id, "") for row in review_items),
        top_profiles=_dedupe_limited(profile for row in review_items for profile in row.profile_ids),
        page_indices=tuple(sorted({page for row in review_items for page in row.page_indices}))[:20],
        supporting_finding_ids=tuple(row.finding_id for row in review_items[:32]),
        metadata={
            "queue_groups": {
                "topology_backed_structural_review": sum(
                    1
                    for row in review_items
                    if bool(row.evidence_topology_ids) and any(profile in _STRUCTURAL_PROFILES for profile in row.profile_ids)
                ),
                "cross_page_family_ambiguity": sum(1 for row in review_items if row.finding_type == "cross_page_consistency"),
                "legend_grounding_review": sum(
                    1
                    for row in review_items
                    if str((row.metadata or {}).get("link_status", "")).strip() in {"detected_but_unmapped", "weakly_linked", "conflicting"}
                ),
                "detail_installation_review": sum(1 for row in review_items if "detail_installation_profile" in set(row.profile_ids)),
                "riser_continuity_review": sum(1 for row in review_items if "riser_profile" in set(row.profile_ids)),
                "rack_equipment_consistency_review": sum(
                    1
                    for row in review_items
                    if {"rack_detail_profile", "equipment_room_profile"} & set(row.profile_ids)
                ),
            }
        },
    )
    endpoint_profile_counts = Counter(row.profile_id for row in topology_endpoints if row.profile_id)
    relation_profile_counts = Counter(row.profile_id for row in topology_relations if row.profile_id)
    endpoint_family_counts = Counter(row.detector_class_id for row in topology_endpoints if row.detector_class_id)
    relation_family_counts = Counter(
        row.detector_class_id
        for row in topology_endpoints
        if row.endpoint_id in {rel.source_endpoint_id for rel in topology_relations} | {rel.target_endpoint_id for rel in topology_relations}
        and row.detector_class_id
    )
    topology_coverage = SiteSchematicTopologyCoverageSummary(
        summary_id="topology_coverage:packet",
        endpoint_count=len(topology_endpoints),
        relation_count=len(topology_relations),
        inferred_endpoint_count=sum(1 for row in topology_endpoints if row.status == "inferred"),
        unresolved_endpoint_count=sum(1 for row in topology_endpoints if row.status != "inferred"),
        inferred_relation_count=sum(1 for row in topology_relations if row.status == "inferred"),
        unresolved_relation_count=sum(1 for row in topology_relations if row.status != "inferred"),
        endpoint_profile_counts=dict(endpoint_profile_counts),
        relation_profile_counts=dict(relation_profile_counts),
        top_family_endpoint_counts=dict(endpoint_family_counts.most_common(8)),
        top_family_relation_counts=dict(relation_family_counts.most_common(8)),
        sparse_profiles=tuple(
            profile
            for profile, count in sorted((endpoint_profile_counts + relation_profile_counts).items(), key=lambda item: item[0])
            if count <= 1
        )[:8],
        supporting_topology_ids=_dedupe_limited(
            [row.endpoint_id for row in topology_endpoints[:24]] + [row.relation_id for row in topology_relations[:24]],
            limit=24,
        ),
        metadata={
            "profiles_with_inferred_relations": sorted(
                {
                    row.profile_id
                    for row in topology_relations
                    if row.status == "inferred" and row.profile_id
                }
            ),
        },
    )
    profile_rows: list[SiteSchematicProfileQASummary] = []
    profile_ids = sorted(
        {
            profile
            for row in findings
            for profile in row.profile_ids
            if profile
        }
        | {row.profile_id for row in topology_endpoints if row.profile_id}
        | {row.profile_id for row in topology_relations if row.profile_id}
    )
    for profile_id in profile_ids:
        scoped = [row for row in findings if profile_id in set(row.profile_ids)]
        if not scoped:
            continue
        top_families = Counter(family_by_finding.get(row.finding_id, "") for row in scoped if family_by_finding.get(row.finding_id, ""))
        strong_anchors = sum(1 for row in scoped if bool((row.metadata or {}).get("anchor_grounding_tier") == "strong"))
        mixed_anchors = sum(1 for row in scoped if bool((row.metadata or {}).get("anchor_grounding_tier") == "mixed"))
        profile_rows.append(
            SiteSchematicProfileQASummary(
                profile_id=profile_id,
                total_findings=len(scoped),
                supported_count=sum(1 for row in scoped if row.status == "supported"),
                review_count=sum(1 for row in scoped if row.status in {"needs_review", "ambiguous", "abstained"}),
                contradiction_count=sum(1 for row in scoped if row.status == "contradicted"),
                high_priority_count=sum(1 for row in scoped if row.triage_bucket in {"high_priority_review", "contradiction_high_confidence"}),
                strong_anchor_count=strong_anchors,
                mixed_anchor_count=mixed_anchors,
                inferred_topology_count=sum(1 for row in topology_endpoints if row.profile_id == profile_id and row.status == "inferred")
                + sum(1 for row in topology_relations if row.profile_id == profile_id and row.status == "inferred"),
                unresolved_topology_count=sum(1 for row in topology_endpoints if row.profile_id == profile_id and row.status != "inferred")
                + sum(1 for row in topology_relations if row.profile_id == profile_id and row.status != "inferred"),
                top_families=tuple(family for family, _ in top_families.most_common(5)),
                page_indices=tuple(sorted({page for row in scoped for page in row.page_indices}))[:12],
                supporting_finding_ids=tuple(row.finding_id for row in scoped[:20]),
                metadata={
                    "triage_bucket_counts": dict(Counter(row.triage_bucket for row in scoped)),
                    "reasoning_pressure": "high"
                    if sum(1 for row in scoped if row.status in {"needs_review", "contradicted"}) >= max(4, len(scoped) // 2)
                    else "stable",
                },
            )
        )
    packet_summary = SiteSchematicPacketReasoningSummary(
        summary_id="packet_reasoning:summary",
        packet_scope="site_schematic_packet",
        total_findings=len(findings),
        supported_count=status_counts.get("supported", 0),
        needs_review_count=status_counts.get("needs_review", 0) + status_counts.get("ambiguous", 0),
        contradicted_count=status_counts.get("contradicted", 0),
        high_priority_count=high_priority_count,
        summary=(
            f"Packet reasoning reports {status_counts.get('supported', 0)} supported and "
            f"{status_counts.get('needs_review', 0) + status_counts.get('ambiguous', 0)} review findings."
        ),
        top_review_profiles=_dedupe_limited(
            profile
            for profile, _ in Counter(profile for row in review_items for profile in row.profile_ids).most_common(5)
        ),
        top_review_families=_dedupe_limited(
            family
            for family, _ in Counter(family_by_finding.get(row.finding_id, "") for row in review_items if family_by_finding.get(row.finding_id, "")).most_common(5)
        ),
        supporting_finding_ids=tuple(row.finding_id for row in findings[:32]),
        metadata={
            "triage_bucket_counts": dict(triage_counts),
            "review_queue_size": len(review_items),
            "family_summary_count": len(family_rows),
            "profile_summary_count": len(profile_rows),
        },
    )
    return (
        packet_summary,
        tuple(family_rows),
        review_queue,
        topology_coverage,
        tuple(sorted(profile_rows, key=lambda row: (-row.high_priority_count, row.profile_id))),
    )

