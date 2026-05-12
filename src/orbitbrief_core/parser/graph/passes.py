from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import Iterable

from orbitbrief_core.parser.graph.base import GraphContext as PassContext, GraphPassStat, PacketSeedHint
from orbitbrief_core.parser.graph.indices import GraphIndices
from orbitbrief_core.parser.graph.neural_hooks import PacketSeedRequest, SameTopicRequest, SupportRequest
from orbitbrief_core.parser.graph.scorers.policy import apply_fanout, evaluate_score_result
from orbitbrief_core.parser.graph.signals import GraphSignals, normalized_cue_values, packet_families_for_span, packet_seed_score
from orbitbrief_core.parser.shared.types import (
    ActorEdge,
    ActorGraph,
    ChronologyEdge,
    ChronologyGraph,
    EvidenceEdge,
    EvidenceGraph,
    RelationType,
    ReviewCategory,
    ReviewFlag,
    ReviewSeverity,
    SectionTree,
    TimeAnchor,
    ThreadEdge,
    ThreadGraph,
)


_ALLOWED_REASON_CODES = {
    "adjacent_in_document_order",
    "same_parent_section",
    "section_parent_child",
    "explicit_reply_header",
    "message_order_adjacency",
    "quoted_boundary_match",
    "forwarded_header_detected",
    "same_normalized_speaker",
    "explicit_timestamp_order",
    "same_resolved_time_anchor",
    "turn_sequence_adjacency",
    "message_sender_match",
    "transcript_speaker_match",
    "quoted_sender_match",
    "forwarded_sender_match",
    "cue_tagger_attachment",
    "packet_seed_family_match",
    "same_section_context",
    "actor_exact_match",
    "preexisting_edge",
    "same_topic_neural_score",
    "support_neural_score",
    "packet_seed_neural_score",
    "same_section_prefilter",
    "lexical_overlap_prefilter",
    "cue_family_compatible",
    "support_prefilter",
    "within_fanout",
}


def _normalized_reason_codes(reason_codes: Iterable[str]) -> list[str]:
    codes = [str(code).strip() for code in reason_codes if str(code).strip()]
    if not codes:
        return ["preexisting_edge"]
    normalized = [code if code in _ALLOWED_REASON_CODES else "preexisting_edge" for code in codes]
    return list(dict.fromkeys(normalized))


def _with_reason_metadata(
    *,
    source_pass: str,
    edge_family: str,
    reason_codes: Iterable[str],
    metadata: dict | None = None,
) -> dict:
    payload = dict(metadata or {})
    payload["source_pass"] = source_pass
    payload["graph_pass"] = source_pass
    payload["edge_family"] = edge_family
    payload["reason_codes"] = _normalized_reason_codes(reason_codes)
    return payload


def _append_flag(
    document_parse,
    flag_id: str,
    severity: ReviewSeverity,
    category: ReviewCategory,
    message: str,
    *,
    span_id: str | None = None,
    metadata: dict | None = None,
):
    if any(flag.flag_id == flag_id for flag in document_parse.review_flags):
        return document_parse, 0
    flags = list(document_parse.review_flags)
    flags.append(
        ReviewFlag(
            flag_id=flag_id,
            severity=severity,
            category=category,
            message=message,
            span_id=span_id,
            metadata=dict(metadata or {}),
        )
    )
    return replace(document_parse, review_flags=tuple(flags)), 1


def _append_evidence_edge(document_parse, edge: EvidenceEdge):
    edges = list(document_parse.evidence_graph.edges)
    family = str(edge.metadata.get("edge_family", ""))
    if edge.relation_type is RelationType.SAME_AS:
        ordered = tuple(sorted((edge.source_span_id, edge.target_span_id)))
        sig = (ordered[0], ordered[1], edge.relation_type.value, family)
    else:
        sig = (edge.source_span_id, edge.target_span_id, edge.relation_type.value, family)
    for existing in edges:
        existing_family = str(existing.metadata.get("edge_family", ""))
        if existing.relation_type is RelationType.SAME_AS:
            ordered = tuple(sorted((existing.source_span_id, existing.target_span_id)))
            cur = (ordered[0], ordered[1], existing.relation_type.value, existing_family)
        else:
            cur = (
                existing.source_span_id,
                existing.target_span_id,
                existing.relation_type.value,
                existing_family,
            )
        if cur == sig:
            return document_parse, 0
    edges.append(edge)
    return replace(document_parse, evidence_graph=EvidenceGraph(edges=tuple(edges), metadata=document_parse.evidence_graph.metadata)), 1


def _append_thread_edge(document_parse, edge: ThreadEdge):
    if document_parse.thread_graph is None:
        return document_parse, 0
    edges = list(document_parse.thread_graph.edges)
    sig = (edge.source_message_id, edge.target_message_id, edge.relation_type.value, str(edge.metadata.get("edge_family", "")))
    for existing in edges:
        cur = (
            existing.source_message_id,
            existing.target_message_id,
            existing.relation_type.value,
            str(existing.metadata.get("edge_family", "")),
        )
        if cur == sig:
            return document_parse, 0
    edges.append(edge)
    return (
        replace(
            document_parse,
            thread_graph=ThreadGraph(
                thread_id=document_parse.thread_graph.thread_id,
                message_nodes=document_parse.thread_graph.message_nodes,
                edges=tuple(edges),
                metadata=document_parse.thread_graph.metadata,
            ),
        ),
        1,
    )


