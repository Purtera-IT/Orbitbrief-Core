from __future__ import annotations

from collections import defaultdict
import re

from orbitbrief_core.parser.site_schematic.models import (
    SiteSchematicLegendEntry,
    SiteSchematicSymbolInstance,
    SiteSchematicSymbolLink,
    SiteSchematicSymbolResolutionOutcome,
    SiteSchematicTopologyEndpoint,
    SiteSchematicTopologyRelation,
)
from orbitbrief_core.parser.site_schematic.symbols.profile_routing import (
    get_detector_profile,
    is_class_suppressed,
    profile_score_adjustment,
    profile_suppression_margin,
    profile_threshold_delta,
    select_profile_for_context,
)
from orbitbrief_core.parser.site_schematic.symbols.vocabulary import vocabulary_class_lookup

# Phase V2 note:
# This linker remains the deterministic symbol-instance linker. V2 legend-grounded
# candidate resolution runs as an additive layer in core and can later be unified
# here through a shared resolver seam.

_LOW_VOLTAGE_CLASS_MIN_LINK_SCORE = {
    "data_outlet": 3.4,
    "door_contact_marker": 3.4,
    "riser_endpoint": 3.0,
    "telecomm_jack_tag": 3.5,
    "j_hook_pathway_symbol": 3.2,
    "equipment_rack_front": 3.2,
    "wireless_node_wall_outlet": 2.9,
    "zigbee_node_ceiling_outlet": 2.9,
}

_STRUCTURAL_GROUNDING_PROFILES = {
    "detail_installation_profile",
    "rack_detail_profile",
    "equipment_room_profile",
    "riser_profile",
}

_RELATION_KIND_COMPATIBLE_FAMILIES: dict[str, set[str]] = {
    "pathway_attachment": {"telecomm_jack_tag", "data_outlet", "j_hook_pathway_symbol", "ladder_rack_cable_runway"},
    "rack_connectivity": {"patch_panel_row", "equipment_rack_front", "ladder_rack_cable_runway"},
    "riser_continuity": {"riser_endpoint", "ladder_rack_cable_runway"},
    "termination_attachment": {"telecomm_jack_tag", "data_outlet", "patch_panel_row"},
}

_RELATION_KIND_INCOMPATIBLE_FAMILIES: dict[str, set[str]] = {
    "pathway_attachment": {"patch_panel_row", "equipment_rack_front", "riser_endpoint"},
    "rack_connectivity": {"data_outlet", "door_contact_marker"},
    "riser_continuity": {"telecomm_jack_tag", "data_outlet"},
    "termination_attachment": {"riser_endpoint", "equipment_rack_front"},
}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _relevant_notes(symbol: SiteSchematicSymbolInstance, note_clauses: tuple[str, ...]) -> tuple[str, ...]:
    token = symbol.token.upper()
    primitive = symbol.primitive_kind
    scored: list[tuple[int, str]] = []
    for clause in note_clauses:
        lower = clause.lower()
        score = 0
        if token in {"AP", "WAP", "CM", "WM", "EXT"}:
            if any(term in lower for term in ("wireless", "wap", "access point")):
                score += 6
            if any(term in lower for term in ("slack", "service loop", "future relocation")):
                score += 4
            if "patch panel" in lower:
                score += 4
            if any(term in lower for term in ("site survey", "wifi", "wi-fi", "ceiling mounted")):
                score += 3
        elif token in {"CCTV", "TV", "PP", "FIC"}:
            if any(term in lower for term in ("camera", "cctv", "matv", "tv", "signal")):
                score += 4
            if "patch panel" in lower:
                score += 2
        elif primitive == "rack_or_patch_symbol" and any(term in lower for term in ("rack", "cabinet", "patch panel", "busbar", "ground")):
            score += 4
        if any(term in lower for term in ("terminate", "conduit", "power", "mount", "aff", "label")):
            score += 1
        if score > 0:
            scored.append((score, _clean(clause)))
    scored.sort(key=lambda item: (-item[0], item[1]))
    deduped: list[str] = []
    seen: set[str] = set()
    for _, row in scored:
        key = row.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
        if len(deduped) >= 4:
            break
    # Keep one patch-panel anchor for wireless AP/WAP links when available.
    if token in {"AP", "WAP"} and not any("patch panel" in row.lower() for row in deduped):
        patch_candidates = [
            _clean(clause)
            for clause in note_clauses
            if "patch panel" in clause.lower() and any(term in clause.lower() for term in ("wap", "wireless", "access point", "ap"))
        ]
        if patch_candidates:
            patch_note = patch_candidates[0]
            if patch_note.lower() not in seen:
                if len(deduped) >= 4:
                    deduped[-1] = patch_note
                else:
                    deduped.append(patch_note)
    return tuple(deduped)


