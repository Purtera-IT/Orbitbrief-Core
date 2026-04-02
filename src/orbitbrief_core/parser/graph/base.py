from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from orbitbrief_core.parser.router import ParsePlan
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
    strict_mode: bool = True


@dataclass(slots=True)
class GraphContext:
    parse_plan: ParsePlan
    compiled_pack: Any
    config: GraphBuildConfig
    hooks: Any | None = None
    diagnostics: list[str] = field(default_factory=list)
    packet_seed_hints: list[PacketSeedHint] = field(default_factory=list)
    pass_stats: list[GraphPassStat] = field(default_factory=list)

    def add_diagnostic(self, message: str) -> None:
        if message:
            self.diagnostics.append(str(message))

    def add_packet_seed(self, hint: PacketSeedHint) -> None:
        self.packet_seed_hints.append(hint)

    def record_stat(self, stat: GraphPassStat) -> None:
        self.pass_stats.append(stat)
        for message in stat.diagnostics:
            self.add_diagnostic(f"{stat.pass_name}: {message}")


@dataclass(frozen=True, slots=True)
class GraphBuildResult:
    document_parse: DocumentParse
    packet_seed_hints: tuple[PacketSeedHint, ...]
    diagnostics: tuple[str, ...] = ()
    pass_stats: tuple[GraphPassStat, ...] = ()


class GraphPass(Protocol):
    name: str

    def run(self, *, document_parse: DocumentParse, context: GraphContext, indices: Any) -> tuple[DocumentParse, GraphPassStat]:
        ...
