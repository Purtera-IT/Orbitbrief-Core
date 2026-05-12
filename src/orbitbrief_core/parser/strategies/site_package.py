from __future__ import annotations

from dataclasses import replace
from typing import Any

from orbitbrief_core.parser.shared.types import RelationType, ReviewCategory, ReviewSeverity
from orbitbrief_core.parser.strategies.base import (
    add_review_flag,
    append_evidence_edge,
    mark_strategy_applied,
    with_strategy_diag,
)


class SitePackageStrategy:
    name = "site_package"
    _CAD_MODALITIES = {"cad_sheet", "schematic", "floorplan", "drawing_packet", "site_schematic_pdf", "site_schematic_image"}
    _NOISE_TOKENS = ("legend", "symbol table", "drawing notes", "general symbol", "north arrow", "scale bar", "boilerplate", "stamp")
    _SCOPE_LIKE_TOKENS = ("scope", "install", "replace", "remove", "provide", "support")
    _LOGISTICS_TOKENS = ("badge", "escort", "access", "loading dock", "security", "after-hours")
    _CONSTRUCTABILITY_TOKENS = ("constraint", "dependency", "blocked", "clearance", "coordination", "permit")

    @staticmethod
    def _kind(span) -> str:
        return str(span.metadata.get("kind", "")).strip().lower()

    @staticmethod
    def _sheet_id(span) -> str:
        section = tuple(span.section_path)
        if len(section) >= 2:
            return f"{section[0]}/{section[1]}"
        if section:
            return section[0]
        return "unknown_sheet"

    @staticmethod
    def _by_sheet(spans: list[Any]) -> dict[str, list[Any]]:
        out: dict[str, list[Any]] = {}
        for span in spans:
            out.setdefault(SitePackageStrategy._sheet_id(span), []).append(span)
        return out

    @staticmethod
    def _cluster_kind(text: str) -> str:
        lower = text.lower()
        if any(token in lower for token in SitePackageStrategy._SCOPE_LIKE_TOKENS):
            return "scope_like"
        if any(token in lower for token in SitePackageStrategy._LOGISTICS_TOKENS):
            return "logistics_like"
        if any(token in lower for token in SitePackageStrategy._CONSTRUCTABILITY_TOKENS):
            return "constructability_like"
        if any(token in lower for token in SitePackageStrategy._NOISE_TOKENS):
            return "metadata_or_noise"
        return "uncertain"

    @staticmethod
    def _rank(span) -> int:
        if isinstance(span.chronology_rank, int):
            return span.chronology_rank
        return 10**9

    @classmethod
    def _nearest(cls, source, candidates: list[Any], max_delta: int = 6):
        if not candidates:
            return None
        s_rank = cls._rank(source)
        best = None
        best_delta = max_delta + 1
        for candidate in candidates:
            delta = abs(cls._rank(candidate) - s_rank)
            if delta < best_delta:
                best = candidate
                best_delta = delta
        return best if best is not None and best_delta <= max_delta else None

    def apply(self, *, document_parse, parse_plan, compiled_pack):
        _ = parse_plan
        _ = compiled_pack
        if document_parse.modality not in self._CAD_MODALITIES:
            return with_strategy_diag(mark_strategy_applied(document_parse, self.name), self.name, "skipped_non_cad_modality")

        spans = list(document_parse.evidence_spans)
        out = document_parse
        links = 0

        title_block_spans = [span for span in spans if self._kind(span) in {"sheet_ref", "title_block", "title_block_field"}]
        revision_spans = [span for span in spans if self._kind(span) == "revision_block"]
        note_spans = [span for span in spans if self._kind(span) in {"note_block", "callout"}]
        room_spans = [span for span in spans if self._kind(span) in {"room_label"}]
        closet_spans = [span for span in spans if self._kind(span) in {"room_label"} and any(token in span.normalized_text.lower() for token in ("closet", "mdf", "idf"))]
        equipment_spans = [span for span in spans if self._kind(span) in {"equipment_label"}]
        dimension_spans = [span for span in spans if self._kind(span) in {"dimension_text"}]
        callout_spans = [span for span in spans if self._kind(span) == "callout"]
        zone_spans = room_spans + closet_spans
        noise_spans = [
            span
            for span in spans
            if any(token in span.normalized_text.lower() for token in self._NOISE_TOKENS)
            or self._kind(span) in {"legend", "table", "symbol_table"}
        ]
        sheet_groups = self._by_sheet(spans)

        # Title-block authority bundling + same-sheet coherence.
        title_block_bundle = []
        for sheet_id, sheet_spans in self._by_sheet(title_block_spans).items():
            fields = []
            for span in sorted(sheet_spans, key=lambda item: (self._rank(item), item.span_id)):
                fields.append(
                    {
                        "span_id": span.span_id,
                        "text": span.text,
                        "kind": self._kind(span),
                        "confidence": round(max(0.72, float(span.authority_score)), 6),
                        "provenance": {"sheet_id": sheet_id, "section_path": list(span.section_path)},
                    }
                )
            title_block_bundle.append(
                {
                    "sheet_id": sheet_id,
                    "fields": fields,
                    "authority_boost": 0.15,
                    "confidence": round(min(1.0, 0.78 + (0.03 * len(fields))), 6),
                }
            )
            for left in sheet_spans:
                for right in sheet_spans:
                    if left.span_id == right.span_id:
                        continue
                    out = append_evidence_edge(
                        out,
                        source_span_id=left.span_id,
                        target_span_id=right.span_id,
                        relation_type=RelationType.SAME_AS,
                        edge_family="same_title_block",
                        weight=0.84,
                        metadata={"strategy": self.name, "reason_codes": ["same_title_block"], "sheet_id": sheet_id},
                    )
                    links += 1

        # Revision block separation.
        revision_bundle = []
        for sheet_id, sheet_spans in self._by_sheet(revision_spans).items():
            entries = []
            for span in sorted(sheet_spans, key=lambda item: (self._rank(item), item.span_id)):
                entries.append(
                    {
                        "span_id": span.span_id,
                        "text": span.text,
                        "confidence": round(max(0.65, float(span.authority_score)), 6),
                        "provenance": {"sheet_id": sheet_id, "section_path": list(span.section_path)},
                    }
                )
            revision_bundle.append({"sheet_id": sheet_id, "entries": entries, "separated": True})
            for zone in zone_spans:
                if self._sheet_id(zone) != sheet_id:
                    continue
                for rev in sheet_spans:
                    out = append_evidence_edge(
                        out,
                        source_span_id=zone.span_id,
                        target_span_id=rev.span_id,
                        relation_type=RelationType.REFERENCES,
                        edge_family="same_revision_block",
                        weight=0.58,
                        metadata={"strategy": self.name, "reason_codes": ["same_revision_block"], "sheet_id": sheet_id},
                    )
                    links += 1

        # Note clusters + callout attachments as hints (not final claims).
        note_clusters = []
        likely_callout_attachments = []
        for sheet_id, sheet_spans in self._by_sheet(note_spans).items():
            cluster_rows = []
            local_equipment = [span for span in equipment_spans if self._sheet_id(span) == sheet_id]
            local_zones = [span for span in zone_spans if self._sheet_id(span) == sheet_id]
            for span in sorted(sheet_spans, key=lambda item: (self._rank(item), item.span_id)):
                cluster_rows.append(
                    {
                        "span_id": span.span_id,
                        "text": span.text,
                        "cluster_kind": self._cluster_kind(span.text),
                        "confidence": round(max(0.52, float(span.authority_score)), 6),
                    }
                )
                target = self._nearest(span, local_equipment, max_delta=6) or self._nearest(span, local_zones, max_delta=6)
                if target is None:
                    continue
                out = append_evidence_edge(
                    out,
                    source_span_id=span.span_id,
                    target_span_id=target.span_id,
                    relation_type=RelationType.REFERENCES,
                    edge_family="note_attached_to",
                    weight=0.66,
                    metadata={"strategy": self.name, "reason_codes": ["note_attached_to"], "sheet_id": sheet_id},
                )
                links += 1
                likely_callout_attachments.append(
                    {
                        "sheet_id": sheet_id,
                        "source_span_id": span.span_id,
                        "target_span_id": target.span_id,
                        "hint_kind": "note_attached_to",
                        "confidence": 0.66,
                    }
                )
                if self._kind(span) == "callout":
                    likely_callout_attachments.append(
                        {
                            "sheet_id": sheet_id,
                            "source_span_id": span.span_id,
                            "target_span_id": target.span_id,
                            "hint_kind": "callout_for",
                            "confidence": 0.64,
                        }
                    )
            note_clusters.append({"sheet_id": sheet_id, "items": cluster_rows})

        # Room/closet grouping + equipment clusters + zone associations.
        room_or_closet_clusters = []
        equipment_clusters = []
        likely_zone_associations = []
        for sheet_id, _sheet_spans in sheet_groups.items():
            local_rooms = [span for span in room_spans if self._sheet_id(span) == sheet_id]
            local_closets = [span for span in closet_spans if self._sheet_id(span) == sheet_id]
            local_equipment = [span for span in equipment_spans if self._sheet_id(span) == sheet_id]
            local_dimensions = [span for span in dimension_spans if self._sheet_id(span) == sheet_id]
            local_callouts = [span for span in callout_spans if self._sheet_id(span) == sheet_id]
            zone_members = []
            unique_zones = {span.span_id: span for span in [*local_rooms, *local_closets]}
            for zone in sorted(unique_zones.values(), key=lambda item: (self._rank(item), item.span_id)):
                members = []
                for eq in local_equipment:
                    if abs(self._rank(zone) - self._rank(eq)) <= 6:
                        members.append(eq.span_id)
                        out = append_evidence_edge(
                            out,
                            source_span_id=eq.span_id,
                            target_span_id=zone.span_id,
                            relation_type=RelationType.REFERENCES,
                            edge_family="component_in_zone",
                            weight=0.62,
                            metadata={"strategy": self.name, "reason_codes": ["component_in_zone"], "sheet_id": sheet_id},
                        )
                        links += 1
                        likely_zone_associations.append(
                            {
                                "sheet_id": sheet_id,
                                "zone_span_id": zone.span_id,
                                "component_span_id": eq.span_id,
                                "hint_kind": "component_in_zone",
                                "confidence": 0.62,
                            }
                        )
                zone_members.append(
                    {
                        "zone_span_id": zone.span_id,
                        "zone_text": zone.text,
                        "kind": "closet" if zone in local_closets else "room",
                        "member_span_ids": members,
                    }
                )
            room_or_closet_clusters.append({"sheet_id": sheet_id, "zones": zone_members})

            for eq in local_equipment:
                nearby_dimensions = [span.span_id for span in local_dimensions if abs(self._rank(eq) - self._rank(span)) <= 5]
                nearby_callouts = [span.span_id for span in local_callouts if abs(self._rank(eq) - self._rank(span)) <= 5]
                equipment_clusters.append(
                    {
                        "sheet_id": sheet_id,
                        "equipment_span_id": eq.span_id,
                        "equipment_text": eq.text,
                        "nearby_dimension_span_ids": nearby_dimensions,
                        "nearby_callout_span_ids": nearby_callouts,
                        "confidence": round(max(0.58, float(eq.authority_score)), 6),
                    }
                )

        # Legend/border/schedule-noise downgrade (review-aware).
        downgraded_noise_regions = []
        if noise_spans:
            updated_spans = list(out.evidence_spans)
            idx_by_id = {span.span_id: idx for idx, span in enumerate(updated_spans)}
            for span in noise_spans:
                idx = idx_by_id.get(span.span_id)
                if idx is None:
                    continue
                new_meta = dict(updated_spans[idx].metadata)
                new_meta["cad_noise_downgraded"] = True
                updated_spans[idx] = replace(
                    updated_spans[idx],
                    authority_score=max(0.05, float(updated_spans[idx].authority_score) * 0.5),
                    metadata=new_meta,
                )
                downgraded_noise_regions.append(
                    {
                        "span_id": span.span_id,
                        "text": span.text,
                        "sheet_id": self._sheet_id(span),
                        "reason": "legend_or_border_noise",
                    }
                )
            out = replace(out, evidence_spans=tuple(updated_spans))
            if len(noise_spans) >= 3:
                out = add_review_flag(
                    out,
                    flag_id=f"flag:{out.doc_id}:cad_noise_heavy",
                    severity=ReviewSeverity.WARNING,
                    category=ReviewCategory.QUALITY,
                    message="Drawing contains heavy legend/border/admin text; semantic confidence should be conservative.",
                    metadata={"strategy": self.name, "noise_span_count": len(noise_spans)},
                )

        # Strategy output bundles are pre-graph interpreted hints, not final claims.
        metadata = dict(out.metadata)
        metadata["title_block_bundle"] = title_block_bundle
        metadata["revision_bundle"] = revision_bundle
        metadata["note_clusters"] = note_clusters
        metadata["room_or_closet_clusters"] = room_or_closet_clusters
        metadata["equipment_clusters"] = equipment_clusters
        metadata["likely_callout_attachments"] = likely_callout_attachments
        metadata["likely_zone_associations"] = likely_zone_associations
        metadata["downgraded_noise_regions"] = downgraded_noise_regions
        out = replace(out, metadata=metadata)

        out = mark_strategy_applied(out, self.name)
        return with_strategy_diag(
            out,
            self.name,
            (
                f"site_links={links};title_blocks={len(title_block_bundle)};revisions={len(revision_bundle)};"
                f"note_clusters={len(note_clusters)};zone_clusters={len(room_or_closet_clusters)};"
                f"equipment_clusters={len(equipment_clusters)};noise_downgraded={len(downgraded_noise_regions)}"
            ),
        )

