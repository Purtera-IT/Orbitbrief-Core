"""Labeled-atom builder for atom_type_classifier — STUBBED.

When active, produces a JSONL of `(atom_text, section_path,
parser_name, atom_type, authority_class)` rows from:

* Existing parser-tagged atoms (bootstrap labels)
* PM corrections in `JsonlTrainingLog` where the PM relabeled an atom
* External annotation campaign (~5K rows)

Optionally augments with adversarial examples (atom_text variants
that should keep the same label).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LabelBuildConfig:
    envelopes_dir: Path
    corrections_file: Path | None
    out_path: Path
    min_rows: int = 5000


def build_labeled_atoms(config: LabelBuildConfig) -> int:
    raise NotImplementedError(
        "atom_type_classifier training_data_builder is scaffolded but not connected. "
        "See README.md."
    )
