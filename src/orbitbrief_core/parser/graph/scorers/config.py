from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ScorerPolicy:
    threshold: float
    abstain_below: float | None
    max_fanout: int
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class GraphScorerPolicies:
    same_topic: ScorerPolicy = ScorerPolicy(threshold=0.72, abstain_below=0.2, max_fanout=5, enabled=True)
    support: ScorerPolicy = ScorerPolicy(threshold=0.75, abstain_below=0.25, max_fanout=6, enabled=True)
    packet_seed: ScorerPolicy = ScorerPolicy(threshold=0.70, abstain_below=0.2, max_fanout=4, enabled=True)