def _detector_class_keyword_boost(symbol: SiteSchematicSymbolInstance, entry: SiteSchematicLegendEntry) -> float:
    detector_class_id = str((symbol.metadata or {}).get("detector_class_id", "")).strip()
    if not detector_class_id:
        return 0.0
    lookup = vocabulary_class_lookup()
    class_row = lookup.get(detector_class_id)
    if class_row is None:
        return 0.0
    keywords = class_row.get("keywords", [])
    if not isinstance(keywords, list):
        return 0.0
    haystack = f"{entry.label} {entry.description}".lower()
    score = 0.0
    for token in keywords:
        token = str(token).strip().lower()
        if not token:
            continue
        if token in haystack:
            score += 0.9
    if score <= 0.0:
        return 0.0
    # Keep this as a bounded prior so local legend still decides.
    return min(3.0, score)


def _detector_class_keywords(symbol: SiteSchematicSymbolInstance) -> tuple[str, ...]:
    detector_class_id = str((symbol.metadata or {}).get("detector_class_id", "")).strip()
    if not detector_class_id:
        return ()
    lookup = vocabulary_class_lookup()
    class_row = lookup.get(detector_class_id)
    if class_row is None:
        return ()
    value = class_row.get("keywords", [])
    if not isinstance(value, list):
        return ()
    rows = [str(token).strip().lower() for token in value if str(token).strip()]
    return tuple(dict.fromkeys(rows))


def _is_low_voltage_symbol(symbol: SiteSchematicSymbolInstance) -> bool:
    if "low_voltage" in set(symbol.overlay_tags):
        return True
    context = _clean(f"{symbol.text} {symbol.room_label}").lower()
    return any(token in context for token in ("idf", "mdf", "security", "duress", "door contact", "zigbee", "card reader"))


def _low_voltage_context_adjustment(symbol: SiteSchematicSymbolInstance, entry: SiteSchematicLegendEntry) -> float:
    detector_class_id = str((symbol.metadata or {}).get("detector_class_id", "")).strip()
    if not detector_class_id:
        return 0.0
    context = _clean(f"{symbol.text} {symbol.room_label}").lower()
    haystack = f"{entry.label} {entry.description}".lower()
    if detector_class_id == "data_outlet":
        if any(token in haystack for token in ("data outlet", "cat", "telecomm", "jack", "outlet")):
            return 1.1
        return -0.8
    if detector_class_id == "door_contact_marker":
        if "door" in haystack and any(token in haystack for token in ("contact", "security", "access")):
            return 1.0
        return -0.9
    if detector_class_id == "riser_endpoint":
        if any(token in haystack for token in ("riser", "backbone", "fiber", "coax", "endpoint")):
            return 1.0
        if "riser" not in context and "backbone" not in context:
            return -0.7
        return -0.4
    if detector_class_id == "telecomm_jack_tag":
        if any(token in haystack for token in ("tag", "jack", "telecomm", "outlet id", "port")):
            return 1.1
        return -1.0
    if detector_class_id == "j_hook_pathway_symbol":
        if any(token in haystack for token in ("j-hook", "pathway", "support", "cable route")):
            return 1.0
        return -0.8
    if detector_class_id == "equipment_rack_front":
        if any(token in haystack for token in ("rack", "cabinet", "panel")):
            return 0.9
        if not any(token in context for token in ("rack", "cabinet", "idf", "mdf", "equipment")):
            return -0.9
        return -0.4
    if detector_class_id == "wireless_node_wall_outlet":
        if any(token in haystack for token in ("wireless node", "wall outlet", "wireless")):
            return 0.9
        return -0.2
    if detector_class_id == "zigbee_node_ceiling_outlet":
        if any(token in haystack for token in ("zigbee", "ceiling")):
            return 0.9
        return -0.2
    return 0.0


