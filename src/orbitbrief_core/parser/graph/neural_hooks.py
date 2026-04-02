from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


class PairwiseScoreHook(Protocol):
    def __call__(self, *, left: Any, right: Any, features: Mapping[str, Any]) -> float | None:
        ...


class UnaryScoreHook(Protocol):
    def __call__(self, *, node: Any, features: Mapping[str, Any]) -> float | None:
        ...


@dataclass(frozen=True, slots=True)
class GraphNeuralHooks:
    same_topic_scorer: PairwiseScoreHook | None = None
    support_scorer: PairwiseScoreHook | None = None
    contradiction_scorer: PairwiseScoreHook | None = None
    packet_seed_scorer: UnaryScoreHook | None = None
    chronology_scorer: PairwiseScoreHook | None = None
    actor_affinity_scorer: PairwiseScoreHook | None = None
