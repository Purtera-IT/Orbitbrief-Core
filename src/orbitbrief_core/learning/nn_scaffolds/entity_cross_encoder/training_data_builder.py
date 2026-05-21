"""Training-data builder for entity_cross_encoder — STUBBED.

Activated when ≥ 2-3K labeled `(text_a, text_b, same)` pairs are
needed for training.

What this would produce (when active):

* JSONL of `{"text_a": ..., "text_b": ..., "label": 0|1, "metadata": {...}}` rows
* Positive pairs: bootstrapped from `entities[].aliases` in past envelopes
* Negative pairs: random non-overlapping entity pairs from the same corpus
* Hard negatives: pairs that the canonical_key matcher incorrectly merged
  (mined from `pm_decisions.action == "rejected"` on entity-merge decisions)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TrainingDataBuildConfig:
    """Knobs for the bootstrap. Not used in production."""

    envelopes_dir: Path
    out_path: Path
    min_positive_pairs: int = 2000
    negative_ratio: float = 1.5                      # negatives per positive


def build_training_pairs(config: TrainingDataBuildConfig) -> int:
    """Stub. Raises NotImplementedError. See README for activation path."""
    raise NotImplementedError(
        "entity_cross_encoder training pipeline is scaffolded but not connected. "
        "See src/orbitbrief_core/learning/nn_scaffolds/entity_cross_encoder/README.md."
    )