def link_symbol_instances(
    *,
    symbol_instances: tuple[SiteSchematicSymbolInstance, ...],
    legend_entries: tuple[SiteSchematicLegendEntry, ...],
    note_clauses: tuple[str, ...],
    room_labels: tuple[str, ...],
) -> tuple[SiteSchematicSymbolLink, ...]:
    legend_lookup: dict[str, list[SiteSchematicLegendEntry]] = defaultdict(list)
    primitive_lookup: dict[str, list[SiteSchematicLegendEntry]] = defaultdict(list)
    for entry in legend_entries:
        keys = {entry.symbol_token.upper()} if entry.symbol_token else set()
        lower_desc = f"{entry.label} {entry.description}".lower()
        if any(term in lower_desc for term in ("wireless", "access point", "wap")):
            keys.update({"AP", "WAP"})
        if "wireless node" in lower_desc:
            keys.update({"WN", "WAP", "AP"})
        if "zigbee" in lower_desc:
            keys.add("ZN")
        if "ceiling mounted" in lower_desc:
            keys.add("CM")
        if "wall mounted" in lower_desc:
            keys.add("WM")
        if "exterior" in lower_desc:
            keys.add("EXT")
        if any(term in lower_desc for term in ("camera", "cctv")):
            keys.update({"CCTV", "FIC"})
        if "tv" in lower_desc:
            keys.add("TV")
        if "point of sale terminal" in lower_desc or "pos terminal" in lower_desc:
            keys.add("POS-T")
        if "point of sale printer" in lower_desc or "pos printer" in lower_desc:
            keys.add("POS-P")
        if "patch panel" in lower_desc:
            keys.add("PP")
        for key in keys:
            if key:
                legend_lookup[key].append(entry)
        primitive_lookup[entry.primitive_kind].append(entry)

    links: list[SiteSchematicSymbolLink] = []
    for idx, symbol in enumerate(symbol_instances, start=1):
        low_voltage_symbol = _is_low_voltage_symbol(symbol)
        detector_class_id = str((symbol.metadata or {}).get("detector_class_id", "")).strip()
        sheet_type = str((symbol.metadata or {}).get("sheet_type", "")).strip()
        region_kind = str((symbol.metadata or {}).get("region_kind", "")).strip()
        detail_kind = str((symbol.metadata or {}).get("detail_kind", "")).strip()
        subregion_role = str((symbol.metadata or {}).get("subregion_role", "")).strip()
        pseudo_role = str((symbol.metadata or {}).get("pseudo_page_role", "")).strip()
        profile_id = str((symbol.metadata or {}).get("detector_profile_id", "")).strip()
        profile_reasons = tuple((symbol.metadata or {}).get("detector_profile_reasons", ()) or ())
        if not profile_id:
            profile_id, profile_reasons = select_profile_for_context(
                sheet_type=sheet_type,
                region_kind=region_kind,
                detail_kind=detail_kind,
                subregion_role=subregion_role,
                pseudo_role=pseudo_role,
                local_text=f"{symbol.text} {symbol.room_label}",
            )
        profile = get_detector_profile(profile_id)
        profile_suppressed = bool(detector_class_id and is_class_suppressed(profile_id, detector_class_id))
        suppression_margin = profile_suppression_margin(profile_id)
        detector_keywords = _detector_class_keywords(symbol)
        candidates = list(legend_lookup.get(symbol.token.upper(), ()))
        candidates.extend(entry for entry in primitive_lookup.get(symbol.primitive_kind, ()) if entry not in candidates)
        if detector_keywords:
            for entry in legend_entries:
                haystack = f"{entry.label} {entry.description}".lower()
                if any(token in haystack for token in detector_keywords):
                    if entry not in candidates:
                        candidates.append(entry)
        scored: list[tuple[float, SiteSchematicLegendEntry]] = []
        for entry in candidates:
            score = 0.0
            if symbol.token.upper() == entry.symbol_token.upper() and entry.symbol_token:
                score += 3.0
            haystack = f"{entry.label} {entry.description}".upper()
            if symbol.token.upper() in haystack:
                score += 1.6
            if entry.primitive_kind == symbol.primitive_kind:
                score += 1.0
            if set(symbol.overlay_tags) & set(entry.overlay_tags):
                score += 0.4
            if symbol.token.upper() in {"AP", "WAP"} and any(term in haystack for term in ("WIRELESS", "ACCESS POINT", "WAP")):
                score += 3.4
            if symbol.token.upper() == "WN" and "WIRELESS NODE" in haystack:
                score += 3.2
            if symbol.token.upper() == "ZN" and "ZIGBEE" in haystack:
                score += 3.2
            if symbol.token.upper() == "POS-T" and all(term in haystack for term in ("POS", "TERMINAL")):
                score += 3.0
            if symbol.token.upper() == "POS-P" and all(term in haystack for term in ("POS", "PRINTER")):
                score += 3.0
            if symbol.token.upper() == "FIC" and any(term in haystack for term in ("CAMERA", "CCTV")):
                score += 2.6
            if symbol.token.upper() in {"CM", "WM", "EXT"} and any(term in haystack for term in ("CEILING", "WALL", "EXTERIOR")):
                score += 1.2
            score += _detector_class_keyword_boost(symbol, entry)
            score += profile_score_adjustment(profile_id, detector_class_id)
            if low_voltage_symbol:
                score += _low_voltage_context_adjustment(symbol, entry)
            scored.append((score, entry))
        scored.sort(key=lambda item: item[0], reverse=True)
        best_score, best_entry = scored[0] if scored else (0.0, None)
        second_score = scored[1][0] if len(scored) > 1 else 0.0
        tie_delta = 0.4 if low_voltage_symbol else 0.45
        weak_min = 1.7 if low_voltage_symbol else 1.5
        min_link_score = _LOW_VOLTAGE_CLASS_MIN_LINK_SCORE.get(detector_class_id, 3.0) if low_voltage_symbol else 3.0
        min_link_score = max(1.6, min_link_score + profile_threshold_delta(profile_id, detector_class_id))
        if low_voltage_symbol and symbol.token.upper() in {"WN", "ZN"}:
            min_link_score = min(min_link_score, 2.4)
        if profile_id == "control_legend_profile":
            tie_delta = min(tie_delta, 0.28)
        near_tie = bool(best_entry and len(scored) > 1 and abs(best_score - second_score) <= tie_delta and best_score >= weak_min)
        if low_voltage_symbol and symbol.token.upper() in {"WN", "ZN"} and best_entry is not None:
            best_haystack = f"{best_entry.label} {best_entry.description}".upper()
            if symbol.token.upper() == "WN" and "WIRELESS NODE" in best_haystack and best_score >= 2.4:
                near_tie = False
            if symbol.token.upper() == "ZN" and "ZIGBEE" in best_haystack and best_score >= 2.4:
                near_tie = False
        if profile_id == "control_legend_profile" and profile_suppressed:
            status = "detected_but_unmapped"
            confidence = 0.2
        elif profile_suppressed and best_score < (min_link_score + suppression_margin):
            status = "detected_but_unmapped"
            confidence = 0.2
        elif best_entry and best_score >= min_link_score:
            status = "linked"
            confidence = min(0.94, 0.58 + (best_score / 8.0))
        elif near_tie:
            status = "conflicting"
            confidence = min(0.74, 0.4 + (best_score / 8.0))
        elif best_entry and best_score >= weak_min:
            status = "weakly_linked"
            confidence = min(0.82, 0.46 + (best_score / 8.0))
        elif low_voltage_symbol and detector_class_id in _LOW_VOLTAGE_CLASS_MIN_LINK_SCORE:
            status = "detected_but_unmapped"
            confidence = 0.24
        elif low_voltage_symbol:
            status = "detected_but_unmapped"
            confidence = 0.24
        elif not candidates:
            status = "detected_but_unmapped"
            confidence = 0.24
        elif symbol.confidence < 0.52:
            status = "candidate_requires_review"
            confidence = min(0.55, max(0.2, symbol.confidence))
        else:
            status = "unresolved"
            confidence = 0.38 if scored else 0.22
        room_label = symbol.room_label or next((room for room in room_labels if room and room.lower() in symbol.text.lower()), "")
        related_notes = _relevant_notes(symbol, note_clauses)
        links.append(
            SiteSchematicSymbolLink(
                link_id=f"link:p{symbol.page_index}:{idx}",
                page_index=symbol.page_index,
                instance_id=symbol.instance_id,
                symbol_token=symbol.token,
                status=status,
                confidence=round(confidence, 4),
                legend_entry_id=best_entry.entry_id if best_entry else "",
                legend_label=best_entry.label if best_entry else "",
                room_label=room_label,
                related_note_clauses=related_notes,
                metadata={
                    "primitive_kind": symbol.primitive_kind,
                    "candidate_count": len(candidates),
                    "best_score": round(best_score, 4),
                    "second_score": round(second_score, 4),
                    "near_tie": near_tie,
                    "source_mode": symbol.source_mode,
                    "detector_profile_id": profile_id,
                    "detector_profile_reasons": list(profile_reasons),
                    "detector_profile_favored_classes": sorted(set(profile.get("favored_classes", set()))),
                    "detector_profile_suppressed_classes": sorted(set(profile.get("suppressed_classes", set()))),
                    "detector_profile_threshold_delta": profile_threshold_delta(profile_id, detector_class_id),
                    "detector_profile_suppressed_for_class": profile_suppressed,
                    "detector_profile_suppression_margin": suppression_margin,
                },
            )
        )
    return tuple(links)


