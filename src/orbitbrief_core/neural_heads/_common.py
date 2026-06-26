"""Shared helpers for teacher/judge heads: atom tagging + citation grounding.

The teacher must cite atom tags (A1..AN); we validate every cited tag exists, so
fabrication is structurally impossible (a claim that cites nothing real is dropped).
"""
from __future__ import annotations

from typing import Any


def tag_atoms(envelope: dict, keep_types: set[str] | None, limit: int = 60,
              with_doc: bool = False) -> tuple[str, dict[str, dict]]:
    """Return (rendered_context, tagmap). Atoms are filtered to ``keep_types``
    (all types if None) and tagged A1..AN. ``with_doc`` prefixes the source doc."""
    docs = {d.get("artifact_id"): (d.get("filename") or "")[:22]
            for d in (envelope.get("documents") or [])}
    atoms = [a for a in (envelope.get("atoms") or [])
             if (keep_types is None or a.get("atom_type") in keep_types)
             and (a.get("text") or "").strip()][:limit]
    tagmap: dict[str, dict] = {}
    lines = []
    for i, a in enumerate(atoms, 1):
        tag = f"A{i}"
        tagmap[tag] = a
        prefix = f"({docs.get(a.get('artifact_id'), '?')}) " if with_doc else ""
        lines.append(f"  {tag}: {prefix}[{a.get('atom_type')}] {(a.get('text') or '')[:130]}")
    return "\n".join(lines), tagmap


def valid_cites(item: dict, tagmap: dict[str, dict], min_cites: int = 1) -> list[str]:
    """Keep only cited tags that exist; returns [] if fewer than ``min_cites``."""
    cited = [t for t in (item.get("atom_ids") or item.get("evidence_ids") or []) if t in tagmap]
    return cited if len(cited) >= min_cites else []
