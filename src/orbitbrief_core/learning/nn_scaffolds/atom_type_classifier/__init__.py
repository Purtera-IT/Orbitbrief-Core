"""Atom-type + authority_class classifier — SCAFFOLDED, NOT CONNECTED.

Small encoder + 2 linear heads jointly predicting:

* ``atom_type`` ∈ {13 canonical types}
* ``authority_class`` ∈ {customer_current_authored | vendor_quote | ...}

Replaces / augments the per-parser heuristics in ``app.parsers.*``.
The parser still does locator extraction (deterministic); the
classifier handles the typing decision.
"""
from __future__ import annotations

__all__ = ["IS_ACTIVE"]

IS_ACTIVE: bool = False