def build_symbol_resolution_outcomes(
    *,
    symbol_instances: tuple[SiteSchematicSymbolInstance, ...],
    symbol_links: tuple[SiteSchematicSymbolLink, ...],
    legend_entries: tuple[SiteSchematicLegendEntry, ...],
) -> tuple[SiteSchematicSymbolResolutionOutcome, ...]:
    outcomes: list[SiteSchematicSymbolResolutionOutcome] = []
    linked_legend_ids = {row.legend_entry_id for row in symbol_links if row.legend_entry_id}
    link_by_instance = {row.instance_id: row for row in symbol_links}
    for idx, symbol in enumerate(symbol_instances, start=1):
        link = link_by_instance.get(symbol.instance_id)
        if link is None:
            outcomes.append(
                SiteSchematicSymbolResolutionOutcome(
                    outcome_id=f"sym_outcome:p{symbol.page_index}:{idx}",
                    page_index=symbol.page_index,
                    status="detected_but_unmapped",
                    confidence=max(0.2, min(0.6, symbol.confidence)),
                    symbol_token=symbol.token,
                    instance_id=symbol.instance_id,
                    reason_codes=("missing_link_row",),
                    metadata={"primitive_kind": symbol.primitive_kind, "source_mode": symbol.source_mode},
                )
            )
            continue
        reason_codes: tuple[str, ...]
        if link.status == "linked":
            reason_codes = ("high_legend_match",)
        elif link.status == "weakly_linked":
            reason_codes = ("partial_legend_match",)
        elif link.status == "conflicting":
            reason_codes = ("multiple_legend_candidates",)
        elif link.status == "detected_but_unmapped":
            reason_codes = ("no_legend_candidate",)
        elif link.status == "candidate_requires_review":
            reason_codes = ("low_confidence_candidate",)
        else:
            reason_codes = ("unresolved_grounding",)
        outcomes.append(
            SiteSchematicSymbolResolutionOutcome(
                outcome_id=f"sym_outcome:p{symbol.page_index}:{idx}",
                page_index=symbol.page_index,
                status=link.status,
                confidence=link.confidence,
                symbol_token=link.symbol_token,
                instance_id=link.instance_id,
                legend_entry_id=link.legend_entry_id,
                reason_codes=reason_codes,
                metadata={
                    "link_id": link.link_id,
                    "source_mode": symbol.source_mode,
                    "related_note_count": len(link.related_note_clauses),
                },
            )
        )
    unused_entries = [row for row in legend_entries if row.entry_id not in linked_legend_ids]
    for idx, entry in enumerate(unused_entries, start=1):
        outcomes.append(
            SiteSchematicSymbolResolutionOutcome(
                outcome_id=f"legend_outcome:p{entry.page_index}:{idx}",
                page_index=entry.page_index,
                status="legend_defined_but_unused",
                confidence=max(0.4, min(0.9, entry.confidence)),
                symbol_token=entry.symbol_token,
                legend_entry_id=entry.entry_id,
                reason_codes=("legend_not_linked_to_symbol",),
                metadata={"label": entry.label, "primitive_kind": entry.primitive_kind},
            )
        )
    return tuple(outcomes)


