from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from orbitbrief_core.parser.graph.base import GraphPassStat
from orbitbrief_core.parser.graph.cad_signals import (
    is_component,
    is_callout,
    is_note_like,
    is_region_span,
    is_zone_like,
    pair_signals,
    possible_topology_neighbor,
)
from orbitbrief_core.parser.shared.types import EvidenceEdge, EvidenceGraph, RelationType


def _append_edge(document_parse, edge: EvidenceEdge):
    edges = list(document_parse.evidence_graph.edges)
    sig = (edge.source_span_id, edge.target_span_id, edge.relation_type.value, str(edge.metadata.get("edge_family", "")))
    for existing in edges:
        existing_sig = (
            existing.source_span_id,
            existing.target_span_id,
            existing.relation_type.value,
            str(existing.metadata.get("edge_family", "")),
        )
        if existing_sig == sig:
            return document_parse, 0
    edges.append(edge)
    return replace(document_parse, evidence_graph=EvidenceGraph(edges=tuple(edges), metadata=document_parse.evidence_graph.metadata)), 1


def _meta(family: str, reason: str) -> dict[str, object]:
    return {
        "edge_family": family,
        "source_pass": "CadStructuralPass",
        "graph_pass": "CadStructuralPass",
        "reason_codes": [reason],
    }


