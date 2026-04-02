from __future__ import annotations

import re
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
    append_chronology_edge,
    append_evidence_edge,
    with_strategy_diag,
)

_SPEAKER_RE = re.compile(r"^(?P<speaker>[A-Z][A-Za-z0-9 .'\-/&]{1,50})\s*:\s*(?P<body>.+)$")


class CallTranscriptStrategy:
    name = "call_transcript"
    supported_discourse_types = (DiscourseType.CALL_TRANSCRIPT,)

    def apply(
        self,
        *,
        document_parse: DocumentParse,
        parse_plan: ParsePlan,
        compiled_pack: Any,
    ) -> DocumentParse:
        spans = list(document_parse.evidence_spans)
        if not spans:
            return with_strategy_diag(document_parse, self.name, "no_spans")

        actor_map = {actor.actor_id: actor for actor in document_parse.actor_graph.nodes}
        updated = []
        missing_speaker = 0
        for span in spans:
            match = _SPEAKER_RE.match(span.text.strip())
            speaker_label = None
            if span.speaker_id is None and match:
                speaker_label = match.group("speaker").strip()
            meta = dict(span.metadata)
            if speaker_label:
                meta["inferred_speaker_label"] = speaker_label
            if span.speaker_id:
                meta["speaker_present"] = True
            else:
                missing_speaker += 1
            text = span.normalized_text
            if match and match.group("body").strip():
                text = match.group("body").strip()
            authority = max(span.authority_score, 0.72 if span.speaker_id or speaker_label else span.authority_score)
            updated.append(
                replace(
                    span,
                    normalized_text=text,
                    authority_score=min(1.0, authority),
                    authority_class=AuthorityClass.FIRST_PASS if (span.speaker_id or speaker_label) else span.authority_class,
                    metadata=meta,
                )
            )

        result = replace(document_parse, evidence_spans=tuple(updated))
        ordered = sorted(updated, key=lambda span: (span.chronology_rank if span.chronology_rank is not None else 10**9, span.span_id))
        for left, right in zip(ordered, ordered[1:]):
            result = append_evidence_edge(
                result,
                source_span_id=left.span_id,
                target_span_id=right.span_id,
                relation_type=RelationType.FOLLOWS,
                edge_family="next",
                weight=0.85,
            )
            if left.speaker_id and right.speaker_id and left.speaker_id == right.speaker_id:
                result = append_evidence_edge(
                    result,
                    source_span_id=left.span_id,
                    target_span_id=right.span_id,
                    relation_type=RelationType.SAME_AS,
                    edge_family="same_actor",
                    weight=0.78,
                )
            if left.time_anchor_id and right.time_anchor_id:
                result = append_chronology_edge(
                    result,
                    source_time_anchor_id=left.time_anchor_id,
                    target_time_anchor_id=right.time_anchor_id,
                    relation_type=RelationType.FOLLOWS,
                    edge_family="temporal_before",
                    confidence=0.82,
                )

        if missing_speaker and (missing_speaker / len(spans)) >= 0.25:
            result = add_review_flag(
                result,
                flag_id=f"strategy:{result.doc_id}:call_transcript:missing_speakers",
                severity=ReviewSeverity.WARNING,
                category=ReviewCategory.AMBIGUITY,
                message="Call transcript enrichment found many spans without speaker attribution.",
                metadata={"missing_speaker_count": missing_speaker, "span_count": len(spans)},
            )
        return with_strategy_diag(result, self.name, f"enriched_spans={len(spans)}")
