from __future__ import annotations

from dataclasses import replace
from typing import Any

from orbitbrief_core.parser.router import ParsePlan
from orbitbrief_core.parser.shared.types import DiscourseType, DocumentParse, RelationType
from orbitbrief_core.parser.strategies.base import append_evidence_edge, with_strategy_diag

_MEMO_ZONE_HINTS: tuple[tuple[str, str], ...] = (
    ("scope", "scope"),
    ("exclusion", "exclusions"),
    ("assumption", "assumptions"),
    ("deliverable", "deliverables"),
    ("schedule", "schedule"),
    ("responsibilit", "responsibilities"),
    ("risk", "risks"),
    ("dependenc", "dependencies"),
)


class ProjectMemoStrategy:
    name = "project_memo"
    supported_discourse_types = (DiscourseType.PROJECT_MEMO,)

    def apply(
        self,
        *,
        document_parse: DocumentParse,
        parse_plan: ParsePlan,
        compiled_pack: Any,
    ) -> DocumentParse:
        spans = []
        for span in document_parse.evidence_spans:
            section_text = " ".join(span.section_path).lower()
            text = span.normalized_text.lower()
            memo_zone = "general"
            for token, zone in _MEMO_ZONE_HINTS:
                if token in section_text or token in text:
                    memo_zone = zone
                    break
            meta = dict(span.metadata)
            meta["memo_zone"] = memo_zone
            spans.append(replace(span, metadata=meta))

        result = replace(document_parse, evidence_spans=tuple(spans))
        grouped: dict[str, list[str]] = {}
        for span in spans:
            grouped.setdefault(str(span.metadata.get("memo_zone", "general")), []).append(span.span_id)
        support_edges = 0
        for zone, ids in grouped.items():
            for left, right in zip(ids, ids[1:]):
                result = append_evidence_edge(
                    result,
                    source_span_id=left,
                    target_span_id=right,
                    relation_type=RelationType.SUPPORTS,
                    edge_family="supports",
                    weight=0.7,
                    metadata={"memo_zone": zone},
                )
                support_edges += 1
        return with_strategy_diag(result, self.name, f"processed_spans={len(spans)} support_edges={support_edges}")
