from __future__ import annotations

from orbitbrief_core.parser.site_schematic.connector_context_scoring import score_connector_context
from orbitbrief_core.parser.site_schematic.connector_grounding_refinement import refine_with_connector_context
from orbitbrief_core.parser.site_schematic.evidence_backed_flags import (
    evidence_backed_connector_ok,
    evidence_backed_grounded_ok,
    evidence_backed_room_assoc_ok,
)
from orbitbrief_core.parser.site_schematic.grounding_state_policy import choose_grounding_state
from orbitbrief_core.parser.site_schematic.grounded_family_derivation import derive_grounded_family
from orbitbrief_core.parser.site_schematic.legend_grounding_models import GroundedSymbol, LegendGroundingEntry
from orbitbrief_core.parser.site_schematic.packet_family_alias_maps import infer_family_from_packet_context, packet_alias_family
from orbitbrief_core.parser.site_schematic.room_device_association_refinement import score_room_device_association
from orbitbrief_core.parser.site_schematic.semantic_mapper import score_candidate_legend_text_association
from orbitbrief_core.parser.site_schematic.symbol_candidate_grouping import SymbolCandidateGroup


def resolve_grounded_symbols(
    *,
    candidates: list[SymbolCandidateGroup],
    legend_dictionary: list[LegendGroundingEntry],
    sheet_type: str = "",
    packet_id: str = "",
) -> list[GroundedSymbol]:
    out: list[GroundedSymbol] = []
    for candidate in candidates:
        best: LegendGroundingEntry | None = None
        best_score = -1.0
        candidate_alias_tokens = {
            str(token).upper()
            for token in candidate.metadata.get("alias_tokens", ())
            if str(token).strip()
        }
        for entry in legend_dictionary:
            score = 0.0
            if entry.family in candidate.family_candidates:
                score += 1.0
            entry_alias_tokens = {
                str(alias).upper().strip()
                for alias in entry.aliases
                if str(alias).strip()
            }
            if candidate_alias_tokens & entry_alias_tokens:
                score += 1.1
            for hint in candidate.text_hints:
                if hint and hint.lower() in (entry.raw_label or "").lower():
                    score += 0.5
            if score > best_score:
                best = entry
                best_score = score
        mapped_from_packet_alias: str | None = None
        if candidate_alias_tokens:
            for token in candidate_alias_tokens:
                mapped = packet_alias_family(packet_id, token)
                if mapped:
                    mapped_from_packet_alias = mapped
                    break
        inferred_context_family = infer_family_from_packet_context(
            packet_id=packet_id,
            sheet_type=sheet_type,
            alias_tokens=tuple(sorted(candidate_alias_tokens)),
            text_hints=tuple(candidate.text_hints),
        )
        if best is None:
            fallback_family = (
                mapped_from_packet_alias
                or inferred_context_family
                or (candidate.family_candidates[0] if candidate.family_candidates else "unknown_symbol_group")
            )
            inferred_only = fallback_family not in set(candidate.family_candidates)
            fallback_state = "grounded" if inferred_only and fallback_family != "unknown_symbol_group" else "ambiguous"
            fallback_confidence = 0.58 if fallback_state == "grounded" else 0.2
            out.append(
                GroundedSymbol(
                    grounded_id=f"grounded:{candidate.candidate_id}",
                    page_index=candidate.page_index,
                    candidate_id=candidate.candidate_id,
                    family=fallback_family,
                    semantic_meaning="unresolved",
                    bbox=candidate.bbox,
                    confidence=fallback_confidence,
                    status=fallback_state,
                    metadata={
                        "grounding_state": fallback_state,
                        "grounding_state_confidence": fallback_confidence,
                        "grounding_state_reasons": ["no_legend_match_available", "packet_context_backfill"],
                        "grounded_family": fallback_family,
                        "packet_alias_map_used": bool(mapped_from_packet_alias),
                        "packet_context_family_used": bool(inferred_context_family),
                        "legend_match_score": 0.0,
                        "text_association_score": 0.35 if inferred_context_family else 0.0,
                        "legend_text_association_score": 0.35 if inferred_context_family else 0.0,
                        "connector_context_score": 0.0,
                        "room_device_association_score": 0.0,
                        "page_type_compatibility": 0.6 if sheet_type != "unknown" else 0.0,
                    },
                )
            )
            continue
        legend_match_score = 1.0 if best.family in candidate.family_candidates else 0.45
        text_association_score = score_candidate_legend_text_association(
            legend_text=best.raw_label,
            nearby_note_text=" ".join(candidate.text_hints),
            outlet_definition_text=" ".join(candidate.text_hints[:2]),
            abbreviation_text=" ".join(candidate.text_hints[:1]),
        )
        connector_candidate = any(
            fam in {"conduit_pathway", "riser_endpoint", "ladder_rack_runway"}
            for fam in candidate.family_candidates
        )
        has_leader_attachment = any(
            token.lower() in {"to", "from", "run", "route", "riser", "rack", "panel", "conduit", "pathway", "home-run", "homerun"}
            for token in candidate.text_hints
        )
        near_room_label = any(
            token.lower() in {"room", "rm", "idf", "mdf", "tr"}
            or token.lower().startswith(("room", "rm", "idf", "mdf", "tr-"))
            for token in candidate.text_hints
        )
        same_region = bool(candidate.metadata.get("same_region", False) or sheet_type != "unknown")
        same_subregion = bool(
            candidate.metadata.get("same_subregion", False)
            or candidate.metadata.get("seed_kind") in {"box", "polyline", "line"}
            or bool(candidate.metadata.get("alias_tokens"))
        )
        same_pseudo_page = bool(
            candidate.metadata.get("same_pseudo_page", False)
            or sheet_type in {"floorplan_overall", "floorplan_detail", "riser_diagram", "equipment_room_layout", "installation_detail", "rack_detail"}
        )
        connector_refined = refine_with_connector_context(
            base_score=min(1.0, 0.35 + 0.2 * best_score),
            has_connector_candidate=connector_candidate,
            has_leader_attachment=has_leader_attachment,
            riser_context=sheet_type == "riser_diagram",
            rack_pathway_context=sheet_type in {"equipment_room_layout", "installation_detail", "rack_detail"},
        )
        connector_context = score_connector_context(
            connector_candidate_count=2 if connector_candidate else 0,
            leader_attachment_count=1 if has_leader_attachment else 0,
            riser_context=sheet_type == "riser_diagram",
            rack_pathway_context=sheet_type in {"equipment_room_layout", "installation_detail", "rack_detail"},
            equipment_detail_context=sheet_type == "installation_detail",
        )
        room_assoc = score_room_device_association(
            symbol_bbox=candidate.bbox,
            room_label_bboxes=[],
            same_region=same_region,
            same_subregion=same_subregion,
            same_pseudo_page=same_pseudo_page,
            same_detail_frame=sheet_type in {"installation_detail", "rack_detail", "equipment_room_layout"},
            leader_attached=has_leader_attachment,
        )
        room_device_score = room_assoc.score
        page_type_compatibility = 0.95 if sheet_type in {
            "legend_symbol",
            "floorplan_overall",
            "floorplan_detail",
            "equipment_room_layout",
            "rack_detail",
            "riser_diagram",
            "installation_detail",
        } else 0.5
        decision = choose_grounding_state(
            legend_match_score=legend_match_score,
            text_association_score=text_association_score,
            connector_score=max(connector_refined.adjusted_score, connector_context.score),
            room_device_score=room_device_score,
            page_type_compatibility=page_type_compatibility,
        )
        connector_ok = evidence_backed_connector_ok(
            connector_context_score=connector_context.score,
            connector_candidate_count=2 if connector_candidate else 0,
            leader_attachment_count=1 if has_leader_attachment else 0,
        )
        room_assoc_ok = evidence_backed_room_assoc_ok(
            room_device_association_score=room_assoc.score,
            near_room_label=near_room_label,
            same_region=same_region,
            leader_attached=has_leader_attachment,
        )
        grounded_ok = evidence_backed_grounded_ok(
            grounding_state=decision.state,
            legend_match_score=legend_match_score,
            legend_text_association_score=text_association_score,
            connector_context_score=connector_context.score,
            room_device_association_score=room_assoc.score,
            page_type_compatibility=page_type_compatibility,
        )
        status = decision.state
        reasons = list(decision.reasons)
        if status == "grounded" and not grounded_ok:
            status = "ambiguous"
            reasons.append("downgraded_by_truth_audit")
        grounded_family = derive_grounded_family(
            legend_text=best.raw_label or "",
            mapped_semantic_text=best.raw_label or best.family,
            outlet_definition_text=" ".join(candidate.text_hints[:2]),
            page_title=" ".join(candidate.text_hints[:4]),
            page_type=sheet_type,
            connector_context_score=float(connector_context.score),
            room_device_association_score=float(room_assoc.score),
            allowed_families=list(candidate.family_candidates) + [best.family],
        ) or mapped_from_packet_alias or inferred_context_family or best.family
        if status == "grounded" and not grounded_family:
            status = "ambiguous"
            reasons.append("missing_grounded_family")
        out.append(
            GroundedSymbol(
                grounded_id=f"grounded:{candidate.candidate_id}",
                page_index=candidate.page_index,
                candidate_id=candidate.candidate_id,
                family=grounded_family,
                semantic_meaning=best.raw_label or best.family,
                bbox=candidate.bbox,
                legend_ids=(best.legend_id,),
                supporting_text_hints=tuple(candidate.text_hints),
                confidence=min(0.95, max(0.2, decision.confidence)),
                status=status,
                metadata={
                    "family_candidates": list(candidate.family_candidates),
                    "alias_tokens": sorted(candidate_alias_tokens),
                    "grounded_family": grounded_family,
                    "grounding_state": status,
                    "grounding_state_confidence": round(decision.confidence, 4),
                    "grounding_state_reasons": reasons,
                    "legend_match_score": round(legend_match_score, 4),
                    "text_association_score": round(text_association_score, 4),
                    "legend_text_association_score": round(text_association_score, 4),
                    "connector_score": round(connector_refined.adjusted_score, 4),
                    "connector_refinement_reasons": list(connector_refined.reasons),
                    "connector_context_score": round(connector_context.score, 4),
                    "connector_context_reasons": list(connector_context.reasons),
                    "connector_required": connector_candidate,
                    "connector_grounding_ok": connector_ok,
                    "room_device_association_score": round(room_assoc.score, 4),
                    "room_device_association_ok": room_assoc_ok,
                    "room_device_association_reasons": list(room_assoc.reasons),
                    "near_room_label": near_room_label,
                    "same_region": same_region,
                    "same_subregion": same_subregion,
                    "same_pseudo_page": same_pseudo_page,
                    "leader_attached": has_leader_attachment,
                    "page_type_compatibility": round(page_type_compatibility, 4),
                    "packet_memory_transfer": bool(best.legend_id.startswith("memory:")),
                    "packet_alias_map_used": bool(mapped_from_packet_alias),
                },
            )
        )
    return out
