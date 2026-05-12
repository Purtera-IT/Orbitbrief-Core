from __future__ import annotations

import re

from orbitbrief_core.parser.site_schematic.models import SiteSchematicAbbreviationEntry

_ABBREV_RE = re.compile(r"(?m)^\s*([A-Z][A-Z0-9./()'\"#&+_-]{1,24})\s*(?:-|=|:)\s*(.{3,180})$")
_COLOR_RE = re.compile(r"\b(red|green|blue|black|yellow|aqua|gray|grey|white)\b\s*(?:=|-)\s*([^\n.;]{2,120})", flags=re.IGNORECASE)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def parse_abbreviation_entries(text: str, *, page_index: int) -> tuple[SiteSchematicAbbreviationEntry, ...]:
    rows: list[SiteSchematicAbbreviationEntry] = []
    seen: set[tuple[str, str, str]] = set()
    counter = 0
    for match in _ABBREV_RE.finditer(text or ""):
        token = _clean(match.group(1)).upper()
        meaning = _clean(match.group(2))
        if not token or not meaning:
            continue
        category = "abbreviation"
        lower = meaning.lower()
        if any(word in lower for word in ("wall mounted", "ceiling mounted", "exterior mounted", "mounted")):
            category = "mounting_rule"
        elif any(word in lower for word in ("wireless", "camera", "lan", "wall phones", "elevators")) and token.lower() in {"red", "green", "blue", "black", "yellow", "aqua", "gray", "grey", "white"}:
            category = "color_convention"
        key = (token, meaning.lower(), category)
        if key in seen:
            continue
        seen.add(key)
        counter += 1
        rows.append(
            SiteSchematicAbbreviationEntry(
                entry_id=f"abbr:p{page_index}:{counter}",
                page_index=page_index,
                token=token,
                meaning=meaning,
                category=category,
                confidence=0.82,
            )
        )
    for match in _COLOR_RE.finditer(text or ""):
        token = _clean(match.group(1)).upper()
        meaning = _clean(match.group(2))
        key = (token, meaning.lower(), "color_convention")
        if key in seen:
            continue
        seen.add(key)
        counter += 1
        rows.append(
            SiteSchematicAbbreviationEntry(
                entry_id=f"abbr:p{page_index}:{counter}",
                page_index=page_index,
                token=token,
                meaning=meaning,
                category="color_convention",
                confidence=0.84,
            )
        )
    return tuple(rows)


def build_abbreviation_lookup(entries: tuple[SiteSchematicAbbreviationEntry, ...]) -> dict[str, SiteSchematicAbbreviationEntry]:
    lookup: dict[str, SiteSchematicAbbreviationEntry] = {}
    for entry in entries:
        lookup.setdefault(entry.token.upper(), entry)
    return lookup
