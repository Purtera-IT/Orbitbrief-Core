"""Gap-rule auto-generator — SCAFFOLDED, NOT CONNECTED.

The institutional-learning crown jewel. Auto-mines new ``sow_missingness``
detector rules from items that PMs hand-added across past deals
(``pm_decisions.action == "added"`` in the learning ledger).

This is what makes the system **stop needing manual rule authoring**.
Every closed deal contributes detector evolution. Mining + clustering
+ verification + proposal — not a single classifier but a small
pipeline.

See ``README.md`` for the full activation path.
"""
from __future__ import annotations

__all__ = ["IS_ACTIVE"]

IS_ACTIVE: bool = False
