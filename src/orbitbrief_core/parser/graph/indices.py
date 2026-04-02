from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from orbitbrief_core.parser.shared.types import ActorNode, DocumentParse, EvidenceSpan, MessageNode, SectionNode, TimeAnchor


@dataclass(frozen=True, slots=True)
class GraphIndices:
    ordered_spans: tuple[EvidenceSpan, ...]
    spans_by_id: Mapping[str, EvidenceSpan]
    spans_by_section_path: Mapping[tuple[str, ...], tuple[EvidenceSpan, ...]]
    spans_by_message_id: Mapping[str, tuple[EvidenceSpan, ...]]
    spans_by_actor_id: Mapping[str, tuple[EvidenceSpan, ...]]
    spans_by_time_anchor_id: Mapping[str, tuple[EvidenceSpan, ...]]
    sections_by_id: Mapping[str, SectionNode]
    section_ids_by_path: Mapping[tuple[str, ...], str]
    messages_by_id: Mapping[str, MessageNode]
    actors_by_id: Mapping[str, ActorNode]
    time_anchors_by_id: Mapping[str, TimeAnchor]

    @classmethod
    def from_parse(cls, document_parse: DocumentParse) -> "GraphIndices":
        spans = tuple(
            sorted(
                document_parse.evidence_spans,
                key=lambda span: (
                    span.chronology_rank if span.chronology_rank is not None else 10**9,
                    span.page_ref.page_index if span.page_ref is not None else 10**9,
                    span.char_range.start if span.char_range is not None else 10**9,
                    span.span_id,
                ),
            )
        )
        by_section: dict[tuple[str, ...], list[EvidenceSpan]] = {}
        by_message: dict[str, list[EvidenceSpan]] = {}
        by_actor: dict[str, list[EvidenceSpan]] = {}
        by_anchor: dict[str, list[EvidenceSpan]] = {}
        for span in spans:
            by_section.setdefault(tuple(span.section_path), []).append(span)
            if span.message_id:
                by_message.setdefault(span.message_id, []).append(span)
            for actor_id in (span.speaker_id, span.author_id):
                if actor_id:
                    by_actor.setdefault(actor_id, []).append(span)
            if span.time_anchor_id:
                by_anchor.setdefault(span.time_anchor_id, []).append(span)

        sections_by_id = {node.section_id: node for node in document_parse.section_tree.nodes}
        section_ids_by_path = {node.section_path: node.section_id for node in document_parse.section_tree.nodes if node.section_path}
        thread_nodes = () if document_parse.thread_graph is None else document_parse.thread_graph.message_nodes
        actor_nodes = document_parse.actor_graph.nodes
        time_anchors = document_parse.chronology_graph.time_anchors
        return cls(
            ordered_spans=spans,
            spans_by_id={span.span_id: span for span in spans},
            spans_by_section_path={key: tuple(value) for key, value in by_section.items()},
            spans_by_message_id={key: tuple(value) for key, value in by_message.items()},
            spans_by_actor_id={key: tuple(value) for key, value in by_actor.items()},
            spans_by_time_anchor_id={key: tuple(value) for key, value in by_anchor.items()},
            sections_by_id=sections_by_id,
            section_ids_by_path=section_ids_by_path,
            messages_by_id={node.message_id: node for node in thread_nodes},
            actors_by_id={node.actor_id: node for node in actor_nodes},
            time_anchors_by_id={anchor.time_anchor_id: anchor for anchor in time_anchors},
        )
