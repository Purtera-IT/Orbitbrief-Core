"""Margin / outcome regression — SCAFFOLDED, NOT CONNECTED.

Small MLP (~5M params) predicting ``(deal_value_est, margin_est,
outcome_prob)`` from envelope features. Used as a sanity check on
the PM's margin assumptions and to flag risky deals at compile time.

Inputs: counts (atoms by type, packets by family), parser_quality,
domain pack mix, reconciliation flags, urgency signals, etc.
Outputs: three regressions for value / margin / outcome.

See ``README.md`` for activation path.
"""
from __future__ import annotations

__all__ = ["IS_ACTIVE"]

IS_ACTIVE: bool = False
