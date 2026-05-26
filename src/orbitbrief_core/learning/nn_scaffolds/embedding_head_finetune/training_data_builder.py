"""Triplet builder for embedding_head_finetune — STUBBED.

When active, walks the JsonlTrainingLog + envelope artifacts to
produce `(anchor_atom, positive_atom, negative_atom)` triplets:

* Positive = atoms in the same PM-accepted packet
* Anchor = the packet's governing_atom
* Negative = atoms in OTHER packets, scored as similar by the
  zero-shot embedder (hard negatives)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TripletBuildConfig:
    training_log_path: Path
    envelopes_dir: Path
    out_path: Path
    min_triplets: int = 5000
    hard_negative_ratio: float = 0.5


def build_triplets(config: TripletBuildConfig) -> int:
    raise NotImplementedError(
        "embedding_head_finetune triplet builder is scaffolded but not connected. "
        "See README.md."
    )
