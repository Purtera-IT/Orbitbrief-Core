"""Eval harness for margin_regression — STUBBED.

Three regression heads each scored independently:

* deal_value_est: log-scale MAE + MAPE
* margin_est_pct: linear MAE (percentage points)
* outcome_prob_won: AUC + Brier score

Blocks if margin_est MAE > 4 pp OR per-domain MAE bias > 2 pp.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalResult:
    margin_mae_pp: float
    margin_mape: float
    value_mae_log: float
    outcome_auc: float
    outcome_brier: float
    per_domain_margin_mae_pp: dict[str, float]
    blocked: bool
    block_reason: str = ""


def evaluate(model_path: str, test_jsonl: str) -> EvalResult:
    raise NotImplementedError(
        "margin_regression eval harness is scaffolded but not connected."
    )