def _append_actor_edge(document_parse, edge: ActorEdge):
    edges = list(document_parse.actor_graph.edges)
    family = str(edge.metadata.get("edge_family", ""))
    if edge.relation_type is RelationType.SAME_AS:
        ordered = tuple(sorted((edge.source_actor_id, edge.target_actor_id)))
        sig = (ordered[0], ordered[1], edge.relation_type.value, family)
    else:
        sig = (edge.source_actor_id, edge.target_actor_id, edge.relation_type.value, family)
    for existing in edges:
        existing_family = str(existing.metadata.get("edge_family", ""))
        if existing.relation_type is RelationType.SAME_AS:
            ordered = tuple(sorted((existing.source_actor_id, existing.target_actor_id)))
            cur = (ordered[0], ordered[1], existing.relation_type.value, existing_family)
        else:
            cur = (
                existing.source_actor_id,
                existing.target_actor_id,
                existing.relation_type.value,
                existing_family,
            )
        if cur == sig:
            return document_parse, 0
    edges.append(edge)
    return replace(
        document_parse,
        actor_graph=ActorGraph(
            nodes=document_parse.actor_graph.nodes,
            edges=tuple(edges),
            primary_actor_id=document_parse.actor_graph.primary_actor_id,
            metadata=document_parse.actor_graph.metadata,
        ),
    ), 1


def _append_chrono_edge(document_parse, edge: ChronologyEdge):
    edges = list(document_parse.chronology_graph.edges)
    sig = (edge.source_time_anchor_id, edge.target_time_anchor_id, edge.relation_type.value, str(edge.metadata.get("edge_family", "")))
    for existing in edges:
        cur = (
            existing.source_time_anchor_id,
            existing.target_time_anchor_id,
            existing.relation_type.value,
            str(existing.metadata.get("edge_family", "")),
        )
        if cur == sig:
            return document_parse, 0
    edges.append(edge)
    return (
        replace(
            document_parse,
            chronology_graph=ChronologyGraph(
                time_anchors=document_parse.chronology_graph.time_anchors,
                edges=tuple(edges),
                metadata=document_parse.chronology_graph.metadata,
            ),
        ),
        1,
    )


class StructuralPass:
    name = "StructuralPass"

    def run(self, *, document_parse, context: PassContext, indices: GraphIndices, signals: GraphSignals):
        edges_added = 0
        sections_touched = 0
        section_map = {node.section_id: node for node in document_parse.section_tree.nodes}
        section_path_to_id = {node.section_path: node.section_id for node in document_parse.section_tree.nodes if node.section_path}
        section_to_span_ids: dict[str, list[str]] = {sid: list(node.span_ids) for sid, node in section_map.items()}
        for span in indices.ordered_spans:
            section_id = section_path_to_id.get(tuple(span.section_path))
            if section_id:
                bucket = section_to_span_ids.setdefault(section_id, [])
                if span.span_id not in bucket:
                    bucket.append(span.span_id)
                    sections_touched += 1

        new_sections = []
        for node in document_parse.section_tree.nodes:
            merged = tuple(sorted(set(section_to_span_ids.get(node.section_id, []))))
            new_sections.append(replace(node, span_ids=merged))
        out = replace(
            document_parse,
            section_tree=SectionTree(
                nodes=tuple(sorted(new_sections, key=lambda n: n.section_id)),
                root_section_id=document_parse.section_tree.root_section_id,
                metadata=document_parse.section_tree.metadata,
            ),
        )

        refreshed = GraphIndices.from_parse(out)
        for left, right in zip(refreshed.ordered_spans, refreshed.ordered_spans[1:]):
            out, added = _append_evidence_edge(
                out,
                EvidenceEdge(
                    source_span_id=left.span_id,
                    target_span_id=right.span_id,
                    relation_type=RelationType.FOLLOWS,
                    weight=0.92,
                    metadata=_with_reason_metadata(
                        source_pass=self.name,
                        edge_family="next",
                        reason_codes=("adjacent_in_document_order",),
                    ),
                ),
            )
            edges_added += added

        # Contains edges: section-anchor span references member spans.
        for section_id, span_ids in ((node.section_id, node.span_ids) for node in out.section_tree.nodes):
            if len(span_ids) < 2:
                continue
            anchor_span_id = span_ids[0]
            for span_id in span_ids[1:]:
                out, added = _append_evidence_edge(
                    out,
                    EvidenceEdge(
                        source_span_id=anchor_span_id,
                        target_span_id=span_id,
                        relation_type=RelationType.REFERENCES,
                        weight=0.74,
                        metadata=_with_reason_metadata(
                            source_pass=self.name,
                            edge_family="contains",
                            reason_codes=("same_parent_section",),
                            metadata={"section_id": section_id},
                        ),
                    ),
                )
                edges_added += added

        # Parent-of edges from parent section anchor span to child section anchor span.
        section_anchor_by_id = {node.section_id: (node.span_ids[0] if node.span_ids else None) for node in out.section_tree.nodes}
        for node in out.section_tree.nodes:
            if not node.parent_section_id:
                continue
            source = section_anchor_by_id.get(node.parent_section_id)
            target = section_anchor_by_id.get(node.section_id)
            if not source or not target:
                continue
            out, added = _append_evidence_edge(
                out,
                EvidenceEdge(
                    source_span_id=source,
                    target_span_id=target,
                    relation_type=RelationType.REFERENCES,
                    weight=0.71,
                    metadata=_with_reason_metadata(
                        source_pass=self.name,
                        edge_family="parent_of",
                        reason_codes=("section_parent_child",),
                    ),
                ),
            )
            edges_added += added

        if context.config.create_same_section_edges:
            refreshed = GraphIndices.from_parse(out)
            for section_path, spans in refreshed.spans_by_section_path.items():
                for idx, left in enumerate(spans):
                    for right in spans[idx + 1 : idx + 1 + context.config.same_section_window]:
                        out, added = _append_evidence_edge(
                            out,
                            EvidenceEdge(
                                source_span_id=left.span_id,
                                target_span_id=right.span_id,
                                relation_type=RelationType.SAME_AS,
                                weight=0.76,
                                metadata=_with_reason_metadata(
                                    source_pass=self.name,
                                    edge_family="same_section",
                                    reason_codes=("same_parent_section",),
                                    metadata={"section_path": "/".join(section_path)},
                                ),
                            ),
                        )
                        edges_added += added
        return out, GraphPassStat(
            self.name,
            edges_added=edges_added,
            sections_touched=sections_touched,
            diagnostics=("emitted contains/next/parent_of/same_section edges",),
        )


