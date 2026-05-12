from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from orbitbrief_core.parser.graph.base import ScoreResult


@dataclass(frozen=True, slots=True)
class SameTopicRequest:
    left_span_id: str
    right_span_id: str
    left_text: str
    right_text: str
    signals: Any
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SupportRequest:
    anchor_span_id: str
    candidate_span_id: str
    anchor_text: str
    candidate_text: str
    signals: Any
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PacketSeedRequest:
    span_id: str
    text: str
    family_hints: tuple[str, ...]
    authority_class: str
    authority_score: float
    local_support_density: float
    cue_strength: float
    signals: Mapping[str, float] = field(default_factory=dict)


class SameTopicScorer(Protocol):
    def score(self, request: SameTopicRequest) -> ScoreResult:
        ...


class SupportScorer(Protocol):
    def score(self, request: SupportRequest) -> ScoreResult:
        ...


class PacketSeedScorer(Protocol):
    def score(self, request: PacketSeedRequest) -> ScoreResult:
        ...


@dataclass(frozen=True, slots=True)
class GraphNeuralHooks:
    same_topic_scorer: SameTopicScorer | None = None
    support_scorer: SupportScorer | None = None
    packet_seed_scorer: PacketSeedScorer | None = None
