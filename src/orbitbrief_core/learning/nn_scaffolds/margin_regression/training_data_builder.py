"""Training-data builder for margin_regression — STUBBED.

When active, walks closed-outcome rows in the learning ledger and
joins each to its envelope to produce feature vectors:

* Atom counts by type
* Packet counts by family
* Parser quality score
* Domain pack one-hot
* Reconciliation flag count
* Has_vendor_quote / has_executive_stakeholder / has_compliance_callout
* Retrieved-comparable avg margin (uses retrieve_similar_deals())

Labels: deal_value_usd, final_margin_pct, outcome (won/lost/none).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BuildConfig:
    ledger_path: Path
    out_path: Path
    min_records: int = 50
    require_known_outcome: bool = True


def build_training_set(config: BuildConfig) -> int:
    raise NotImplementedError(
        "margin_regression training_data_builder is scaffolded but not connected. "
        "See README.md."
    )