class ThreadConversationPass:
    name = "ThreadConversationPass"

    def run(self, *, document_parse, context: PassContext, indices: GraphIndices, signals: GraphSignals):
        out = document_parse
        edges_added = 0

        # reply_to only with strong conversation signal
        if out.thread_graph is not None:
            nodes = tuple(out.thread_graph.message_nodes)
            for left, right in zip(nodes, nodes[1:]):
                explicit_reply = bool(right.metadata.get("in_reply_to") or right.metadata.get("references"))
                author_shift = bool(left.author_id and right.author_id and left.author_id != right.author_id)
                if not (explicit_reply or author_shift):
                    continue
                out, added = _append_thread_edge(
                    out,
                    ThreadEdge(
                        source_message_id=left.message_id,
                        target_message_id=right.message_id,
                        relation_type=RelationType.REPLIES_TO,
                        metadata=_with_reason_metadata(
                            source_pass=self.name,
                            edge_family="reply_to",
                            reason_codes=("explicit_reply_header", "message_order_adjacency") if explicit_reply else ("message_order_adjacency",),
                        ),
                    ),
                )
                edges_added += added

        # quote/forward and continuation/same speaker from message and actor groupings
        refreshed = GraphIndices.from_parse(out)
        for message_id, spans in refreshed.spans_by_message_id.items():
            authored = [span for span in spans if str(span.metadata.get("boundary_class", "")).lower() == "current_authored" and span.authority_score >= 0.74]
            quoted = [
                span
                for span in spans
                if str(span.metadata.get("boundary_class", "")).lower() == "quoted_context"
            ]
            forwarded = [
                span
                for span in spans
                if str(span.metadata.get("boundary_class", "")).lower() == "forwarded_context"
            ]
            if authored and context.config.create_quote_edges:
                anchor = authored[0]
                for quoted_span in quoted:
                    out, added = _append_evidence_edge(
                        out,
                        EvidenceEdge(
                            source_span_id=anchor.span_id,
                            target_span_id=quoted_span.span_id,
                            relation_type=RelationType.REFERENCES,
                            weight=0.45,
                            metadata=_with_reason_metadata(
                                source_pass=self.name,
                                edge_family="quotes",
                                reason_codes=("quoted_boundary_match",),
                                metadata={"message_id": message_id},
                            ),
                        ),
                    )
                    edges_added += added
                for forwarded_span in forwarded:
                    out, added = _append_evidence_edge(
                        out,
                        EvidenceEdge(
                            source_span_id=anchor.span_id,
                            target_span_id=forwarded_span.span_id,
                            relation_type=RelationType.REFERENCES,
                            weight=0.43,
                            metadata=_with_reason_metadata(
                                source_pass=self.name,
                                edge_family="forwards",
                                reason_codes=("forwarded_header_detected",),
                                metadata={"message_id": message_id},
                            ),
                        ),
                    )
                    edges_added += added

        refreshed = GraphIndices.from_parse(out)
        for actor_id, spans in refreshed.spans_by_actor_id.items():
            for left, right in zip(spans, spans[1:]):
                pair = signals.pair_signals(left.span_id, right.span_id)
                if signals.same_message(left, right):
                    out, added = _append_evidence_edge(
                        out,
                        EvidenceEdge(
                            source_span_id=left.span_id,
                            target_span_id=right.span_id,
                            relation_type=RelationType.FOLLOWS,
                            weight=0.78,
                            metadata=_with_reason_metadata(
                                source_pass=self.name,
                                edge_family="continuation_of_turn",
                                reason_codes=("same_normalized_speaker", "adjacent_in_document_order"),
                                metadata={"actor_id": actor_id},
                            ),
                        ),
                    )
                    edges_added += added
                if (pair.chronology_distance is not None and pair.chronology_distance > 3) and not pair.same_message:
                    continue
                out, added = _append_evidence_edge(
                    out,
                    EvidenceEdge(
                        source_span_id=left.span_id,
                        target_span_id=right.span_id,
                        relation_type=RelationType.SAME_AS,
                        weight=0.82,
                        metadata=_with_reason_metadata(
                            source_pass=self.name,
                            edge_family="same_speaker",
                            reason_codes=("same_normalized_speaker",),
                            metadata={"actor_id": actor_id},
                        ),
                    ),
                )
                edges_added += added
        return out, GraphPassStat(self.name, edges_added=edges_added, diagnostics=("emitted reply/quote/forward/conversation edges",))


