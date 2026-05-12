from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from orbitbrief_core.parser.router import ParsePlan
from orbitbrief_core.parser.graph.scorers.config import GraphScorerPolicies
from orbitbrief_core.parser.shared.types import DocumentParse


@dataclass(frozen=True, slots=True)
class PacketSeedHint:
    span_id: str
    packet_family: str
    score: float
    cue_kinds: tuple[str, ...] = ()
    section_path: tuple[str, ...] = ()
    actor_ids: tuple[str, ...] = ()
    message_ids: tuple[str, ...] = ()
    time_anchor_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "packet_family": self.packet_family,
            "score": self.score,
            "cue_kinds": list(self.cue_kinds),
            "section_path": list(self.section_path),
            "actor_ids": list(self.actor_ids),
            "message_ids": list(self.message_ids),
            "time_anchor_ids": list(self.time_anchor_ids),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class GraphPassStat:
    pass_name: str
    edges_added: int = 0
    flags_added: int = 0
    sections_touched: int = 0
    anchors_inferred: int = 0
    packet_seeds_created: int = 0
    metadata_updates: int = 0
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "pass_name": self.pass_name,
            "edges_added": self.edges_added,
            "flags_added": self.flags_added,
            "sections_touched": self.sections_touched,
            "anchors_inferred": self.anchors_inferred,
            "packet_seeds_created": self.packet_seeds_created,
            "metadata_updates": self.metadata_updates,
            "diagnostics": list(self.diagnostics),
        }


@dataclass(frozen=True, slots=True)
class GraphBuildConfig:
    same_section_window: int = 4
    discourse_window: int = 5
    support_similarity_floor: float = 0.18
    same_topic_similarity_floor: float = 0.12
    contradiction_review_floor: float = 0.72
    packet_seed_floor: float = 0.54
    max_packet_families_per_span: int = 4
    infer_missing_time_anchors: bool = True
    create_support_edges: bool = True
    create_same_topic_edges: bool = True
    create_same_section_edges: bool = True
    create_same_actor_edges: bool = True
    create_quote_edges: bool = True
    same_topic_neural_threshold: float = 0.72
    support_neural_threshold: float = 0.75
    packet_seed_neural_threshold: float = 0.70
    max_scored_pairs_per_span: int = 5
    max_scored_support_per_anchor: int = 6
    scorer_policies: GraphScorerPolicies = field(default_factory=GraphScorerPolicies)
    strict_mode: bool = True


@dataclass(frozen=True, slots=True)
class ScoreResult:
    score: float | None
    model_name: str | None = None
    abstained: bool = False
    raw_metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ScoreDecision:
    accepted: bool
    score: float | None
    threshold: float
    reason_codes: tuple[str, ...]
    model_name: str | None
    candidate_rank: int | None
    fanout_limited: bool
    abstained: bool


@dataclass(frozen=True, slots=True)
class ScorerDiagnostic:
    scorer_name: str
    candidate_id: str
    accepted: bool
    score: float | None
    threshold: float
    reason_codes: tuple[str, ...]
    abstained: bool
    fanout_limited: bool
    model_name: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scorer_name": self.scorer_name,
            "candidate_id": self.candidate_id,
            "accepted": self.accepted,
            "score": self.score,
            "threshold": self.threshold,
            "reason_codes": list(self.reason_codes),
            "abstained": self.abstained,
            "fanout_limited": self.fanout_limited,
            "model_name": self.model_name,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class PassContext:
    parse_plan: ParsePlan
    compiled_pack: Any
    config: GraphBuildConfig
    hooks: Any | None = None
    diagnostics: list[str] = field(default_factory=list)
    packet_seed_hints: list[PacketSeedHint] = field(default_factory=list)
    pass_stats: list[GraphPassStat] = field(default_factory=list)
    scorer_diagnostics: list[ScorerDiagnostic] = field(default_factory=list)

    def add_diagnostic(self, message: str) -> None:
        if message:
            self.diagnostics.append(str(message))

    def add_packet_seed(self, hint: PacketSeedHint) -> None:
        self.packet_seed_hints.append(hint)

    def record_stat(self, stat: GraphPassStat) -> None:
        self.pass_stats.append(stat)
        for message in stat.diagnostics:
            self.add_diagnostic(f"{stat.pass_name}: {message}")

    def add_scorer_diagnostic(self, diagnostic: ScorerDiagnostic) -> None:
        self.scorer_diagnostics.append(diagnostic)


