from __future__ import annotations

from dataclasses import replace
from typing import Any

from orbitbrief_core.parser.router import ParsePlan
from orbitbrief_core.parser.shared.types import AuthorityClass, DiscourseType, DocumentParse, RelationType
from orbitbrief_core.parser.strategies.base import append_evidence_edge, append_thread_edge, with_strategy_diag


class EmailThreadStrategy:
    name = "email_thread"
    supported_discourse_types = (DiscourseType.EMAIL_THREAD,)

    def apply(
        self,
        *,
        document_parse: DocumentParse,
        parse_plan: ParsePlan,
        compiled_pack: Any,
    ) -> DocumentParse:
        spans = []
        for span in document_parse.evidence_spans:
            kind = str(span.metadata.get("kind", ""))
            authority = span.authority_score
            authority_class = span.authority_class
            meta = dict(span.metadata)
            if kind in {"quoted_context", "forwarded_context"}:
                authority = min(authority, 0.35)
                authority_class = AuthorityClass.UNKNOWN
                meta["thread_zone"] = "quoted_or_forwarded"
            elif kind == "email_current":
                authority = max(authority, 0.86)
                authority_class = AuthorityClass.FIRST_PASS
                meta["thread_zone"] = "current_message"
            spans.append(replace(span, authority_score=authority, authority_class=authority_class, metadata=meta))

        result = replace(document_parse, evidence_spans=tuple(spans))

        by_message: dict[str, list[str]] = {}
        for span in spans:
            if span.message_id:
                by_message.setdefault(span.message_id, []).append(span.span_id)
        for message_id, ids in by_message.items():
            for left, right in zip(ids, ids[1:]):
                result = append_evidence_edge(
                    result,
                    source_span_id=left,
                    target_span_id=right,
                    relation_type=RelationType.SAME_AS,
                    edge_family="same_section",
                    weight=0.75,
                    metadata={"message_id": message_id},
                )

        thread_graph = result.thread_graph
        if thread_graph is not None and len(thread_graph.message_nodes) > 1:
            ordered = sorted(thread_graph.message_nodes, key=lambda node: node.message_id)
            for later, earlier in zip(ordered[1:], ordered[:-1]):
                result = append_thread_edge(
                    result,
                    source_message_id=later.message_id,
                    target_message_id=earlier.message_id,
                    relation_type=RelationType.REPLIES_TO,
                    edge_family="reply_to",
                )
        return with_strategy_diag(result, self.name, f"processed_spans={len(spans)}")
