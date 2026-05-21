"""Eval harness for atom_type_classifier — STUBBED.

When active:

* Macro-F1 (atom_type) + Macro-F1 (authority_class) on held-out atoms
* Per-class precision/recall (so a poor minority class is visible)
* Confusion matrix
* Comparison against the parser-rule baseline
* Block deployment if ANY class drops > 5 pp F1 vs baseline

Blocks if macro-F1 lift < 5 pp OR any per-class F1 regression > 5 pp.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalResult:
    atom_type_macro_f1: float
    authority_class_macro_f1: float
    baseline_atom_type_f1: float
    uplift_pp: float
    per_class_f1: dict[str, float]
    confusion_matrix: dict[str, dict[str, int]]
    blocked: bool
    block_reason: str = ""


def evaluate(model_path: str, test_jsonl: str) -> EvalResult:
    raise NotImplementedError(
        "atom_type_classifier eval harness is scaffolded but not connected."
    )