class ChronologyPass:
    name = "ChronologyPass"

    def run(self, *, document_parse, context: PassContext, indices: GraphIndices, signals: GraphSignals):
        edges_added = 0
        anchors_inferred = 0
        spans = list(document_parse.evidence_spans)
        anchors = {anchor.time_anchor_id: anchor for anchor in document_parse.chronology_graph.time_anchors}
        anchor_seq = max([a.sequence_rank for a in anchors.values() if a.sequence_rank is not None], default=-1) + 1
        updates: dict[str, object] = {}
        for idx, span in enumerate(sorted(spans, key=lambda s: (s.chronology_rank if s.chronology_rank is not None else 10**9, s.span_id))):
            rank = span.chronology_rank if span.chronology_rank is not None else idx
            updated = span
            if span.chronology_rank is None:
                updated = replace(updated, chronology_rank=rank)
            if context.config.infer_missing_time_anchors and updated.time_anchor_id is None:
                anchor_id = f"time:{updated.span_id}"
                if anchor_id not in anchors:
                    anchors[anchor_id] = TimeAnchor(
                        time_anchor_id=anchor_id,
                        label=f"inferred:{updated.span_id}",
                        sequence_rank=anchor_seq,
                        is_inferred=True,
                        metadata={"source_pass": self.name, "reason_codes": ["turn_sequence_adjacency"]},
                    )
                    anchor_seq += 1
                    anchors_inferred += 1
                updated = replace(updated, time_anchor_id=anchor_id)
            updates[span.span_id] = updated
        spans = [updates.get(span.span_id, span) for span in spans]

        out = replace(
            document_parse,
            evidence_spans=tuple(spans),
            chronology_graph=ChronologyGraph(
                time_anchors=tuple(sorted(anchors.values(), key=lambda a: (a.sequence_rank if a.sequence_rank is not None else 10**9, a.time_anchor_id))),
                edges=document_parse.chronology_graph.edges,
                metadata=document_parse.chronology_graph.metadata,
            ),
        )
        refreshed = GraphIndices.from_parse(out)
        anchor_by_id = {anchor.time_anchor_id: anchor for anchor in out.chronology_graph.time_anchors}
        prev_anchor = None
        for span in refreshed.ordered_spans:
            if not span.time_anchor_id:
                continue
            if prev_anchor and prev_anchor != span.time_anchor_id:
                left_anchor = anchor_by_id.get(prev_anchor)
                right_anchor = anchor_by_id.get(span.time_anchor_id)
                both_inferred = bool(left_anchor and right_anchor and left_anchor.is_inferred and right_anchor.is_inferred)
                if both_inferred:
                    prev_anchor = span.time_anchor_id
                    continue
                out, added = _append_chrono_edge(
                    out,
                    ChronologyEdge(
                        source_time_anchor_id=prev_anchor,
                        target_time_anchor_id=span.time_anchor_id,
                        relation_type=RelationType.FOLLOWS,
                        confidence=0.82,
                        metadata=_with_reason_metadata(
                            source_pass=self.name,
                            edge_family="temporal_before",
                            reason_codes=("explicit_timestamp_order",),
                        ),
                    ),
                )
                edges_added += added
            prev_anchor = span.time_anchor_id

        # same_time and sequence_next on evidence edges
        refreshed = GraphIndices.from_parse(out)
        for anchor_id, anchor_spans in refreshed.spans_by_time_anchor_id.items():
            anchor = anchor_by_id.get(anchor_id)
            if anchor is not None and anchor.is_inferred:
                continue
            for left, right in zip(anchor_spans, anchor_spans[1:]):
                out, added = _append_evidence_edge(
                    out,
                    EvidenceEdge(
                        source_span_id=left.span_id,
                        target_span_id=right.span_id,
                        relation_type=RelationType.SAME_AS,
                        weight=0.8,
                        metadata=_with_reason_metadata(
                            source_pass=self.name,
                            edge_family="same_time",
                            reason_codes=("same_resolved_time_anchor",),
                            metadata={"time_anchor_id": anchor_id},
                        ),
                    ),
                )
                edges_added += added
        for left, right in zip(refreshed.ordered_spans, refreshed.ordered_spans[1:]):
            chronology = signals.chronology_signals(left.span_id, right.span_id)
            if chronology.temporal_order and chronology.chronology_near:
                out, added = _append_evidence_edge(
                    out,
                    EvidenceEdge(
                        source_span_id=left.span_id,
                        target_span_id=right.span_id,
                        relation_type=RelationType.FOLLOWS,
                        weight=0.79,
                        metadata=_with_reason_metadata(
                            source_pass=self.name,
                            edge_family="sequence_next",
                            reason_codes=("turn_sequence_adjacency",),
                        ),
                    ),
                )
                edges_added += added

        return out, GraphPassStat(
            self.name,
            edges_added=edges_added,
            anchors_inferred=anchors_inferred,
            diagnostics=("emitted temporal_before/same_time/sequence_next edges",),
        )