class CadStructuralPass:
    name = "CadStructuralPass"

    def run(self, *, document_parse, context, indices, signals):
        if document_parse.modality not in {"cad_sheet", "schematic", "floorplan", "drawing_packet", "site_schematic_pdf", "site_schematic_image"}:
            return document_parse, GraphPassStat(self.name, diagnostics=("skipped non-cad modality",))
        out = document_parse
        edges_added = 0
        metadata_updates = 0
        spans = tuple(document_parse.evidence_spans)
        span_by_id = {span.span_id: span for span in spans}
        strategy_meta = dict(document_parse.metadata)
        noisy_ids = {span.span_id for span in spans if bool(span.metadata.get("cad_noise_downgraded"))}

        def _is_noise(span) -> bool:
            return span.span_id in noisy_ids

        # Promote strategy hints first (strong deterministic hints).
        for row in strategy_meta.get("likely_callout_attachments", []):
            if not isinstance(row, Mapping):
                continue
            src_id = row.get("source_span_id")
            dst_id = row.get("target_span_id")
            if not isinstance(src_id, str) or not isinstance(dst_id, str):
                continue
            source = span_by_id.get(src_id)
            target = span_by_id.get(dst_id)
            if source is None or target is None or _is_noise(source) or _is_noise(target):
                continue
            hint_kind = str(row.get("hint_kind", "")).strip().lower()
            confidence = float(row.get("confidence", 0.0) or 0.0)
            if hint_kind == "callout_for" and confidence >= 0.6:
                out, added = _append_edge(
                    out,
                    EvidenceEdge(
                        source_span_id=src_id,
                        target_span_id=dst_id,
                        relation_type=RelationType.REFERENCES,
                        weight=min(0.9, max(0.58, confidence)),
                        metadata={
                            **_meta("callout_for", "strategy_hint_callout_for"),
                            "source_hint": "likely_callout_attachments",
                            "hint_confidence": confidence,
                        },
                    ),
                )
                edges_added += added
            elif hint_kind == "note_attached_to" and confidence >= 0.6:
                out, added = _append_edge(
                    out,
                    EvidenceEdge(
                        source_span_id=src_id,
                        target_span_id=dst_id,
                        relation_type=RelationType.REFERENCES,
                        weight=min(0.88, max(0.56, confidence)),
                        metadata={
                            **_meta("note_attached_to", "strategy_hint_note_attached_to"),
                            "source_hint": "likely_callout_attachments",
                            "hint_confidence": confidence,
                        },
                    ),
                )
                edges_added += added

        for row in strategy_meta.get("likely_zone_associations", []):
            if not isinstance(row, Mapping):
                continue
            zone_id = row.get("zone_span_id")
            component_id = row.get("component_span_id")
            confidence = float(row.get("confidence", 0.0) or 0.0)
            if not isinstance(zone_id, str) or not isinstance(component_id, str) or confidence < 0.58:
                continue
            zone = span_by_id.get(zone_id)
            component = span_by_id.get(component_id)
            if zone is None or component is None or _is_noise(zone) or _is_noise(component):
                continue
            out, added = _append_edge(
                out,
                EvidenceEdge(
                    source_span_id=component_id,
                    target_span_id=zone_id,
                    relation_type=RelationType.REFERENCES,
                    weight=min(0.86, max(0.56, confidence)),
                    metadata={
                        **_meta("component_in_zone", "strategy_hint_component_in_zone"),
                        "source_hint": "likely_zone_associations",
                        "hint_confidence": confidence,
                    },
                ),
            )
            edges_added += added

        # Build deterministic pairwise CAD edges with conservative gating.
        for left in spans:
            if _is_noise(left):
                continue
            for right in spans:
                if left.span_id == right.span_id or _is_noise(right):
                    continue
                sig = pair_signals(left, right, metadata=strategy_meta)
                if not sig.same_sheet:
                    continue
                if sig.same_sheet and (is_region_span(left) or is_region_span(right)):
                    out, added = _append_edge(
                        out,
                        EvidenceEdge(
                            source_span_id=left.span_id,
                            target_span_id=right.span_id,
                            relation_type=RelationType.SAME_AS,
                            weight=0.7,
                            metadata={**_meta("same_sheet", "same_sheet"), "signal_strength": 0.7},
                        ),
                    )
                    edges_added += added
                if sig.inside_region and (is_region_span(left) or is_region_span(right)):
                    out, added = _append_edge(
                        out,
                        EvidenceEdge(
                            source_span_id=left.span_id,
                            target_span_id=right.span_id,
                            relation_type=RelationType.REFERENCES,
                            weight=0.66,
                            metadata={**_meta("inside_region", "bbox_containment"), "overlap_ratio": sig.overlap_ratio},
                        ),
                    )
                    edges_added += added
                if sig.same_zone and is_zone_like(left) and is_zone_like(right):
                    out, added = _append_edge(
                        out,
                        EvidenceEdge(
                            source_span_id=left.span_id,
                            target_span_id=right.span_id,
                            relation_type=RelationType.SAME_AS,
                            weight=0.73,
                            metadata={**_meta("inside_zone", "same_zone")},
                        ),
                    )
                    edges_added += added
                if sig.overlaps:
                    out, added = _append_edge(
                        out,
                        EvidenceEdge(
                            source_span_id=left.span_id,
                            target_span_id=right.span_id,
                            relation_type=RelationType.REFERENCES,
                            weight=0.61,
                            metadata={**_meta("overlaps", "bbox_overlap"), "overlap_ratio": sig.overlap_ratio},
                        ),
                    )
                    edges_added += added
                if sig.near and sig.ocr_confidence_compatibility >= 0.45 and (is_region_span(left) and is_region_span(right)):
                    out, added = _append_edge(
                        out,
                        EvidenceEdge(
                            source_span_id=left.span_id,
                            target_span_id=right.span_id,
                            relation_type=RelationType.REFERENCES,
                            weight=0.62,
                            metadata={**_meta("near", "chronology_proximity"), "bbox_distance": sig.bbox_distance},
                        ),
                    )
                    edges_added += added
                if is_note_like(left) and (is_component(right) or is_zone_like(right)) and (sig.same_note_cluster or sig.near):
                    out, added = _append_edge(
                        out,
                        EvidenceEdge(
                            source_span_id=left.span_id,
                            target_span_id=right.span_id,
                            relation_type=RelationType.REFERENCES,
                            weight=0.67,
                            metadata={**_meta("annotation_for", "note_cluster_or_proximity")},
                        ),
                    )
                    edges_added += added
                if is_callout(left) and (is_component(right) or is_zone_like(right)) and (sig.near or sig.overlaps):
                    out, added = _append_edge(
                        out,
                        EvidenceEdge(
                            source_span_id=left.span_id,
                            target_span_id=right.span_id,
                            relation_type=RelationType.REFERENCES,
                            weight=0.64,
                            metadata={**_meta("callout_for", "callout_locality")},
                        ),
                    )
                    edges_added += added
                if sig.same_title_block_bundle:
                    out, added = _append_edge(
                        out,
                        EvidenceEdge(
                            source_span_id=left.span_id,
                            target_span_id=right.span_id,
                            relation_type=RelationType.SAME_AS,
                            weight=0.84,
                            metadata={**_meta("same_title_block", "same_title_block_bundle")},
                        ),
                    )
                    edges_added += added
                if sig.same_revision_cluster:
                    out, added = _append_edge(
                        out,
                        EvidenceEdge(
                            source_span_id=left.span_id,
                            target_span_id=right.span_id,
                            relation_type=RelationType.SAME_AS,
                            weight=0.79,
                            metadata={**_meta("same_revision_block", "same_revision_bundle")},
                        ),
                    )
                    edges_added += added
                if (is_component(left) and is_zone_like(right)) and (sig.same_zone or sig.near):
                    out, added = _append_edge(
                        out,
                        EvidenceEdge(
                            source_span_id=left.span_id,
                            target_span_id=right.span_id,
                            relation_type=RelationType.REFERENCES,
                            weight=0.64,
                            metadata={**_meta("component_in_zone", "component_zone_proximity")},
                        ),
                    )
                    edges_added += added
                if is_component(left) and is_component(right) and sig.near:
                    out, added = _append_edge(
                        out,
                        EvidenceEdge(
                            source_span_id=left.span_id,
                            target_span_id=right.span_id,
                            relation_type=RelationType.REFERENCES,
                            weight=0.59,
                            metadata={**_meta("component_near_component", "component_locality")},
                        ),
                    )
                    edges_added += added
                if possible_topology_neighbor(left, right) and (sig.component_prefix_match or sig.lexical_overlap >= 0.15):
                    out, added = _append_edge(
                        out,
                        EvidenceEdge(
                            source_span_id=left.span_id,
                            target_span_id=right.span_id,
                            relation_type=RelationType.REFERENCES,
                            weight=0.58,
                            metadata={**_meta("possible_topology_neighbor", "component_topology_hint")},
                        ),
                    )
                    edges_added += added
                if is_zone_like(left) and sig.room_or_closet_pattern_match and any(token in left.normalized_text for token in ("room", "closet")):
                    out, added = _append_edge(
                        out,
                        EvidenceEdge(
                            source_span_id=left.span_id,
                            target_span_id=right.span_id,
                            relation_type=RelationType.SUPPORTS,
                            weight=0.55,
                            metadata={**_meta("possible_support_area", "room_or_closet_pattern")},
                        ),
                    )
                    edges_added += added
                if is_zone_like(left) and any(token in left.normalized_text for token in ("mdf", "idf")) and is_component(right):
                    out, added = _append_edge(
                        out,
                        EvidenceEdge(
                            source_span_id=left.span_id,
                            target_span_id=right.span_id,
                            relation_type=RelationType.SUPPORTS,
                            weight=0.6,
                            metadata={**_meta("possible_distribution_room", "distribution_room_label")},
                        ),
                    )
                    edges_added += added

        # Metadata/authority edges from title/revision bundles into body evidence.
        body_spans = [span for span in spans if not _is_noise(span) and str(span.metadata.get("kind", "")).lower() in {"room_label", "equipment_label", "note_block", "callout", "dimension_text"}]
        for bundle in strategy_meta.get("title_block_bundle", []):
            if not isinstance(bundle, Mapping):
                continue
            field_ids = [
                entry.get("span_id")
                for entry in bundle.get("fields", [])
                if isinstance(entry, Mapping) and isinstance(entry.get("span_id"), str)
            ]
            for field_id in field_ids:
                for body in body_spans[:8]:
                    out, added = _append_edge(
                        out,
                        EvidenceEdge(
                            source_span_id=field_id,
                            target_span_id=body.span_id,
                            relation_type=RelationType.REFERENCES,
                            weight=0.52,
                            metadata={**_meta("sheet_metadata_for", "title_block_to_sheet_body")},
                        ),
                    )
                    edges_added += added
                # preferentially link explicit title fields
                source_span = span_by_id.get(field_id)
                if source_span is not None and "title" in source_span.normalized_text:
                    for body in body_spans[:4]:
                        out, added = _append_edge(
                            out,
                            EvidenceEdge(
                                source_span_id=field_id,
                                target_span_id=body.span_id,
                                relation_type=RelationType.REFERENCES,
                                weight=0.58,
                                metadata={**_meta("sheet_title_for", "sheet_title_field_reference")},
                            ),
                        )
                        edges_added += added

        for bundle in strategy_meta.get("revision_bundle", []):
            if not isinstance(bundle, Mapping):
                continue
            revision_ids = [
                entry.get("span_id")
                for entry in bundle.get("entries", [])
                if isinstance(entry, Mapping) and isinstance(entry.get("span_id"), str)
            ]
            for rev_id in revision_ids:
                for body in body_spans[:8]:
                    out, added = _append_edge(
                        out,
                        EvidenceEdge(
                            source_span_id=rev_id,
                            target_span_id=body.span_id,
                            relation_type=RelationType.REFERENCES,
                            weight=0.5,
                            metadata={**_meta("revision_metadata_for", "revision_bundle_reference")},
                        ),
                    )
                    edges_added += added
                    if any(token in body.normalized_text for token in ("room", "closet", "rack", "ap", "switch")):
                        out, added = _append_edge(
                            out,
                            EvidenceEdge(
                                source_span_id=rev_id,
                                target_span_id=body.span_id,
                                relation_type=RelationType.REFERENCES,
                                weight=0.56,
                                metadata={**_meta("revision_applies_to", "revision_to_labeled_component_or_zone")},
                            ),
                        )
                        edges_added += added

        # Surface reusable CAD signal payload for packetizer/debug.
        signal_rows = []
        sample_candidates = [span for span in spans if not _is_noise(span)][:30]
        for idx, left in enumerate(sample_candidates):
            for right in sample_candidates[idx + 1 :]:
                sig = pair_signals(left, right, metadata=strategy_meta)
                if not sig.same_sheet:
                    continue
                if not (
                    sig.near
                    or sig.same_zone
                    or sig.same_note_cluster
                    or sig.same_revision_cluster
                    or sig.same_title_block_bundle
                    or sig.overlaps
                ):
                    continue
                signal_rows.append(
                    {
                        "left_span_id": left.span_id,
                        "right_span_id": right.span_id,
                        "same_sheet": sig.same_sheet,
                        "same_zone": sig.same_zone,
                        "near": sig.near,
                        "overlap_ratio": round(sig.overlap_ratio, 6),
                        "bbox_distance": sig.bbox_distance,
                        "lexical_overlap": round(sig.lexical_overlap, 6),
                        "ocr_confidence_compatibility": round(sig.ocr_confidence_compatibility, 6),
                        "review_risk": round(max(sig.review_risk_left, sig.review_risk_right), 6),
                    }
                )
        meta = dict(out.metadata)
        meta["cad_signals"] = signal_rows
        out = replace(out, metadata=meta)
        metadata_updates += 1
        return out, GraphPassStat(
            self.name,
            edges_added=edges_added,
            metadata_updates=metadata_updates,
            diagnostics=("emitted cad structural/annotation/topology/metadata edges and cad_signals",),
        )

