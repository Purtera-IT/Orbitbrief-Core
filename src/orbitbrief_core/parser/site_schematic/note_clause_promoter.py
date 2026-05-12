from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence

from orbitbrief_core.parser.site_schematic.final_text_tail_registry import lookup_tail_note_gap_profile


_NOTE_PATTERNS = (
    re.compile(r"^\s*(?:\d+[\.\)]|[A-Z][\.\)]|[•\-])\s+"),
    re.compile(r"\b(?:general note|keyed note|project requirements?|notes?|specifications?)\b", re.IGNORECASE),
)
_DISALLOWED_SHORT_LABELS = re.compile(r"^\s*(?:room|rm|idf|mdf|office|corridor)\s*[a-z0-9-]*\s*$", re.IGNORECASE)
_ALLOWED_SHEET_TYPES = {"schedule_sheet", "notes_spec", "legend_symbol", "riser_diagram", "floorplan_overall"}


def looks_like_note_text(text: str, *, strict_for_floorplan: bool = False) -> bool:
    value = (text or "").strip()
    if len(value) < 20:
        return False
    if _DISALLOWED_SHORT_LABELS.match(value):
        return False
    if strict_for_floorplan and len(value.split()) < 8:
        return False
    return any(pattern.search(value) for pattern in _NOTE_PATTERNS)


def promote_note_clauses_from_blocks(
    *,
    packet_id: str = "",
    page_index: int = -1,
    sheet_type: str,
    layout_blocks: Sequence[Any],
    existing_note_count: int,
) -> List[Dict[str, Any]]:
    """
    Deterministically promote note-like layout blocks only when note emission
    is currently empty for note-heavy sheets.
    """
    if sheet_type not in _ALLOWED_SHEET_TYPES:
        return []
    if existing_note_count > 0:
        return []
    residual_profile = lookup_tail_note_gap_profile(packet_id, page_index, sheet_type)
    strict_for_floorplan = sheet_type == "floorplan_overall"
    promoted: List[Dict[str, Any]] = []
    for idx, block in enumerate(layout_blocks):
        text = getattr(block, "text", None) if not isinstance(block, dict) else block.get("text")
        bbox = getattr(block, "bbox", None) if not isinstance(block, dict) else block.get("bbox")
        if not text or bbox is None:
            continue
        min_chars = int((residual_profile or {}).get("min_block_chars", 20))
        stripped = (text or "").strip()
        if len(stripped) < min_chars:
            continue
        explicit_note_cue = any(
            token in stripped.lower()
            for token in ("note", "notes", "requirements", "spec", "installation", "warranty", "labeling", "guidelines")
        )
        allow_sidecar = bool((residual_profile or {}).get("allow_table_adjacent_sidecar", False))
        require_explicit = bool((residual_profile or {}).get("require_explicit_note_cue", False))
        allow = looks_like_note_text(stripped, strict_for_floorplan=strict_for_floorplan) or (allow_sidecar and explicit_note_cue)
        if require_explicit and not explicit_note_cue:
            allow = False
        if allow:
            promoted.append(
                {
                    "promoted_note_id": f"promoted_note:{idx}",
                    "text": stripped,
                    "bbox": bbox,
                    "reason": "note_like_block_promotion",
                    "source_mode": "deterministic_note_promoter_v1",
                    "residual_profile": (residual_profile or {}).get("profile", ""),
                }
            )
    return promoted
