"""Fold parser taxonomy-v2 atom types onto the v1 types Core reads.

Core filters atoms by exact type in dozens of places -- the SOW body takes
only ``scope_item`` (pm_handoff/sow_draft.py), the exclusion sweep reads
``scope_item`` among others (pm_handoff/reconciliation.py), the gap and
question generators branch on it. The parser's v2 taxonomy splits
``scope_item`` into finer types (``work_scope_item`` first). Without this
fold, the day the parser emits a v2 type every such atom silently leaves the
SOW: nothing errors, the section is just shorter.

One fold at ingest instead of editing every filter: the envelope is rewritten
once, before the canonical copy is written, so every downstream reader sees a
type it knows. The parser's own label is kept on ``atom_type_v2`` so nothing
is lost and a v2-aware consumer can read it.
"""
from __future__ import annotations

from typing import Any

# v2 type -> the v1 type every Core filter already understands.
V2_TO_V1: dict[str, str] = {
    "work_scope_item": "scope_item",
}


def fold_v2_atom_types(envelope: dict[str, Any]) -> int:
    """Rewrite v2 atom types in place. Returns how many atoms were folded."""
    folded = 0
    for atom in envelope.get("atoms") or []:
        if not isinstance(atom, dict):
            continue
        v1 = V2_TO_V1.get(str(atom.get("atom_type") or ""))
        if v1 is None:
            continue
        atom.setdefault("atom_type_v2", atom["atom_type"])
        atom["atom_type"] = v1
        folded += 1
    return folded