# Backward-compatible alias for existing runtime imports.
GraphContext = PassContext


@dataclass(frozen=True, slots=True)
class GraphBuildResult:
    document_parse: DocumentParse
    packet_seed_hints: tuple[PacketSeedHint, ...]
    diagnostics: tuple[str, ...] = ()
    pass_stats: tuple[GraphPassStat, ...] = ()
    scorer_diagnostics: tuple[ScorerDiagnostic, ...] = ()

    def summary(self) -> "GraphSummary":
        return summarize_graph(self.document_parse)

    def packet_seed_diagnostics(self) -> tuple["PacketSeedDiagnostic", ...]:
        return get_packet_seed_diagnostics(self.document_parse)

    def conflict_diagnostics(self) -> tuple["ConflictDiagnostic", ...]:
        return get_conflict_diagnostics(self.document_parse)

    def provenance_for_node(self, node_id: str) -> "NodeProvenance | None":
        return get_node_provenance(self.document_parse, node_id)

    def provenance_for_edge(self, edge_id: str) -> "EdgeProvenance | None":
        return get_edge_provenance(self.document_parse, edge_id)

    def inspection_bundle(self) -> "GraphInspectionBundle":
        return build_graph_inspection_bundle(self.document_parse)


class GraphPass(Protocol):
    name: str

    def run(
        self,
        *,
        document_parse: DocumentParse,
        context: PassContext,
        indices: Any,
        signals: Any,
    ) -> tuple[DocumentParse, GraphPassStat]:
        ...


@dataclass(frozen=True, slots=True)
class GraphSummary:
    node_counts_by_family: Mapping[str, int]
    edge_counts_by_family: Mapping[str, int]
    edge_counts_by_pass: Mapping[str, int]
    disputed_edge_count: int
    packet_seed_count: int
    cue_attachment_count: int
    conflict_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_counts_by_family": dict(self.node_counts_by_family),
            "edge_counts_by_family": dict(self.edge_counts_by_family),
            "edge_counts_by_pass": dict(self.edge_counts_by_pass),
            "disputed_edge_count": self.disputed_edge_count,
            "packet_seed_count": self.packet_seed_count,
            "cue_attachment_count": self.cue_attachment_count,
            "conflict_count": self.conflict_count,
        }