class AuthorityPass:
    name = "AuthorityPass"

    def run(self, *, document_parse, context: PassContext, indices: GraphIndices, signals: GraphSignals):
        out = document_parse
        edges_added = 0
        flags_added = 0

        for actor_id, spans in indices.spans_by_actor_id.items():
            if len(spans) < 2:
                continue
            for left, right in zip(spans, spans[1:]):
                pair = signals.pair_signals(left.span_id, right.span_id)
                authority = signals.authority_signals(left.span_id, right.span_id)
                if (pair.chronology_distance is not None and pair.chronology_distance > 3) and not pair.same_message:
                    continue
                authored_family = "spoken_by" if left.speaker_id == actor_id and right.speaker_id == actor_id else "authored_by"
                reason = "transcript_speaker_match" if authored_family == "spoken_by" else "message_sender_match"
                if authored_family == "authored_by" and not (left.author_id and right.author_id and left.author_id == right.author_id):
                    continue
                out, added = _append_evidence_edge(
                    out,
                    EvidenceEdge(
                        source_span_id=left.span_id,
                        target_span_id=right.span_id,
                        relation_type=RelationType.REFERENCES,
                        weight=0.77,
                        metadata=_with_reason_metadata(
                            source_pass=self.name,
                            edge_family=authored_family,
                            reason_codes=(reason,),
                            metadata={"actor_id": actor_id},
                        ),
                    ),
                )
                edges_added += added
                if left.authority_score < 0.72 or right.authority_score < 0.72 or not authority.compatible:
                    continue
                out, added = _append_evidence_edge(
                    out,
                    EvidenceEdge(
                        source_span_id=left.span_id,
                        target_span_id=right.span_id,
                        relation_type=RelationType.SAME_AS,
                        weight=0.82,
                        metadata=_with_reason_metadata(
                            source_pass=self.name,
                            edge_family="same_actor",
                            reason_codes=("same_normalized_speaker",),
                            metadata={"actor_id": actor_id},
                        ),
                    ),
                )
                edges_added += added

        for message_id, spans in indices.spans_by_message_id.items():
            authored = [span for span in spans if str(span.metadata.get("boundary_class", "")).lower() == "current_authored" and span.authority_score >= 0.74]
            quoted = [span for span in spans if str(span.metadata.get("boundary_class", "")).lower() == "quoted_context"]
            forwarded = [span for span in spans if str(span.metadata.get("boundary_class", "")).lower() == "forwarded_context"]
            if authored and quoted:
                for q in quoted:
                    out, added = _append_evidence_edge(
                        out,
                        EvidenceEdge(
                            source_span_id=authored[0].span_id,
                            target_span_id=q.span_id,
                            relation_type=RelationType.REFERENCES,
                            weight=0.52,
                            metadata=_with_reason_metadata(
                                source_pass=self.name,
                                edge_family="quoted_from",
                                reason_codes=("quoted_sender_match",),
                                metadata={"message_id": message_id},
                            ),
                        ),
                    )
                    edges_added += added
            if authored and forwarded:
                for fwd in forwarded:
                    out, added = _append_evidence_edge(
                        out,
                        EvidenceEdge(
                            source_span_id=authored[0].span_id,
                            target_span_id=fwd.span_id,
                            relation_type=RelationType.REFERENCES,
                            weight=0.5,
                            metadata=_with_reason_metadata(
                                source_pass=self.name,
                                edge_family="forwarded_from",
                                reason_codes=("forwarded_sender_match",),
                                metadata={"message_id": message_id},
                            ),
                        ),
                    )
                    edges_added += added
            if len(quoted) >= max(2, len(spans) // 2):
                out, added = _append_flag(
                    out,
                    flag_id=f"graph:{out.doc_id}:authority:quote_density:{message_id}",
                    severity=ReviewSeverity.INFO,
                    category=ReviewCategory.QUALITY,
                    message="Message contains high inherited-context density.",
                    span_id=quoted[0].span_id if quoted else None,
                    metadata={"source_pass": self.name, "reason_codes": ["quoted_boundary_match"], "message_id": message_id},
                )
                flags_added += added

        refreshed = GraphIndices.from_parse(out)
        for section_path, spans in refreshed.spans_by_section_path.items():
            actor_ids = sorted({aid for span in spans for aid in (span.speaker_id, span.author_id) if aid})
            for left_actor, right_actor in zip(actor_ids, actor_ids[1:]):
                out, _ = _append_actor_edge(
                    out,
                    ActorEdge(
                        source_actor_id=left_actor,
                        target_actor_id=right_actor,
                        relation_type=RelationType.SAME_AS,
                        weight=0.55,
                        evidence_span_ids=tuple(span.span_id for span in spans[:6]),
                        metadata=_with_reason_metadata(
                            source_pass=self.name,
                            edge_family="same_actor",
                            reason_codes=("same_section_context",),
                            metadata={"section_path": "/".join(section_path)},
                        ),
                    ),
                )
        return out, GraphPassStat(self.name, edges_added=edges_added, flags_added=flags_added, diagnostics=("emitted authority topology edges",))


class SemanticCuePass:
    name = "SemanticCuePass"

    def run(self, *, document_parse, context: PassContext, indices: GraphIndices, signals: GraphSignals):
        edges_added = 0
        metadata_updates = 0
        neural_scored_edges = 0
        spans = list(document_parse.evidence_spans)
        idx_map = {span.span_id: idx for idx, span in enumerate(spans)}
        cue_buckets: dict[str, list[str]] = defaultdict(list)
        for span in indices.ordered_spans:
            cue_values = tuple(signals.cue_values(span))
            updated = span
            if cue_values != normalized_cue_values(span.cue_kinds):
                updated = replace(span, cue_kinds=tuple(cue_values))
                spans[idx_map[span.span_id]] = updated
                metadata_updates += 1
            for cue in cue_values:
                cue_buckets[cue].append(span.span_id)
        out = replace(document_parse, evidence_spans=tuple(spans))

        refreshed = GraphIndices.from_parse(out)
        same_topic_hook = getattr(context.hooks, "same_topic_scorer", None) if context.hooks is not None else None
        same_topic_policy = context.config.scorer_policies.same_topic
        same_topic_scored_counts: dict[str, int] = defaultdict(int)
        same_topic_seen_pairs: set[tuple[str, str]] = set()
        for cue, span_ids in cue_buckets.items():
            for span_id in span_ids:
                neighbors = refreshed.span_neighbor_ids.get(span_id, ())
                if not neighbors:
                    continue
                out, added = _append_evidence_edge(
                    out,
                    EvidenceEdge(
                        source_span_id=neighbors[0],
                        target_span_id=span_id,
                        relation_type=RelationType.REFERENCES,
                        weight=0.72,
                        metadata=_with_reason_metadata(
                            source_pass=self.name,
                            edge_family="cue_attached_to_span",
                            reason_codes=("cue_tagger_attachment",),
                            metadata={"cue_family": cue},
                        ),
                    ),
                )
                edges_added += added
                if not context.config.create_same_topic_edges or same_topic_hook is None:
                    continue
                scored_count = 0
                anchor = refreshed.spans_by_id.get(span_id)
                if anchor is None:
                    continue
                accepted_for_fanout: list[tuple[object, object]] = []
                candidate_by_id: dict[str, tuple[object, list[str]]] = {}
                for neighbor_id in neighbors:
                    if scored_count >= context.config.max_scored_pairs_per_span:
                        break
                    if same_topic_scored_counts[anchor.span_id] >= context.config.max_scored_pairs_per_span:
                        break
                    candidate = refreshed.spans_by_id.get(neighbor_id)
                    if candidate is None:
                        continue
                    pair_key = (anchor.span_id, candidate.span_id)
                    if pair_key in same_topic_seen_pairs:
                        continue
                    pair = signals.pair_signals(anchor.span_id, candidate.span_id)
                    prefilter: list[str] = []
                    if pair.section_distance is not None and pair.section_distance <= 2:
                        prefilter.append("same_section_prefilter")
                    if pair.lexical_overlap >= max(0.06, context.config.same_topic_similarity_floor * 0.5):
                        prefilter.append("lexical_overlap_prefilter")
                    if pair.cue_similarity > 0.0:
                        prefilter.append("cue_family_compatible")
                    if not prefilter:
                        continue
                    result = same_topic_hook.score(
                        SameTopicRequest(
                            left_span_id=anchor.span_id,
                            right_span_id=candidate.span_id,
                            left_text=anchor.normalized_text,
                            right_text=candidate.normalized_text,
                            signals=pair,
                            metadata={"cue_family": cue},
                        )
                    )
                    scored_count += 1
                    same_topic_scored_counts[anchor.span_id] += 1
                    same_topic_seen_pairs.add(pair_key)
                    candidate_id = f"{anchor.span_id}->{candidate.span_id}"
                    decision, diagnostic = evaluate_score_result(
                        scorer_name="same_topic",
                        candidate_id=candidate_id,
                        result=result,
                        policy=same_topic_policy,
                        reason_codes=(*prefilter, "deterministic_prefilter_passed"),
                    )
                    context.add_scorer_diagnostic(diagnostic)
                    if not decision.accepted:
                        continue
                    accepted_for_fanout.append((decision, diagnostic))
                    candidate_by_id[candidate_id] = (candidate, prefilter)
                kept, trimmed = apply_fanout(accepted=accepted_for_fanout, policy=same_topic_policy)
                for _, trimmed_diag in trimmed:
                    context.add_scorer_diagnostic(trimmed_diag)
                for kept_decision, kept_diag in kept:
                    candidate_id = kept_diag.candidate_id
                    candidate_payload = candidate_by_id.get(candidate_id)
                    if candidate_payload is None:
                        continue
                    candidate, prefilter = candidate_payload
                    out, added = _append_evidence_edge(
                        out,
                        EvidenceEdge(
                            source_span_id=anchor.span_id,
                            target_span_id=candidate.span_id,
                            relation_type=RelationType.SAME_AS,
                            weight=max(0.0, min(1.0, float(kept_decision.score or 0.0))),
                            metadata=_with_reason_metadata(
                                source_pass=self.name,
                                edge_family="same_topic",
                                reason_codes=(*prefilter, "same_topic_neural_score", "within_fanout"),
                                metadata={
                                    "neural_score": round(float(kept_decision.score or 0.0), 6),
                                    "neural_model": kept_decision.model_name,
                                    "deterministic_prefilter_reason_codes": prefilter,
                                    "candidate_rank": kept_decision.candidate_rank,
                                },
                            ),
                        ),
                    )
                    edges_added += added
                    neural_scored_edges += added
        return out, GraphPassStat(
            self.name,
            edges_added=edges_added,
            metadata_updates=metadata_updates,
            diagnostics=(
                f"emitted cue attachment edges with neural same_topic enrichments={neural_scored_edges}",
            ),
        )


class PacketNeighborhoodPass:
    name = "PacketNeighborhoodPass"

    def run(self, *, document_parse, context: PassContext, indices: GraphIndices, signals: GraphSignals):
        out = document_parse
        metadata_updates = 0
        packet_seed_count = 0
        edges_added = 0
        packet_seed_hook = getattr(context.hooks, "packet_seed_scorer", None) if context.hooks is not None else None
        support_hook = getattr(context.hooks, "support_scorer", None) if context.hooks is not None else None
        packet_seed_policy = context.config.scorer_policies.packet_seed
        support_policy = context.config.scorer_policies.support
        neighbor_scores: dict[str, dict[str, float]] = defaultdict(lambda: {"support": 0.0, "same_section": 0.0, "same_actor": 0.0})
        for edge in out.evidence_graph.edges:
            family = str(edge.metadata.get("edge_family", ""))
            if family in {"supports", "context_for"}:
                neighbor_scores[edge.source_span_id]["support"] = max(neighbor_scores[edge.source_span_id]["support"], float(edge.weight))
                neighbor_scores[edge.target_span_id]["support"] = max(neighbor_scores[edge.target_span_id]["support"], float(edge.weight))
            elif family == "same_section":
                neighbor_scores[edge.source_span_id]["same_section"] = max(neighbor_scores[edge.source_span_id]["same_section"], float(edge.weight))
                neighbor_scores[edge.target_span_id]["same_section"] = max(neighbor_scores[edge.target_span_id]["same_section"], float(edge.weight))
            elif family in {"same_actor", "same_speaker"}:
                neighbor_scores[edge.source_span_id]["same_actor"] = max(neighbor_scores[edge.source_span_id]["same_actor"], float(edge.weight))
                neighbor_scores[edge.target_span_id]["same_actor"] = max(neighbor_scores[edge.target_span_id]["same_actor"], float(edge.weight))

        spans = list(out.evidence_spans)
        span_index = {span.span_id: idx for idx, span in enumerate(spans)}
        seed_span_ids: list[str] = []
        for span in indices.ordered_spans:
            current = spans[span_index[span.span_id]]
            families = packet_families_for_span(current)
            if not families:
                continue
            support = max(neighbor_scores[current.span_id]["support"], neighbor_scores[current.span_id]["same_actor"] * 0.5)
            same_topic = neighbor_scores[current.span_id]["same_section"]
            seed_score = packet_seed_score(current, neighborhood_support=support, neighborhood_same_topic=same_topic, hook=None)
            seed_neural_metadata: dict[str, object] = {}
            if packet_seed_hook is not None:
                seed_request = PacketSeedRequest(
                    span_id=current.span_id,
                    text=current.normalized_text,
                    family_hints=families,
                    authority_class=current.authority_class.value,
                    authority_score=float(current.authority_score),
                    local_support_density=float(support),
                    cue_strength=min(1.0, len(normalized_cue_values(current.cue_kinds)) * 0.2),
                    signals={
                        "support_score": float(support),
                        "same_section_score": float(same_topic),
                    },
                )
                seed_result = packet_seed_hook.score(seed_request)
                candidate_id = f"seed:{current.span_id}"
                decision, diagnostic = evaluate_score_result(
                    scorer_name="packet_seed",
                    candidate_id=candidate_id,
                    result=seed_result,
                    policy=packet_seed_policy,
                    reason_codes=("packet_seed_family_match", "deterministic_prefilter_passed"),
                )
                context.add_scorer_diagnostic(diagnostic)
                if decision.accepted:
                    seed_score = max(0.0, min(1.0, (seed_score * 0.65) + (float(decision.score or 0.0) * 0.35)))
                    seed_neural_metadata = {
                        "neural_score": round(float(decision.score or 0.0), 6),
                        "neural_model": decision.model_name,
                        "deterministic_prefilter_reason_codes": ["packet_seed_family_match"],
                    }
            metadata = dict(current.metadata)
            metadata["packet_seed_score"] = round(seed_score, 6)
            metadata["packet_families"] = list(families[: context.config.max_packet_families_per_span])
            if seed_neural_metadata:
                metadata["packet_seed_neural"] = dict(seed_neural_metadata)
            spans[span_index[current.span_id]] = replace(current, metadata=metadata)
            metadata_updates += 1
            if seed_score < context.config.packet_seed_floor:
                continue
            seed_span_ids.append(current.span_id)
            for family in families[: context.config.max_packet_families_per_span]:
                context.add_packet_seed(
                    PacketSeedHint(
                        span_id=current.span_id,
                        packet_family=family,
                        score=round(seed_score, 6),
                        cue_kinds=tuple(normalized_cue_values(current.cue_kinds)),
                        section_path=tuple(current.section_path),
                        actor_ids=tuple(actor_id for actor_id in (current.speaker_id, current.author_id) if actor_id),
                        message_ids=(current.message_id,) if current.message_id else (),
                        time_anchor_ids=(current.time_anchor_id,) if current.time_anchor_id else (),
                        metadata={
                            "source_pass": self.name,
                            "reason_codes": ["packet_seed_family_match"] + (["packet_seed_neural_score"] if seed_neural_metadata else []),
                            "support_score": round(support, 4),
                            "same_section_score": round(same_topic, 4),
                            **seed_neural_metadata,
                        },
                    )
                )
                packet_seed_count += 1

        out = replace(out, evidence_spans=tuple(spans))
        refreshed = GraphIndices.from_parse(out)
        for seed_span_id in seed_span_ids:
            neighbors = tuple(refreshed.span_neighbor_ids.get(seed_span_id, ()))
            for neighbor_id in neighbors:
                out, added = _append_evidence_edge(
                    out,
                    EvidenceEdge(
                        source_span_id=seed_span_id,
                        target_span_id=neighbor_id,
                        relation_type=RelationType.REFERENCES,
                        weight=0.68,
                        metadata=_with_reason_metadata(
                            source_pass=self.name,
                            edge_family="anchors",
                            reason_codes=("packet_seed_family_match", "adjacent_in_document_order"),
                        ),
                    ),
                )
                edges_added += added

            kept_support: dict[str, tuple[float, str | None, list[str], int | None]] = {}
            if support_hook is not None:
                accepted_support_rows: list[tuple[object, object]] = []
                support_candidate_prefilters: dict[str, list[str]] = {}
                scored_attempts = 0
                for neighbor_id in neighbors:
                    if scored_attempts >= context.config.max_scored_support_per_anchor:
                        break
                    left = refreshed.spans_by_id.get(seed_span_id)
                    right = refreshed.spans_by_id.get(neighbor_id)
                    if left is None or right is None:
                        continue
                    pair = signals.pair_signals(left.span_id, right.span_id)
                    prefilter: list[str] = []
                    if pair.section_distance is not None and pair.section_distance <= 2:
                        prefilter.append("support_prefilter")
                    if pair.lexical_overlap >= max(0.06, context.config.support_similarity_floor * 0.5):
                        prefilter.append("lexical_overlap_prefilter")
                    if pair.same_actor or pair.cue_similarity > 0.0:
                        prefilter.append("cue_family_compatible")
                    if not prefilter:
                        continue
                    scored_attempts += 1
                    support_result = support_hook.score(
                        SupportRequest(
                            anchor_span_id=left.span_id,
                            candidate_span_id=right.span_id,
                            anchor_text=left.normalized_text,
                            candidate_text=right.normalized_text,
                            signals=pair,
                            metadata={"edge_family": "context_for"},
                        )
                    )
                    candidate_id = f"{left.span_id}->{right.span_id}"
                    decision, diagnostic = evaluate_score_result(
                        scorer_name="support",
                        candidate_id=candidate_id,
                        result=support_result,
                        policy=support_policy,
                        reason_codes=(*prefilter, "deterministic_prefilter_passed"),
                    )
                    context.add_scorer_diagnostic(diagnostic)
                    if not decision.accepted:
                        continue
                    accepted_support_rows.append((decision, diagnostic))
                    support_candidate_prefilters[candidate_id] = prefilter

                kept, trimmed = apply_fanout(accepted=accepted_support_rows, policy=support_policy)
                for _, trimmed_diag in trimmed:
                    context.add_scorer_diagnostic(trimmed_diag)
                for kept_decision, kept_diag in kept:
                    kept_support[kept_diag.candidate_id] = (
                        float(kept_decision.score or 0.0),
                        kept_decision.model_name,
                        support_candidate_prefilters.get(kept_diag.candidate_id, []),
                        kept_decision.candidate_rank,
                    )

            for neighbor_id in neighbors:
                context_weight = 0.61
                context_reason_codes: list[str] = ["same_section_context"]
                context_metadata: dict[str, object] = {}
                candidate_id = f"{seed_span_id}->{neighbor_id}"
                kept_item = kept_support.get(candidate_id)
                if kept_item is not None:
                    score, model_name, prefilter, rank = kept_item
                    context_weight = max(context_weight, min(1.0, score))
                    context_reason_codes = [*prefilter, "support_neural_score", "within_fanout"]
                    context_metadata = {
                        "neural_score": round(score, 6),
                        "neural_model": model_name,
                        "deterministic_prefilter_reason_codes": prefilter,
                        "candidate_rank": rank,
                    }
                out, added = _append_evidence_edge(
                    out,
                    EvidenceEdge(
                        source_span_id=neighbor_id,
                        target_span_id=seed_span_id,
                        relation_type=RelationType.REFERENCES,
                        weight=context_weight,
                        metadata=_with_reason_metadata(
                            source_pass=self.name,
                            edge_family="context_for",
                            reason_codes=context_reason_codes,
                            metadata=context_metadata,
                        ),
                    ),
                )
                edges_added += added
        return out, GraphPassStat(
            self.name,
            edges_added=edges_added,
            packet_seeds_created=packet_seed_count,
            metadata_updates=metadata_updates,
            diagnostics=(f"produced {packet_seed_count} packet seeds and neighborhood edges",),
        )