def strengthen_symbol_links_with_topology(
    *,
    symbol_instances: tuple[SiteSchematicSymbolInstance, ...],
    symbol_links: tuple[SiteSchematicSymbolLink, ...],
    topology_endpoints: tuple[SiteSchematicTopologyEndpoint, ...],
    topology_relations: tuple[SiteSchematicTopologyRelation, ...],
) -> tuple[tuple[SiteSchematicSymbolLink, ...], dict[str, object]]:
    symbol_by_id = {row.instance_id: row for row in symbol_instances}
    endpoint_by_id = {row.endpoint_id: row for row in topology_endpoints}
    relation_by_id = {row.relation_id: row for row in topology_relations}
    endpoint_ids_by_symbol: dict[str, list[str]] = defaultdict(list)
    relation_ids_by_symbol: dict[str, list[str]] = defaultdict(list)
    for endpoint in topology_endpoints:
        for symbol_id in endpoint.symbol_instance_ids:
            endpoint_ids_by_symbol[symbol_id].append(endpoint.endpoint_id)
    for relation in topology_relations:
        src = endpoint_by_id.get(relation.source_endpoint_id)
        dst = endpoint_by_id.get(relation.target_endpoint_id)
        for endpoint in (src, dst):
            if endpoint is None:
                continue
            for symbol_id in endpoint.symbol_instance_ids:
                relation_ids_by_symbol[symbol_id].append(relation.relation_id)

    strengthened_by_profile: dict[str, int] = defaultdict(int)
    strengthened_by_family: dict[str, int] = defaultdict(int)
    strengthened_samples: list[dict[str, object]] = []
    rejected_samples: list[dict[str, object]] = []
    output: list[SiteSchematicSymbolLink] = []
    for link in symbol_links:
        symbol = symbol_by_id.get(link.instance_id)
        if symbol is None:
            output.append(link)
            continue
        metadata = dict(link.metadata or {})
        profile_id = str((symbol.metadata or {}).get("detector_profile_id", "")).strip()
        detector_class_id = str((symbol.metadata or {}).get("detector_class_id", "")).strip()
        reasons_missing: list[str] = []
        if link.status not in {"detected_but_unmapped", "weakly_linked", "unresolved", "candidate_requires_review"}:
            output.append(link)
            continue
        if profile_id not in _STRUCTURAL_GROUNDING_PROFILES:
            output.append(link)
            continue
        endpoint_ids = tuple(endpoint_ids_by_symbol.get(link.instance_id, ()))
        inferred_endpoint_ids = tuple(
            endpoint_id
            for endpoint_id in endpoint_ids
            if endpoint_by_id.get(endpoint_id) is not None and endpoint_by_id[endpoint_id].status == "inferred"
        )
        if not inferred_endpoint_ids:
            reasons_missing.append("missing_inferred_endpoint")
        inferred_relations = [
            relation_by_id[relation_id]
            for relation_id in relation_ids_by_symbol.get(link.instance_id, ())
            if relation_by_id.get(relation_id) is not None and relation_by_id[relation_id].status == "inferred"
        ]
        if not inferred_relations:
            reasons_missing.append("missing_inferred_relation")
        if not detector_class_id:
            detector_class_id = next(
                (
                    str(endpoint_by_id[endpoint_id].detector_class_id).strip()
                    for endpoint_id in inferred_endpoint_ids
                    if endpoint_by_id.get(endpoint_id) is not None and str(endpoint_by_id[endpoint_id].detector_class_id).strip()
                ),
                "",
            )
        relation_kinds = {str(row.relation_kind).strip() for row in inferred_relations if str(row.relation_kind).strip()}
        if relation_kinds:
            has_compatible = any(detector_class_id in _RELATION_KIND_COMPATIBLE_FAMILIES.get(kind, set()) for kind in relation_kinds)
            has_incompatible = any(detector_class_id in _RELATION_KIND_INCOMPATIBLE_FAMILIES.get(kind, set()) for kind in relation_kinds)
        else:
            has_compatible = False
            has_incompatible = False
        if not has_compatible:
            reasons_missing.append("missing_family_compatibility")
        if has_incompatible:
            reasons_missing.append("family_incompatible_with_relation_kind")
        locality_detail_region_ids = sorted(
            {
                endpoint_by_id[endpoint_id].detail_region_id
                for endpoint_id in inferred_endpoint_ids
                if endpoint_by_id.get(endpoint_id) is not None and endpoint_by_id[endpoint_id].detail_region_id
            }
        )
        locality_subregion_ids = sorted(
            {
                endpoint_by_id[endpoint_id].subregion_id
                for endpoint_id in inferred_endpoint_ids
                if endpoint_by_id.get(endpoint_id) is not None and endpoint_by_id[endpoint_id].subregion_id
            }
        )
        locality_pseudo_page_ids = sorted(
            {
                endpoint_by_id[endpoint_id].pseudo_page_id
                for endpoint_id in inferred_endpoint_ids
                if endpoint_by_id.get(endpoint_id) is not None and endpoint_by_id[endpoint_id].pseudo_page_id
            }
        )
        locality_ok = bool(locality_detail_region_ids or locality_subregion_ids or locality_pseudo_page_ids)
        if not locality_ok:
            reasons_missing.append("missing_locality")
        endpoint_note_support = any(
            bool((endpoint_by_id.get(endpoint_id).metadata or {}).get("has_note_support", False))
            for endpoint_id in inferred_endpoint_ids
            if endpoint_by_id.get(endpoint_id) is not None
        )
        endpoint_legend_ids = [
            str((endpoint_by_id.get(endpoint_id).metadata or {}).get("legend_entry_id", "")).strip()
            for endpoint_id in inferred_endpoint_ids
            if endpoint_by_id.get(endpoint_id) is not None
            and str((endpoint_by_id.get(endpoint_id).metadata or {}).get("legend_entry_id", "")).strip()
        ]
        support_ok = bool(endpoint_note_support or endpoint_legend_ids or link.legend_entry_id)
        if not support_ok:
            reasons_missing.append("missing_legend_or_note_support")
        inferred_rel_conf_max = max((float(row.confidence) for row in inferred_relations), default=0.0)
        inferred_ep_conf_max = max((float(endpoint_by_id[endpoint_id].confidence) for endpoint_id in inferred_endpoint_ids if endpoint_by_id.get(endpoint_id) is not None), default=0.0)
        confidence_ok = inferred_rel_conf_max >= 0.84 or inferred_ep_conf_max >= 0.78
        if not confidence_ok:
            reasons_missing.append("missing_topology_confidence_floor")

        if reasons_missing:
            output.append(link)
            if len(rejected_samples) < 64:
                rejected_samples.append(
                    {
                        "link_id": link.link_id,
                        "instance_id": link.instance_id,
                        "profile_id": profile_id,
                        "detector_class_id": detector_class_id,
                        "current_status": link.status,
                        "relation_kinds": sorted(relation_kinds),
                        "missing_reasons": reasons_missing,
                    }
                )
            continue

        new_status = "linked" if endpoint_legend_ids or link.legend_entry_id else "weakly_linked"
        new_confidence = (
            max(link.confidence, min(0.93, 0.58 + (inferred_rel_conf_max / 2.2)))
            if new_status == "linked"
            else max(link.confidence, min(0.86, 0.5 + (inferred_ep_conf_max / 2.0)))
        )
        legend_entry_id = link.legend_entry_id or (endpoint_legend_ids[0] if endpoint_legend_ids else "")
        upgraded = SiteSchematicSymbolLink(
            link_id=link.link_id,
            page_index=link.page_index,
            instance_id=link.instance_id,
            symbol_token=link.symbol_token,
            status=new_status,
            confidence=round(new_confidence, 4),
            legend_entry_id=legend_entry_id,
            legend_label=link.legend_label,
            room_label=link.room_label,
            related_note_clauses=link.related_note_clauses,
            metadata={
                **metadata,
                "grounding_strengthened": True,
                "grounding_strengthening_rule": "structural_topology_anchor_bridge_v1",
                "grounding_strengthening_original_status": link.status,
                "grounding_strengthening_original_confidence": link.confidence,
                "grounding_strengthening_profile_id": profile_id,
                "grounding_strengthening_detector_class_id": detector_class_id,
                "grounding_strengthening_relation_kinds": sorted(relation_kinds),
                "grounding_strengthening_topology_endpoint_ids": list(inferred_endpoint_ids[:6]),
                "grounding_strengthening_topology_relation_ids": [row.relation_id for row in inferred_relations[:6]],
                "grounding_strengthening_locality": {
                    "detail_region_ids": locality_detail_region_ids,
                    "subregion_ids": locality_subregion_ids,
                    "pseudo_page_ids": locality_pseudo_page_ids,
                },
                "grounding_strengthening_endpoint_note_support": endpoint_note_support,
                "grounding_strengthening_endpoint_legend_ids": endpoint_legend_ids,
                "grounding_strengthening_reasons": [
                    "profile_structural_allowed",
                    "inferred_topology_present",
                    "family_compatibility",
                    "locality_confirmed",
                    "legend_or_note_support",
                    "topology_confidence_floor",
                ],
            },
        )
        output.append(upgraded)
        strengthened_by_profile[profile_id] += 1
        if detector_class_id:
            strengthened_by_family[detector_class_id] += 1
        if len(strengthened_samples) < 64:
            strengthened_samples.append(
                {
                    "link_id": link.link_id,
                    "instance_id": link.instance_id,
                    "profile_id": profile_id,
                    "detector_class_id": detector_class_id,
                    "original_status": link.status,
                    "new_status": new_status,
                    "original_confidence": link.confidence,
                    "new_confidence": round(new_confidence, 4),
                    "relation_kinds": sorted(relation_kinds),
                    "inferred_endpoint_ids": list(inferred_endpoint_ids[:6]),
                    "inferred_relation_ids": [row.relation_id for row in inferred_relations[:6]],
                    "locality_detail_region_ids": locality_detail_region_ids,
                    "locality_subregion_ids": locality_subregion_ids,
                    "locality_pseudo_page_ids": locality_pseudo_page_ids,
                    "legend_ids_used": endpoint_legend_ids,
                    "note_support_used": endpoint_note_support,
                    "rule_name": "structural_topology_anchor_bridge_v1",
                }
            )
    diagnostics: dict[str, object] = {
        "strengthened_anchor_count": sum(strengthened_by_profile.values()),
        "strengthened_by_profile": dict(strengthened_by_profile),
        "strengthened_by_family": dict(strengthened_by_family),
        "strengthened_samples": strengthened_samples,
        "rejected_samples": rejected_samples,
    }
    return tuple(output), diagnostics
