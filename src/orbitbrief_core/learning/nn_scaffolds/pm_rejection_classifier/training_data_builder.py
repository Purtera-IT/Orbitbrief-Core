"""Training-data builder for pm_rejection_classifier — STUBBED.

When active, walks JsonlTrainingLog rows and produces
`(features, label)` JSONL where:

* features = predicted_payload text + atom_type + brain + signal_vector
* label = 1 if reviewer_action == "accepted", else 0
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DecisionBuildConfig:
    training_log_path: Path
    out_path: Path
    min_decisions: int = 300
    min_reject_rate: float = 0.10                    # must have ≥10% rejection to train


def build_pm_decisions(config: DecisionBuildConfig) -> int:
    raise NotImplementedError(
        "pm_rejection_classifier training_data_builder is scaffolded but not connected. "
        "See README.md."
    )
