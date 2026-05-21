"""Eval harness for gap_rule_generator candidate rules — STUBBED.

When active, for each candidate rule from the miner:

1. Run the rule against EVERY historical envelope (does it fire?)
2. For each fire, check if a PM hand-added an item matching the
   cluster centroid (positive match) or not (false-positive fire)
3. Compute precision (true positive fires / total fires) and recall
   (true positive fires / total deals where a matching item was added)
4. Block any candidate with precision < 0.7 OR recall < 0.6
5. Surface remaining candidates to a human reviewer for sow_missingness.yaml
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CandidateEval:
    rule_id: str
    precision: float
    recall: float
    fires_count: int
    matched_count: int                               # of fires, how many matched a PM-added item
    deals_checked: int
    blocked: bool
    block_reason: str = ""


def evaluate(candidates_jsonl: str, envelopes_dir: str) -> list[CandidateEval]:
    raise NotImplementedError(
        "gap_rule_generator eval harness is scaffolded but not connected."
    )