@dataclass(frozen=True, slots=True)
class PacketSeedDiagnostic:
    seed_id: str
    anchor_span_ids: tuple[str, ...]
    cue_family: str | None
    neighborhood_node_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    source_pass: str
    strength_score: float
    anchor_weight: float | None
    neighborhood_size: int
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed_id": self.seed_id,
            "anchor_span_ids": list(self.anchor_span_ids),
            "cue_family": self.cue_family,
            "neighborhood_node_ids": list(self.neighborhood_node_ids),
            "reason_codes": list(self.reason_codes),
            "source_pass": self.source_pass,
            "strength_score": self.strength_score,
            "anchor_weight": self.anchor_weight,
            "neighborhood_size": self.neighborhood_size,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class ConflictDiagnostic:
    diagnostic_id: str
    family: str
    src_id: str
    dst_id: str
    reason_codes: tuple[str, ...]
    competing_edge_ids: tuple[str, ...]
    source_passes: tuple[str, ...]
    severity_score: float
    disagreement_strength: float
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnostic_id": self.diagnostic_id,
            "family": self.family,
            "src_id": self.src_id,
            "dst_id": self.dst_id,
            "reason_codes": list(self.reason_codes),
            "competing_edge_ids": list(self.competing_edge_ids),
            "source_passes": list(self.source_passes),
            "severity_score": self.severity_score,
            "disagreement_strength": self.disagreement_strength,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class NodeProvenance:
    node_id: str
    node_family: str
    source_span_ids: tuple[str, ...]
    source_section_id: str | None
    source_message_id: str | None
    created_by_pass: str | None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EdgeProvenance:
    edge_id: str
    edge_type: str
    src_id: str
    dst_id: str
    source_pass: str
    reason_codes: tuple[str, ...]
    weight: float | None = None
    signal_strength: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GraphInspectionBundle:
    summary: GraphSummary
    packet_seed_diagnostics: tuple[PacketSeedDiagnostic, ...]
    conflict_diagnostics: tuple[ConflictDiagnostic, ...]
    node_provenance_by_id: Mapping[str, NodeProvenance]
    edge_provenance_by_id: Mapping[str, EdgeProvenance]

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary.to_dict(),
            "packet_seed_diagnostics": [item.to_dict() for item in self.packet_seed_diagnostics],
            "conflict_diagnostics": [item.to_dict() for item in self.conflict_diagnostics],
            "node_provenance_by_id": {
                key: {
                    "node_id": value.node_id,
                    "node_family": value.node_family,
                    "source_span_ids": list(value.source_span_ids),
                    "source_section_id": value.source_section_id,
                    "source_message_id": value.source_message_id,
                    "created_by_pass": value.created_by_pass,
                    "metadata": dict(value.metadata),
                }
                for key, value in self.node_provenance_by_id.items()
            },
            "edge_provenance_by_id": {
                key: {
                    "edge_id": value.edge_id,
                    "edge_type": value.edge_type,
                    "src_id": value.src_id,
                    "dst_id": value.dst_id,
                    "source_pass": value.source_pass,
                    "reason_codes": list(value.reason_codes),
                    "weight": value.weight,
                    "signal_strength": value.signal_strength,
                    "metadata": dict(value.metadata),
                }
                for key, value in self.edge_provenance_by_id.items()
            },
        }

    def top_packet_seed_diagnostics(self, limit: int = 10) -> tuple[PacketSeedDiagnostic, ...]:
        ordered = sorted(
            self.packet_seed_diagnostics,
            key=lambda item: (
                item.strength_score,
                item.anchor_weight if item.anchor_weight is not None else -1.0,
                item.neighborhood_size,
            ),
            reverse=True,
        )
        return tuple(ordered[: max(0, limit)])

    def top_conflict_diagnostics(self, limit: int = 10) -> tuple[ConflictDiagnostic, ...]:
        ordered = sorted(
            self.conflict_diagnostics,
            key=lambda item: (item.severity_score, item.disagreement_strength),
            reverse=True,
        )
        return tuple(ordered[: max(0, limit)])


def summarize_graph(document_parse: DocumentParse) -> GraphSummary:
    from orbitbrief_core.parser.graph.indices import GraphIndices

    indices = GraphIndices.from_parse(document_parse)
    packet_seed_count = len(get_packet_seed_diagnostics(document_parse))
    edge_counts_by_family = dict(indices.edge_counts_by_family)
    cue_attachment_count = int(edge_counts_by_family.get("cue_attached_to_span", 0))
    disputed_edge_count = sum(1 for edge_id in indices.edge_provenance_by_id if "disputed" in edge_id)
    conflicts = get_conflict_diagnostics(document_parse)
    return GraphSummary(
        node_counts_by_family=dict(indices.node_counts_by_family),
        edge_counts_by_family=edge_counts_by_family,
        edge_counts_by_pass=dict(indices.edge_counts_by_pass),
        disputed_edge_count=disputed_edge_count,
        packet_seed_count=packet_seed_count,
        cue_attachment_count=cue_attachment_count,
        conflict_count=len(conflicts),
    )


