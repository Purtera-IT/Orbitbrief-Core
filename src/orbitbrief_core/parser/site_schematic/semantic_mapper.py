from __future__ import annotations

import re
from typing import Any

from orbitbrief_core.parser.site_schematic.evidence_backed_flags import evidence_backed_room_assoc_ok
from orbitbrief_core.parser.site_schematic.legend_grounding_models import LegendGroundingEntry
from orbitbrief_core.parser.site_schematic.legend_text_association import score_legend_text_association
from orbitbrief_core.parser.site_schematic.primitive_symbol_ontology import DEFAULT_V2_ONTOLOGY

_ALIAS_TOKEN_RE = re.compile(r"\b[A-Z][A-Z0-9/-]{0,10}\b")
_COMPOUND_NORMALIZATIONS: tuple[tuple[str, str], ...] = (
    (r"camera\s+schedule", "camera"),
    (r"cctv\s+schedule", "camera"),
    (r"ground\s+busbar|telecommunications?\s+ground\s+busbar|tmgb|tgb", "ground bar"),
    (r"pull\s*/\s*junction\s+box|junction\s*/\s*pull\s+box", "junction box"),
)


def _extract_aliases(label: str, extra_aliases: list[str] | tuple[str, ...] = ()) -> tuple[str, ...]:
    aliases: list[str] = []
    if label:
        aliases.append(label)
        aliases.extend(_ALIAS_TOKEN_RE.findall(label))
    aliases.extend(str(row).strip() for row in extra_aliases if str(row).strip())
    deduped: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        key = alias.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(alias)
    return tuple(deduped[:12])


def build_legend_grounding_dictionary(
    *,
    page_index: int,
    legend_entries: list[Any],
) -> list[LegendGroundingEntry]:
    alias_to_family: dict[str, str] = {}
    for entry in DEFAULT_V2_ONTOLOGY:
        for alias in entry.aliases:
            alias_to_family[alias.lower()] = entry.family

    grounded: list[LegendGroundingEntry] = []
    for idx, entry in enumerate(legend_entries):
        if isinstance(entry, dict):
            label = (entry.get("label") or entry.get("description") or entry.get("raw_text") or "").strip()
            source_row_id = entry.get("source_row_id", "")
            source_cell_ids = tuple(entry.get("source_cell_ids", []) or [])
            bbox = entry.get("bbox")
            extra_aliases = tuple(entry.get("aliases", []) or [])
        else:
            label = (getattr(entry, "label", "") or getattr(entry, "description", "") or "").strip()
            source_row_id = getattr(entry, "source_row_id", "")
            source_cell_ids = tuple(getattr(entry, "source_cell_ids", ()) or ())
            bbox = getattr(entry, "bbox", None)
            extra_aliases = tuple(getattr(entry, "aliases", ()) or ())

        lowered = label.lower()
        for pattern, replacement in _COMPOUND_NORMALIZATIONS:
            lowered = re.sub(pattern, replacement, lowered)
        family = "unknown_symbol_group"
        for alias, fam in alias_to_family.items():
            if alias in lowered:
                family = fam
                break
        aliases = _extract_aliases(label, extra_aliases)
        grounded.append(
            LegendGroundingEntry(
                legend_id=f"legend:{page_index}:{idx}",
                page_index=page_index,
                family=family,
                raw_label=label,
                aliases=aliases,
                source_row_id=source_row_id,
                source_cell_ids=source_cell_ids,
                bbox=bbox,
                confidence=0.8 if family != "unknown_symbol_group" else 0.4,
            )
        )
    return grounded


def score_candidate_legend_text_association(
    *,
    legend_text: str,
    nearby_note_text: str = "",
    outlet_definition_text: str = "",
    abbreviation_text: str = "",
) -> float:
    return score_legend_text_association(
        legend_text=legend_text,
        nearby_note_text=nearby_note_text,
        outlet_definition_text=outlet_definition_text,
        abbreviation_text=abbreviation_text,
    )


def evidence_backed_room_association_flag(
    *,
    room_device_association_score: float,
    near_room_label: bool,
    same_region: bool,
    leader_attached: bool,
) -> bool:
    return evidence_backed_room_assoc_ok(
        room_device_association_score=room_device_association_score,
        near_room_label=near_room_label,
        same_region=same_region,
        leader_attached=leader_attached,
    )
