"""Eval harness for entity_cross_encoder — STUBBED.

When active, runs the trained cross-encoder against a held-out test
set of 500 hand-labeled pairs and computes:

* Precision / Recall / F1 vs the canonical_key heuristic baseline
* Per-entity-type breakdown (site / person / device / part_number)
* False-positive analysis (which heuristic-passed pairs the model rejects)
* Calibration (predicted P vs empirical accuracy in 10 buckets)

Blocks deployment if F1 lift < 5 pp or any per-entity-type F1 drops.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalResult:
    """Output shape (when active)."""

    f1: float
    precision: float
    recall: float
    baseline_f1: float
    f1_lift_pp: float
    per_type_f1: dict[str, float]
    blocked: bool
    block_reason: str = ""


def evaluate(model_path: str, test_pairs_jsonl: str) -> EvalResult:
    """Stub. See README for activation path."""
    raise NotImplementedError(
        "entity_cross_encoder eval harness is scaffolded but not connected."
    )
