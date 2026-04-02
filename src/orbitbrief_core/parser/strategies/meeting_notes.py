from __future__ import annotations

from dataclasses import replace
from typing import Any

from orbitbrief_core.parser.router import ParsePlan
from orbitbrief_core.parser.shared.types import (
    AuthorityClass,
    DiscourseType,
    DocumentParse,
    RelationType,
    ReviewCategory,
    ReviewSeverity,
)
from orbitbrief_core.parser.strategies.base import (
    BaseStrategy,
    add_review_flag,
    append_evidence_edge,
    with_strategy_diag,
)

_ZONE_HINTS: tuple[tuple[str, str], ...] = (
    ("scope", "scope"),
    ("assumption", "assumptions"),
    ("deliverable", "deliverables"),
    ("schedule", "schedule"),
    ("dependency", "dependencies"),
    ("risk", "risks"),
    ("question", "open_questions"),
    ("action item", "actions"),
)


class MeetingNotesStrategy:
    name = "meeting_notes"
    supported_discourse_types = (DiscourseType.MEETING_NOTES,)

    def apply(
        self,
        *,
        document_parse: DocumentParse,
        parse_plan: ParsePlan,
        compiled_pack: Any,
    ) -> DocumentParse:
        spans = []
        for span in document_parse.evidence_spans:
            text = span.normalized_text.lower()
            zone = "general"
            for token, zone_name in _ZONE_HINTS:
                if token in text:
                    zone = zone_name
                    break
            meta = dict(span.metadata)
            meta["notes_zone"] = zone
            authority = max(span.authority_score, 0.7 if zone in {"actions", "open_questions"} else span.authority_score)
            spans.append(replace(span, metadata=meta, authority_score=min(1.0, authority), authority_class=AuthorityClass.FIRST_PASS))

        result = replace(document_parse, evidence_spans=tuple(spans))
        grouped: dict[str, list[str]] = {}
        for span in spans:
            grouped.setdefault(str(span.metadata.get("notes_zone", "general")), []).append(span.span_id)
        for zone, ids in grouped.items():
            for left, right in zip(ids, ids[1:]):
                result = append_evidence_edge(
                    result,
                    source_span_id=left,
                    target_span_id=right,
                    relation_type=RelationType.SAME_AS,
                    edge_family="same_section",
                    weight=0.72,
                    metadata={"notes_zone": zone},
                )
        if "general" in grouped and len(grouped["general"]) >= 5:
            result = add_review_flag(
                result,
                flag_id=f"strategy:{result.doc_id}:meeting_notes:flat_structure",
                severity=ReviewSeverity.INFO,
                category=ReviewCategory.QUALITY,
                message="Meeting notes remain largely flat; consider stronger heading structure.",
                metadata={"general_span_count": len(grouped["general"])},
            )
        return with_strategy_diag(result, self.name, f"zones={len(grouped)}")
