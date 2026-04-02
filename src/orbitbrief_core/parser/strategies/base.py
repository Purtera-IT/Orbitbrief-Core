from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Protocol

from orbitbrief_core.parser.router import ParsePlan
from orbitbrief_core.parser.shared.types import (
    ChronologyEdge,
    ChronologyGraph,
    DocumentParse,
    EvidenceEdge,
    EvidenceGraph,
    RelationType,
    ReviewCategory,
    ReviewFlag,
    ReviewSeverity,
    ThreadEdge,
    ThreadGraph,
)


class StrategyError(ValueError):
    """Raised when strategy enrichment cannot be applied safely."""


@dataclass(frozen=True, slots=True)
class StrategyContext:
    parse_plan: ParsePlan
    compiled_pack: Any
    metadata: Mapping[str, Any] | None = None


class BaseStrategy(Protocol):
    name: str

    def apply(
        self,
        *,
        document_parse: DocumentParse,
        parse_plan: ParsePlan,
        compiled_pack: Any,
    ) -> DocumentParse:
        ...


def _with_diag(document_parse: DocumentParse, entry: str) -> DocumentParse:
    metadata = dict(document_parse.metadata)
    diagnostics = list(metadata.get("strategy_diagnostics", []))
    diagnostics.append(entry)
    metadata["strategy_diagnostics"] = diagnostics
    return replace(document_parse, metadata=metadata)


def mark_strategy_applied(document_parse: DocumentParse, strategy_name: str) -> DocumentParse:
    metadata = dict(document_parse.metadata)
    trace = list(metadata.get("strategy_trace", []))
    if strategy_name not in trace:
        trace.append(strategy_name)
    metadata["strategy_trace"] = trace
    return replace(document_parse, metadata=metadata)


def add_review_flag(
    document_parse: DocumentParse,
    *,
    flag_id: str,
    severity: ReviewSeverity,
    category: ReviewCategory,
    message: str,
    span_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> DocumentParse:
    existing = list(document_parse.review_flags)
    if any(flag.flag_id == flag_id for flag in existing):
        return document_parse
    existing.append(
        ReviewFlag(
            flag_id=flag_id,
            severity=severity,
            category=category,
            message=message,
            span_id=span_id,
            metadata=dict(metadata or {}),
        )
    )
    return replace(document_parse, review_flags=tuple(existing))


def append_evidence_edge(
    document_parse: DocumentParse,
    *,
    source_span_id: str,
    target_span_id: str,
    relation_type: RelationType,
    edge_family: str,
    weight: float = 1.0,
    metadata: Mapping[str, Any] | None = None,
) -> DocumentParse:
    edges = list(document_parse.evidence_graph.edges)
    signature = (source_span_id, target_span_id, relation_type.value, edge_family)
    for edge in edges:
        existing = (
            edge.source_span_id,
            edge.target_span_id,
            edge.relation_type.value,
            str(edge.metadata.get("edge_family", "")),
        )
        if existing == signature:
            return document_parse
    merged_meta = dict(metadata or {})
    merged_meta["edge_family"] = edge_family
    edges.append(
        EvidenceEdge(
            source_span_id=source_span_id,
            target_span_id=target_span_id,
            relation_type=relation_type,
            weight=weight,
            metadata=merged_meta,
        )
    )
    return replace(document_parse, evidence_graph=EvidenceGraph(edges=tuple(edges), metadata=document_parse.evidence_graph.metadata))


def append_thread_edge(
    document_parse: DocumentParse,
    *,
    source_message_id: str,
    target_message_id: str,
    relation_type: RelationType = RelationType.REPLIES_TO,
    edge_family: str = "reply_to",
) -> DocumentParse:
    thread_graph = document_parse.thread_graph
    if thread_graph is None:
        return document_parse
    edges = list(thread_graph.edges)
    signature = (source_message_id, target_message_id, relation_type.value, edge_family)
    for edge in edges:
        existing = (
            edge.source_message_id,
            edge.target_message_id,
            edge.relation_type.value,
            str(edge.metadata.get("edge_family", "")),
        )
        if existing == signature:
            return document_parse
    edges.append(
        ThreadEdge(
            source_message_id=source_message_id,
            target_message_id=target_message_id,
            relation_type=relation_type,
            metadata={"edge_family": edge_family},
        )
    )
    return replace(
        document_parse,
        thread_graph=ThreadGraph(
            thread_id=thread_graph.thread_id,
            message_nodes=thread_graph.message_nodes,
            edges=tuple(edges),
            metadata=thread_graph.metadata,
        ),
    )


def append_chronology_edge(
    document_parse: DocumentParse,
    *,
    source_time_anchor_id: str,
    target_time_anchor_id: str,
    relation_type: RelationType = RelationType.FOLLOWS,
    edge_family: str = "temporal_before",
    confidence: float = 0.8,
) -> DocumentParse:
    chronology = document_parse.chronology_graph
    edges = list(chronology.edges)
    signature = (source_time_anchor_id, target_time_anchor_id, relation_type.value, edge_family)
    for edge in edges:
        existing = (
            edge.source_time_anchor_id,
            edge.target_time_anchor_id,
            edge.relation_type.value,
            str(edge.metadata.get("edge_family", "")),
        )
        if existing == signature:
            return document_parse
    if source_time_anchor_id == target_time_anchor_id:
        return document_parse
    edges.append(
        ChronologyEdge(
            source_time_anchor_id=source_time_anchor_id,
            target_time_anchor_id=target_time_anchor_id,
            relation_type=relation_type,
            confidence=max(0.0, min(1.0, confidence)),
            metadata={"edge_family": edge_family},
        )
    )
    return replace(
        document_parse,
        chronology_graph=ChronologyGraph(
            time_anchors=chronology.time_anchors,
            edges=tuple(edges),
            metadata=chronology.metadata,
        ),
    )


def with_strategy_diag(document_parse: DocumentParse, strategy_name: str, message: str) -> DocumentParse:
    return mark_strategy_applied(_with_diag(document_parse, f"{strategy_name}:{message}"), strategy_name)
