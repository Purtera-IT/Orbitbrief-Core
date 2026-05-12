from __future__ import annotations

from orbitbrief_core.parser.shared.types import DiscourseType, RelationType
from orbitbrief_core.parser.strategies.base import append_evidence_edge, mark_strategy_applied, with_strategy_diag


class SpreadsheetRosterStrategy:
    name = "spreadsheet_roster"
    supported_discourse_types = (
        DiscourseType.PROJECT_MEMO,
        DiscourseType.HYBRID_NOTES_MEMO,
        DiscourseType.MEETING_NOTES,
    )

    def apply(self, *, document_parse, parse_plan, compiled_pack):
        _ = parse_plan
        _ = compiled_pack
        spans = list(document_parse.evidence_spans)
        kv_spans = [span for span in spans if str(span.metadata.get("kind", "")) == "spreadsheet_kv"]
        row_spans = [span for span in spans if str(span.metadata.get("kind", "")) == "spreadsheet_row"]
        enriched = document_parse
        linked = 0
        for kv_span in kv_spans:
            kv_families = {str(item) for item in kv_span.metadata.get("packet_families", ()) if str(item)}
            if not kv_families:
                continue
            for row_span in row_spans:
                row_families = {str(item) for item in row_span.metadata.get("packet_families", ()) if str(item)}
                if not row_families or not (kv_families & row_families):
                    continue
                enriched = append_evidence_edge(
                    enriched,
                    source_span_id=kv_span.span_id,
                    target_span_id=row_span.span_id,
                    relation_type=RelationType.REFERENCES,
                    edge_family="spreadsheet_summary_row",
                    weight=0.72,
                    metadata={
                        "shared_packet_families": sorted(kv_families & row_families),
                        "strategy": self.name,
                    },
                )
                linked += 1
        enriched = mark_strategy_applied(enriched, self.name)
        return with_strategy_diag(enriched, self.name, f"summary_links={linked};kv={len(kv_spans)};rows={len(row_spans)}")
