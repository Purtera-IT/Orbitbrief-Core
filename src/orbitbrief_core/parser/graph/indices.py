from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from orbitbrief_core.parser.graph.base import EdgeProvenance, NodeProvenance
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
    section_parent_by_id: Mapping[str, str | None]
    section_ancestors_by_id: Mapping[str, tuple[str, ...]]
    span_neighbor_ids: Mapping[str, tuple[str, ...]]
    node_ids_by_family: Mapping[str, tuple[str, ...]]
    edge_ids_by_family: Mapping[str, tuple[str, ...]]
    edge_ids_by_source_pass: Mapping[str, tuple[str, ...]]
    edge_ids_by_pass_family: Mapping[tuple[str, str], tuple[str, ...]]
    edge_ids_by_node_id: Mapping[str, tuple[str, ...]]
    source_span_id_to_node_ids: Mapping[str, tuple[str, ...]]
    node_id_to_source_span_ids: Mapping[str, tuple[str, ...]]
    source_span_id_to_edge_ids: Mapping[str, tuple[str, ...]]
    packet_seed_ids_by_cue_family: Mapping[str, tuple[str, ...]]
    packet_seed_ids_by_source_pass: Mapping[str, tuple[str, ...]]
    node_counts_by_family: Mapping[str, int]
    edge_counts_by_family: Mapping[str, int]
    edge_counts_by_pass: Mapping[str, int]
    node_provenance_by_id: Mapping[str, NodeProvenance]
    edge_provenance_by_id: Mapping[str, EdgeProvenance]

    def neighbors_for_span(self, span_id: str) -> tuple[str, ...]:
        return self.span_neighbor_ids.get(span_id, ())

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
        section_parent_by_id = {node.section_id: node.parent_section_id for node in document_parse.section_tree.nodes}
        section_ancestors_by_id: dict[str, tuple[str, ...]] = {}
        for section_id in sections_by_id:
            ancestors: list[str] = []
            cursor = section_parent_by_id.get(section_id)
            visited: set[str] = set()
            while cursor and cursor not in visited:
                visited.add(cursor)
                ancestors.append(cursor)
                cursor = section_parent_by_id.get(cursor)
            section_ancestors_by_id[section_id] = tuple(ancestors)
        # Deterministic bounded local neighborhood:
        # - direct previous/next in ordered spans
        # - nearby same-section spans (window=2)
        # - nearby same-message spans (window=1)
        order_idx_by_span_id = {span.span_id: idx for idx, span in enumerate(spans)}
        span_neighbor_buckets: dict[str, set[str]] = {span.span_id: set() for span in spans}
        section_window = 2
        message_window = 1

        for idx, span in enumerate(spans):
            if idx > 0:
                span_neighbor_buckets[span.span_id].add(spans[idx - 1].span_id)
            if idx + 1 < len(spans):
                span_neighbor_buckets[span.span_id].add(spans[idx + 1].span_id)

        for section_spans in by_section.values():
            ordered = sorted(section_spans, key=lambda item: order_idx_by_span_id[item.span_id])
            for idx, span in enumerate(ordered):
                left = max(0, idx - section_window)
                right = min(len(ordered), idx + section_window + 1)
                for candidate in ordered[left:right]:
                    if candidate.span_id != span.span_id:
                        span_neighbor_buckets[span.span_id].add(candidate.span_id)

        for message_spans in by_message.values():
            ordered = sorted(message_spans, key=lambda item: order_idx_by_span_id[item.span_id])
            for idx, span in enumerate(ordered):
                left = max(0, idx - message_window)
                right = min(len(ordered), idx + message_window + 1)
                for candidate in ordered[left:right]:
                    if candidate.span_id != span.span_id:
                        span_neighbor_buckets[span.span_id].add(candidate.span_id)

        span_neighbor_ids: dict[str, tuple[str, ...]] = {}
        for span in spans:
            ordered_neighbors = tuple(
                neighbor_id
                for neighbor_id in sorted(
                    span_neighbor_buckets.get(span.span_id, ()),
                    key=lambda sid: (order_idx_by_span_id.get(sid, 10**9), sid),
                )
                if neighbor_id != span.span_id
            )
            span_neighbor_ids[span.span_id] = ordered_neighbors
        thread_nodes = () if document_parse.thread_graph is None else document_parse.thread_graph.message_nodes
        actor_nodes = document_parse.actor_graph.nodes
        time_anchors = document_parse.chronology_graph.time_anchors
        node_ids_by_family: dict[str, list[str]] = {
            "span": [span.span_id for span in spans],
            "section": [node.section_id for node in document_parse.section_tree.nodes],
            "actor": [node.actor_id for node in actor_nodes],
            "time_anchor": [anchor.time_anchor_id for anchor in time_anchors],
            "message": [node.message_id for node in thread_nodes],
            "packet_seed": [],
        }
        source_span_id_to_node_ids: dict[str, list[str]] = {span.span_id: [span.span_id] for span in spans}
        node_id_to_source_span_ids: dict[str, tuple[str, ...]] = {span.span_id: (span.span_id,) for span in spans}

        for node in document_parse.section_tree.nodes:
            span_ids = tuple(node.span_ids)
            node_id_to_source_span_ids[node.section_id] = span_ids
            for span_id in span_ids:
                source_span_id_to_node_ids.setdefault(span_id, []).append(node.section_id)
        for node in thread_nodes:
            span_ids = tuple(node.span_ids)
            node_id_to_source_span_ids[node.message_id] = span_ids
            for span_id in span_ids:
                source_span_id_to_node_ids.setdefault(span_id, []).append(node.message_id)

        packet_seed_ids_by_cue_family: dict[str, list[str]] = {}
        packet_seed_ids_by_source_pass: dict[str, list[str]] = {}
        for idx, seed in enumerate(document_parse.metadata.get("packet_seed_hints", ())):
            if not isinstance(seed, dict):
                continue
            seed_id = f"packet_seed:{idx:04d}:{seed.get('span_id', 'unknown')}"
            node_ids_by_family["packet_seed"].append(seed_id)
            cue_values = seed.get("cue_kinds", ())
            cue_family = str(cue_values[0]) if isinstance(cue_values, (list, tuple)) and cue_values else "unknown"
            packet_seed_ids_by_cue_family.setdefault(cue_family, []).append(seed_id)
            source_pass = str(seed.get("metadata", {}).get("source_pass", "unknown")) if isinstance(seed.get("metadata"), Mapping) else "unknown"
            packet_seed_ids_by_source_pass.setdefault(source_pass, []).append(seed_id)
            span_id = str(seed.get("span_id", ""))
            if span_id:
                node_id_to_source_span_ids[seed_id] = (span_id,)
                source_span_id_to_node_ids.setdefault(span_id, []).append(seed_id)

        edge_ids_by_family: dict[str, list[str]] = {}
        edge_ids_by_source_pass: dict[str, list[str]] = {}
        edge_ids_by_pass_family: dict[tuple[str, str], list[str]] = {}
        edge_ids_by_node_id: dict[str, list[str]] = {}
        source_span_id_to_edge_ids: dict[str, list[str]] = {}
        edge_provenance_by_id: dict[str, EdgeProvenance] = {}
        span_id_set = {span.span_id for span in spans}

        def _register_edge(edge_id: str, edge_type: str, src_id: str, dst_id: str, metadata: Mapping[str, object], weight: float | None) -> None:
            family = str(metadata.get("edge_family", "unspecified"))
            source_pass = str(metadata.get("source_pass", metadata.get("graph_pass", "preexisting")))
            reason_codes = tuple(str(code) for code in metadata.get("reason_codes", []) if str(code))
            edge_ids_by_family.setdefault(family, []).append(edge_id)
            edge_ids_by_source_pass.setdefault(source_pass, []).append(edge_id)
            edge_ids_by_pass_family.setdefault((source_pass, family), []).append(edge_id)
            edge_ids_by_node_id.setdefault(src_id, []).append(edge_id)
            edge_ids_by_node_id.setdefault(dst_id, []).append(edge_id)
            if src_id in span_id_set:
                source_span_id_to_edge_ids.setdefault(src_id, []).append(edge_id)
            if dst_id in span_id_set:
                source_span_id_to_edge_ids.setdefault(dst_id, []).append(edge_id)
            edge_provenance_by_id[edge_id] = EdgeProvenance(
                edge_id=edge_id,
                edge_type=edge_type,
                src_id=src_id,
                dst_id=dst_id,
                source_pass=source_pass,
                reason_codes=reason_codes,
                weight=weight,
                signal_strength=weight,
                metadata=dict(metadata),
            )

        for idx, edge in enumerate(document_parse.evidence_graph.edges):
            edge_id = f"edge:evidence:{idx:06d}:{edge.source_span_id}:{edge.target_span_id}:{edge.relation_type.value}"
            _register_edge(edge_id, edge.relation_type.value, edge.source_span_id, edge.target_span_id, edge.metadata, float(edge.weight))
        for idx, edge in enumerate(document_parse.actor_graph.edges):
            edge_id = f"edge:actor:{idx:06d}:{edge.source_actor_id}:{edge.target_actor_id}:{edge.relation_type.value}"
            _register_edge(edge_id, edge.relation_type.value, edge.source_actor_id, edge.target_actor_id, edge.metadata, float(edge.weight))
        for idx, edge in enumerate(document_parse.chronology_graph.edges):
            edge_id = f"edge:chrono:{idx:06d}:{edge.source_time_anchor_id}:{edge.target_time_anchor_id}:{edge.relation_type.value}"
            _register_edge(edge_id, edge.relation_type.value, edge.source_time_anchor_id, edge.target_time_anchor_id, edge.metadata, float(edge.confidence))
        if document_parse.thread_graph is not None:
            for idx, edge in enumerate(document_parse.thread_graph.edges):
                edge_id = f"edge:thread:{idx:06d}:{edge.source_message_id}:{edge.target_message_id}:{edge.relation_type.value}"
                _register_edge(edge_id, edge.relation_type.value, edge.source_message_id, edge.target_message_id, edge.metadata, None)

        node_provenance_by_id: dict[str, NodeProvenance] = {}
        for span in spans:
            node_provenance_by_id[span.span_id] = NodeProvenance(
                node_id=span.span_id,
                node_family="span",
                source_span_ids=(span.span_id,),
                source_section_id=section_ids_by_path.get(tuple(span.section_path)),
                source_message_id=span.message_id,
                created_by_pass=str(span.metadata.get("source_pass", "adapter")),
                metadata=dict(span.metadata),
            )
        for node in document_parse.section_tree.nodes:
            node_provenance_by_id[node.section_id] = NodeProvenance(
                node_id=node.section_id,
                node_family="section",
                source_span_ids=tuple(node.span_ids),
                source_section_id=node.section_id,
                source_message_id=None,
                created_by_pass=str(node.metadata.get("source_pass", "structural")),
                metadata=dict(node.metadata),
            )
        for node in thread_nodes:
            node_provenance_by_id[node.message_id] = NodeProvenance(
                node_id=node.message_id,
                node_family="message",
                source_span_ids=tuple(node.span_ids),
                source_section_id=node.section_id,
                source_message_id=node.message_id,
                created_by_pass=str(node.metadata.get("source_pass", "thread")),
                metadata=dict(node.metadata),
            )
        for node in actor_nodes:
            node_provenance_by_id[node.actor_id] = NodeProvenance(
                node_id=node.actor_id,
                node_family="actor",
                source_span_ids=(),
                source_section_id=None,
                source_message_id=None,
                created_by_pass=str(node.metadata.get("source_pass", "adapter")),
                metadata=dict(node.metadata),
            )
        for node in time_anchors:
            node_provenance_by_id[node.time_anchor_id] = NodeProvenance(
                node_id=node.time_anchor_id,
                node_family="time_anchor",
                source_span_ids=(),
                source_section_id=None,
                source_message_id=None,
                created_by_pass=str(node.metadata.get("source_pass", "chronology")),
                metadata=dict(node.metadata),
            )

        node_counts_by_family = {family: len(ids) for family, ids in node_ids_by_family.items()}
        edge_counts_by_family = {family: len(ids) for family, ids in edge_ids_by_family.items()}
        edge_counts_by_pass = {pass_name: len(ids) for pass_name, ids in edge_ids_by_source_pass.items()}
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
            section_parent_by_id=section_parent_by_id,
            section_ancestors_by_id=section_ancestors_by_id,
            span_neighbor_ids=span_neighbor_ids,
            node_ids_by_family={key: tuple(value) for key, value in node_ids_by_family.items()},
            edge_ids_by_family={key: tuple(value) for key, value in edge_ids_by_family.items()},
            edge_ids_by_source_pass={key: tuple(value) for key, value in edge_ids_by_source_pass.items()},
            edge_ids_by_pass_family={key: tuple(value) for key, value in edge_ids_by_pass_family.items()},
            edge_ids_by_node_id={key: tuple(value) for key, value in edge_ids_by_node_id.items()},
            source_span_id_to_node_ids={key: tuple(value) for key, value in source_span_id_to_node_ids.items()},
            node_id_to_source_span_ids={key: tuple(value) for key, value in node_id_to_source_span_ids.items()},
            source_span_id_to_edge_ids={key: tuple(value) for key, value in source_span_id_to_edge_ids.items()},
            packet_seed_ids_by_cue_family={key: tuple(value) for key, value in packet_seed_ids_by_cue_family.items()},
            packet_seed_ids_by_source_pass={key: tuple(value) for key, value in packet_seed_ids_by_source_pass.items()},
            node_counts_by_family=node_counts_by_family,
            edge_counts_by_family=edge_counts_by_family,
            edge_counts_by_pass=edge_counts_by_pass,
            node_provenance_by_id=node_provenance_by_id,
            edge_provenance_by_id=edge_provenance_by_id,
        )
