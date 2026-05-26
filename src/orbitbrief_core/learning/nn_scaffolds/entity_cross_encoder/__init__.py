"""Entity cross-encoder — SCAFFOLDED, NOT CONNECTED.

Pair-wise scoring for entity coreference. When activated, replaces
the bulk of ``app/core/entity_resolution.py`` canonical_key matching
with a learned scorer that handles:

* product part-number ↔ description ↔ short SKU
* company / site names (acronym ↔ full ↔ abbreviation)
* person names with role / honorific disambiguation
* product family rollups ("Cisco DNA Spaces" / "DNA Spaces" /
  "location services platform")

See ``README.md`` for the activation path. Don't flip ``IS_ACTIVE``
until the gates are green.
"""
from __future__ import annotations

__all__ = ["IS_ACTIVE"]

IS_ACTIVE: bool = False
