from __future__ import annotations

from collections import defaultdict
from dataclasses import replace

from orbitbrief_core.parser.graph.base import GraphContext, GraphPassStat, PacketSeedHint
from orbitbrief_core.parser.graph.indices import GraphIndices
from orbitbrief_core.parser.graph.signals import (
    contradiction_score,
    cue_kinds_for_textish,
    derive_span_cues,
    lexical_similarity,
    normalized_cue_values,
    packet_families_for_span,
    packet_seed_score,
    section_affinity,
    span_noise_hint,
    span_position_distance,
    support_score,
)
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
    SectionNode,
    SectionTree,
    TimeAnchor,
    ThreadEdge,
    ThreadGraph,
)


def _append_flag(document_parse, flag_id: str, severity: ReviewSeverity, category: ReviewCategory, message: str, *, span_id: str | None = None, metadata: dict | None = None):
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
    sig = (edge.source_span_id, edge.target_span_id, edge.relation_type.value, str(edge.metadata.get("edge_family", "")))
    for existing in edges:
        cur = (
            existing.source_span_id,
            existing.target_span_id,
            existing.relation_type.value,
            str(existing.metadata.get("edge_family", "")),
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
    sig = (edge.source_actor_id, edge.target_actor_id, edge.relation_type.value, str(edge.metadata.get("edge_family", "")))
    for existing in edges:
        cur = (
            existing.source_actor_id,
            existing.target_actor_id,
            existing.relation_type.value,
            str(existing.metadata.get("edge_family", "")),
        )
        if cur == sig:
            return document_parse, 0
    edges.append(edge)
    return replace(document_parse, actor_graph=ActorGraph(nodes=document_parse.actor_graph.nodes, edges=tuple(edges), primary_actor_id=document_parse.actor_graph.primary_actor_id, metadata=document_parse.actor_graph.metadata)), 1


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
    name = "structural"

    def run(self, *, document_parse, context: GraphContext, indices: GraphIndices):
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
        for left, right in zip(indices.ordered_spans, indices.ordered_spans[1:]):
            out, added = _append_evidence_edge(
                out,
                EvidenceEdge(
                    source_span_id=left.span_id,
                    target_span_id=right.span_id,
                    relation_type=RelationType.FOLLOWS,
                    weight=0.92,
                    metadata={"edge_family": "next", "graph_pass": self.name},
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
                                metadata={"edge_family": "same_section", "graph_pass": self.name, "section_path": "/".join(section_path)},
                            ),
                        )
                        edges_added += added
        return out, GraphPassStat(self.name, edges_added=edges_added, sections_touched=sections_touched, diagnostics=("linked section membership and sequential edges",))


class ChronologyPass:
    name = "chronology"

    def run(self, *, document_parse, context: GraphContext, indices: GraphIndices):
        edges_added = 0
        anchors_inferred = 0
        spans = list(document_parse.evidence_spans)
        anchors = {anchor.time_anchor_id: anchor for anchor in document_parse.chronology_graph.time_anchors}
        anchor_seq = max([a.sequence_rank for a in anchors.values() if a.sequence_rank is not None], default=-1) + 1
        for idx, span in enumerate(sorted(spans, key=lambda s: (s.chronology_rank if s.chronology_rank is not None else 10**9, s.span_id))):
            rank = span.chronology_rank if span.chronology_rank is not None else idx
            updated = span
            if span.chronology_rank is None:
                updated = replace(updated, chronology_rank=rank)
            if context.config.infer_missing_time_anchors and updated.time_anchor_id is None:
                # deterministic synthetic anchor
                anchor_id = f"time:{updated.span_id}"
                if anchor_id not in anchors:
                    anchors[anchor_id] = TimeAnchor(
                        time_anchor_id=anchor_id,
                        label=f"inferred:{updated.span_id}",
                        sequence_rank=anchor_seq,
                        is_inferred=True,
                        metadata={"graph_pass": self.name},
                    )
                    anchor_seq += 1
                    anchors_inferred += 1
                updated = replace(updated, time_anchor_id=anchor_id)
            if updated is not span:
                spans[spans.index(span)] = updated
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
        prev_anchor = None
        for span in refreshed.ordered_spans:
            if not span.time_anchor_id:
                continue
            if prev_anchor and prev_anchor != span.time_anchor_id:
                out, added = _append_chrono_edge(
                    out,
                    ChronologyEdge(
                        source_time_anchor_id=prev_anchor,
                        target_time_anchor_id=span.time_anchor_id,
                        relation_type=RelationType.FOLLOWS,
                        confidence=0.81,
                        metadata={"edge_family": "temporal_before", "graph_pass": self.name},
                    ),
                )
                edges_added += added
            prev_anchor = span.time_anchor_id
        return out, GraphPassStat(self.name, edges_added=edges_added, anchors_inferred=anchors_inferred, diagnostics=("inferred chronology ranks/anchors",))


class AuthorityTopologyPass:
    name = "authority_topology"

    def run(self, *, document_parse, context: GraphContext, indices: GraphIndices):
        edges_added = 0
        flags_added = 0
        out = document_parse
        if context.config.create_same_actor_edges:
            for actor_id, spans in indices.spans_by_actor_id.items():
                for left, right in zip(spans, spans[1:]):
                    out, added = _append_evidence_edge(
                        out,
                        EvidenceEdge(
                            source_span_id=left.span_id,
                            target_span_id=right.span_id,
                            relation_type=RelationType.SAME_AS,
                            weight=0.84,
                            metadata={"edge_family": "same_actor", "graph_pass": self.name, "actor_id": actor_id},
                        ),
                    )
                    edges_added += added
        for message_id, spans in indices.spans_by_message_id.items():
            authored = [span for span in spans if str(span.metadata.get("thread_zone", "")) == "current_message" or span.authority_score >= 0.75]
            quoted = [span for span in spans if span_noise_hint(span)]
            if authored and quoted and context.config.create_quote_edges:
                anchor = authored[0]
                for q in quoted:
                    out, added = _append_evidence_edge(
                        out,
                        EvidenceEdge(
                            source_span_id=anchor.span_id,
                            target_span_id=q.span_id,
                            relation_type=RelationType.REFERENCES,
                            weight=0.44,
                            metadata={"edge_family": "quotes", "graph_pass": self.name, "message_id": message_id},
                        ),
                    )
                    edges_added += added
            if len(quoted) >= max(2, len(spans) // 2):
                out, added = _append_flag(
                    out,
                    flag_id=f"graph:{out.doc_id}:quote_density:{message_id}",
                    severity=ReviewSeverity.INFO,
                    category=ReviewCategory.QUALITY,
                    message="Message contains high density of inherited/low-authority context.",
                    span_id=quoted[0].span_id,
                    metadata={"graph_pass": self.name, "message_id": message_id},
                )
                flags_added += added
        # actor graph affinity by section
        refreshed = GraphIndices.from_parse(out)
        for section_path, spans in refreshed.spans_by_section_path.items():
            actor_ids = sorted({aid for span in spans for aid in (span.speaker_id, span.author_id) if aid})
            for left, right in zip(actor_ids, actor_ids[1:]):
                out, _ = _append_actor_edge(
                    out,
                    ActorEdge(
                        source_actor_id=left,
                        target_actor_id=right,
                        relation_type=RelationType.SAME_AS,
                        weight=0.51,
                        evidence_span_ids=tuple(span.span_id for span in spans[:6]),
                        metadata={"edge_family": "same_topic", "graph_pass": self.name, "section_path": "/".join(section_path)},
                    ),
                )
        return out, GraphPassStat(self.name, edges_added=edges_added, flags_added=flags_added, diagnostics=("reinforced actor and quote topology",))


class DiscourseAffinityPass:
    name = "discourse_affinity"

    def run(self, *, document_parse, context: GraphContext, indices: GraphIndices):
        edges_added = 0
        flags_added = 0
        out = document_parse
        hook_topic = getattr(context.hooks, "same_topic_scorer", None) if context.hooks is not None else None
        hook_support = getattr(context.hooks, "support_scorer", None) if context.hooks is not None else None
        hook_contradiction = getattr(context.hooks, "contradiction_scorer", None) if context.hooks is not None else None
        spans = indices.ordered_spans
        for index, left in enumerate(spans):
            for right in spans[index + 1 : index + 1 + context.config.discourse_window]:
                if span_position_distance(left, right) > context.config.discourse_window * 4 and tuple(left.section_path) != tuple(right.section_path):
                    continue
                lexical = lexical_similarity(left, right)
                section = section_affinity(left, right)
                support = support_score(left, right)
                contradiction = contradiction_score(left, right)
                topic_score = (lexical * 0.56) + (section * 0.22) + (support * 0.22)
                if hook_topic is not None:
                    maybe = hook_topic(left=left, right=right, features={"lexical": lexical, "section_affinity": section, "support_score": support})
                    if maybe is not None:
                        topic_score = (topic_score * 0.68) + (float(maybe) * 0.32)
                if context.config.create_same_topic_edges and topic_score >= context.config.same_topic_similarity_floor:
                    out, added = _append_evidence_edge(
                        out,
                        EvidenceEdge(
                            source_span_id=left.span_id,
                            target_span_id=right.span_id,
                            relation_type=RelationType.SAME_AS,
                            weight=max(topic_score, 0.01),
                            metadata={"edge_family": "same_topic", "graph_pass": self.name, "lexical": round(lexical, 4)},
                        ),
                    )
                    edges_added += added
                support_value = support
                if hook_support is not None:
                    maybe = hook_support(left=left, right=right, features={"lexical": lexical, "support_score": support})
                    if maybe is not None:
                        support_value = (support_value * 0.7) + (float(maybe) * 0.3)
                if context.config.create_support_edges and support_value >= context.config.support_similarity_floor:
                    out, added = _append_evidence_edge(
                        out,
                        EvidenceEdge(
                            source_span_id=left.span_id,
                            target_span_id=right.span_id,
                            relation_type=RelationType.SUPPORTS,
                            weight=max(support_value, 0.01),
                            metadata={"edge_family": "supports", "graph_pass": self.name, "support_score": round(support_value, 4)},
                        ),
                    )
                    edges_added += added
                contradiction_value = contradiction
                if hook_contradiction is not None:
                    maybe = hook_contradiction(left=left, right=right, features={"contradiction_score": contradiction, "lexical": lexical})
                    if maybe is not None:
                        contradiction_value = (contradiction_value * 0.72) + (float(maybe) * 0.28)
                if contradiction_value >= context.config.contradiction_review_floor:
                    out, added = _append_flag(
                        out,
                        flag_id=f"graph:{out.doc_id}:contradiction:{left.span_id}:{right.span_id}",
                        severity=ReviewSeverity.WARNING,
                        category=ReviewCategory.AMBIGUITY,
                        message="Potential contradiction detected between nearby evidence spans.",
                        span_id=right.span_id,
                        metadata={"graph_pass": self.name, "left_span_id": left.span_id, "right_span_id": right.span_id},
                    )
                    flags_added += added
        return out, GraphPassStat(self.name, edges_added=edges_added, flags_added=flags_added, diagnostics=("added affinity/support topology and contradiction reviews",))


class SemanticCuePass:
    name = "semantic_cues"

    def run(self, *, document_parse, context: GraphContext, indices: GraphIndices):
        edges_added = 0
        metadata_updates = 0
        spans = list(document_parse.evidence_spans)
        clusters: dict[tuple[tuple[str, ...], str], list[str]] = defaultdict(list)
        span_index = {span.span_id: idx for idx, span in enumerate(spans)}
        for span in indices.ordered_spans:
            current = spans[span_index[span.span_id]]
            cue_values = normalized_cue_values(current.cue_kinds) or normalized_cue_values(cue_kinds_for_textish(current.normalized_text))
            if cue_values != normalized_cue_values(current.cue_kinds):
                spans[span_index[current.span_id]] = replace(current, cue_kinds=tuple(cue_values))
                current = spans[span_index[current.span_id]]
                metadata_updates += 1
            for cue in cue_values:
                clusters[(tuple(current.section_path), cue)].append(current.span_id)
        out = replace(document_parse, evidence_spans=tuple(spans))
        cluster_count = 0
        for (section_path, cue), span_ids in clusters.items():
            if len(span_ids) < 2:
                continue
            cluster_count += 1
            cluster_id = f"cue_cluster:{cue}:{cluster_count:04d}"
            span_map = {span.span_id: span for span in out.evidence_spans}
            updated_spans = list(out.evidence_spans)
            updated_idx = {span.span_id: idx for idx, span in enumerate(updated_spans)}
            for span_id in span_ids:
                span_obj = span_map[span_id]
                metadata = dict(span_obj.metadata)
                cue_clusters = list(metadata.get("cue_clusters", []))
                if cluster_id not in cue_clusters:
                    cue_clusters.append(cluster_id)
                    metadata["cue_clusters"] = cue_clusters
                    metadata["dominant_cue"] = cue
                    updated_spans[updated_idx[span_id]] = replace(span_obj, metadata=metadata)
                    metadata_updates += 1
            out = replace(out, evidence_spans=tuple(updated_spans))
            for left_id, right_id in zip(span_ids, span_ids[1:]):
                out, added = _append_evidence_edge(
                    out,
                    EvidenceEdge(
                        source_span_id=left_id,
                        target_span_id=right_id,
                        relation_type=RelationType.SUPPORTS,
                        weight=0.79,
                        metadata={"edge_family": "cue_cluster", "graph_pass": self.name, "cue_cluster_id": cluster_id, "cue": cue, "section_path": "/".join(section_path)},
                    ),
                )
                edges_added += added
        return out, GraphPassStat(self.name, edges_added=edges_added, metadata_updates=metadata_updates, diagnostics=(f"formed {cluster_count} multi-span cue clusters",))


class PacketSeedPass:
    name = "packet_seed"

    def run(self, *, document_parse, context: GraphContext, indices: GraphIndices):
        metadata_updates = 0
        packet_seed_count = 0
        hook = getattr(context.hooks, "packet_seed_scorer", None) if context.hooks is not None else None
        graph_neighbors: dict[str, dict[str, float]] = defaultdict(lambda: {"supports": 0.0, "same_topic": 0.0})
        for edge in document_parse.evidence_graph.edges:
            family = str(edge.metadata.get("edge_family", ""))
            if family == "supports":
                graph_neighbors[edge.source_span_id]["supports"] = max(graph_neighbors[edge.source_span_id]["supports"], float(edge.weight))
                graph_neighbors[edge.target_span_id]["supports"] = max(graph_neighbors[edge.target_span_id]["supports"], float(edge.weight))
            elif family == "same_topic":
                graph_neighbors[edge.source_span_id]["same_topic"] = max(graph_neighbors[edge.source_span_id]["same_topic"], float(edge.weight))
                graph_neighbors[edge.target_span_id]["same_topic"] = max(graph_neighbors[edge.target_span_id]["same_topic"], float(edge.weight))

        spans = list(document_parse.evidence_spans)
        idx = {span.span_id: i for i, span in enumerate(spans)}
        for span in indices.ordered_spans:
            current = spans[idx[span.span_id]]
            families = packet_families_for_span(current)
            if not families:
                continue
            seed_score = packet_seed_score(
                current,
                neighborhood_support=graph_neighbors[current.span_id]["supports"],
                neighborhood_same_topic=graph_neighbors[current.span_id]["same_topic"],
                hook=hook,
            )
            metadata = dict(current.metadata)
            metadata["packet_seed_score"] = round(seed_score, 6)
            metadata["packet_families"] = list(families[: context.config.max_packet_families_per_span])
            spans[idx[current.span_id]] = replace(current, metadata=metadata)
            metadata_updates += 1
            if seed_score >= context.config.packet_seed_floor:
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
                                "graph_pass": self.name,
                                "authority_class": getattr(current.authority_class, "value", str(current.authority_class)),
                                "support_score": round(graph_neighbors[current.span_id]["supports"], 4),
                                "same_topic_score": round(graph_neighbors[current.span_id]["same_topic"], 4),
                            },
                        )
                    )
                    packet_seed_count += 1
        out = replace(document_parse, evidence_spans=tuple(spans))
        return out, GraphPassStat(self.name, packet_seeds_created=packet_seed_count, metadata_updates=metadata_updates, diagnostics=(f"produced {packet_seed_count} packet seed hints",))