def get_packet_seed_diagnostics(document_parse: DocumentParse) -> tuple[PacketSeedDiagnostic, ...]:
    raw = document_parse.metadata.get("packet_seed_hints", ())
    diagnostics: list[PacketSeedDiagnostic] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, Mapping):
            continue
        seed_id = f"packet_seed:{idx:04d}:{item.get('span_id', 'unknown')}"
        anchor_span_ids = (str(item.get("span_id")),) if item.get("span_id") else ()
        cue_values = item.get("cue_kinds", ())
        cue_family = str(cue_values[0]) if isinstance(cue_values, (list, tuple)) and cue_values else None
        metadata = dict(item.get("metadata", {})) if isinstance(item.get("metadata"), Mapping) else {}
        reason_codes = tuple(str(code) for code in metadata.get("reason_codes", []) if str(code))
        source_pass = str(metadata.get("source_pass", "unknown"))
        strength_score = float(item.get("score", 0.0) or 0.0)
        support = metadata.get("support_score")
        same_section = metadata.get("same_section_score")
        if support is None and same_section is None:
            anchor_weight = None
        else:
            support_val = float(support or 0.0)
            same_section_val = float(same_section or 0.0)
            anchor_weight = round((support_val * 0.7) + (same_section_val * 0.3), 6)
        neighborhood = tuple(str(value) for value in item.get("section_path", []) if str(value))
        diagnostics.append(
            PacketSeedDiagnostic(
                seed_id=seed_id,
                anchor_span_ids=anchor_span_ids,
                cue_family=cue_family,
                neighborhood_node_ids=neighborhood,
                reason_codes=reason_codes,
                source_pass=source_pass,
                strength_score=round(strength_score, 6),
                anchor_weight=anchor_weight,
                neighborhood_size=len(neighborhood),
                metadata=metadata,
            )
        )
    return tuple(diagnostics)


def get_conflict_diagnostics(document_parse: DocumentParse) -> tuple[ConflictDiagnostic, ...]:
    diagnostics: list[ConflictDiagnostic] = []
    for flag in document_parse.review_flags:
        if "conflict" not in flag.flag_id and "contradiction" not in flag.flag_id:
            continue
        metadata = dict(flag.metadata)
        src_id = str(metadata.get("left_span_id", "") or "")
        dst_id = str(metadata.get("right_span_id", "") or "")
        reason_codes = tuple(str(code) for code in metadata.get("reason_codes", []) if str(code))
        source_pass = str(metadata.get("source_pass", "unknown"))
        severity_map = {
            "info": 0.25,
            "warning": 0.7,
            "error": 1.0,
        }
        severity_score = float(severity_map.get(str(flag.severity.value).lower(), 0.5))
        disagreement_strength = float(metadata.get("disagreement_strength", 0.0) or 0.0)
        if disagreement_strength <= 0.0:
            disagreement_strength = min(1.0, 0.5 + (0.1 * len(reason_codes)))
        diagnostics.append(
            ConflictDiagnostic(
                diagnostic_id=flag.flag_id,
                family=str(metadata.get("edge_family", "conflict")),
                src_id=src_id,
                dst_id=dst_id,
                reason_codes=reason_codes,
                competing_edge_ids=tuple(str(value) for value in metadata.get("competing_edge_ids", []) if str(value)),
                source_passes=(source_pass,),
                severity_score=severity_score,
                disagreement_strength=round(disagreement_strength, 6),
                metadata=metadata,
            )
        )
    return tuple(diagnostics)


def get_node_provenance(document_parse: DocumentParse, node_id: str) -> NodeProvenance | None:
    from orbitbrief_core.parser.graph.indices import GraphIndices

    indices = GraphIndices.from_parse(document_parse)
    return indices.node_provenance_by_id.get(node_id)


def get_edge_provenance(document_parse: DocumentParse, edge_id: str) -> EdgeProvenance | None:
    from orbitbrief_core.parser.graph.indices import GraphIndices

    indices = GraphIndices.from_parse(document_parse)
    return indices.edge_provenance_by_id.get(edge_id)


def build_graph_inspection_bundle(document_parse: DocumentParse) -> GraphInspectionBundle:
    from orbitbrief_core.parser.graph.indices import GraphIndices

    indices = GraphIndices.from_parse(document_parse)
    return GraphInspectionBundle(
        summary=summarize_graph(document_parse),
        packet_seed_diagnostics=get_packet_seed_diagnostics(document_parse),
        conflict_diagnostics=get_conflict_diagnostics(document_parse),
        node_provenance_by_id=dict(indices.node_provenance_by_id),
        edge_provenance_by_id=dict(indices.edge_provenance_by_id),
    )
