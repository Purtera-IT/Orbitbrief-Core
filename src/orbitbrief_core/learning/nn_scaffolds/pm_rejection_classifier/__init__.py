"""PM-rejection classifier — SCAFFOLDED, NOT CONNECTED.

Predicts P(PM accepts) per brain output item. Used to pre-filter the
review queue: items with P < 0.3 are suppressed entirely; items with
P > 0.85 are auto-approved if validator status is clean.

This complements (does not replace) the Platt-calibrated calibrator.
The calibrator gives a calibrated probability that fires AFTER the
brain has run; this classifier predicts BEFORE the PM sees the item
so the queue starts shorter.

See ``README.md`` for activation path.
"""
from __future__ import annotations

__all__ = ["IS_ACTIVE"]

IS_ACTIVE: bool = False
