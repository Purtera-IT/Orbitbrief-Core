"""Candidate rule miner for gap_rule_generator — STUBBED.

The miner reads ``LearningLedger`` rows where
``pm_decisions.action == "added"`` and clusters the added items by
embedding to find recurring patterns. Each cluster (with ≥ 5 items)
becomes a candidate detector rule.

The output is a JSONL of proposed rules in ``sow_missingness.yaml``
shape, ready for human review.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CandidateRule:
    """Output shape (when active)."""

    rule_id: str                                     # auto-generated, e.g. "wireless.poe_class_per_ap"
    domain_id: str                                   # inferred from cluster majority
    label: str                                       # human-readable name
    severity: str                                    # "blocker" | "warning" | "info"
    missing_pattern: dict                            # detector spec
    suggested_question: str                          # what PM should ask the customer
    cluster_size: int
    cluster_centroid_text: str                       # exemplar item from the cluster


@dataclass(frozen=True)
class MineConfig:
    ledger_path: Path
    envelopes_dir: Path
    out_path: Path
    cluster_min_samples: int = 5
    cluster_eps: float = 0.3


def mine_candidate_rules(config: MineConfig) -> int:
    raise NotImplementedError(
        "gap_rule_generator candidate-rule miner is scaffolded but not connected. "
        "See README.md."
    )
