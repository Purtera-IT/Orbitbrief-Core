from __future__ import annotations

import re

from orbitbrief_core.parser.site_schematic.models import SiteSchematicOutletTypeDefinition

_OUTLET_LINE_RE = re.compile(
    r"(?im)^\s*(?:#\s*PORT\s+)?([A-Z0-9/&()'\- ]{3,140}?(?:OUTLET|CAMERA|READER|INTERCOM|PHONE|NODE|PANEL|DEVICE|SYMBOL))\s*$"
)
_PORT_RE = re.compile(r"(?i)\b(\d+)\s*[- ]?(?:port|cat)")
_CABLE_TYPE_RE = re.compile(r"(?i)\b(cat[- ]?\d+[a-z]?|rg-?\d+|fiber|singlemode|multimode|coax|utp)\b")
_MOUNT_RE = re.compile(r"(?i)\b(wall mounted|ceiling mounted|surface mounted|exterior mounted|above ceiling|aff)\b")
_TERMINATE_RE = re.compile(
    r"(?i)\b(dedicated admin patch panel|dedicated pos patch panel|patch panel|110 block|fiber panel|matv backboard|homerun[^.]{0,120})"
)
_POWER_RE = re.compile(r"(?i)\b(power|poe|120v|receptacle|ups)\b[^.]{0,80}")
_EXTRA_LABEL_PATTERNS = (
    "POINT OF SALE TERMINAL OUTLET",
    "POINT OF SALE PRINTER OUTLET",
    "WIRELESS NODE OUTLET",
    "ZIGBEE NODE OUTLET",
    "GUESTROOM DESK DATA OUTLET",
    "BED PHONE OUTLET - VOIP",
    "HOUSE PHONE OUTLET - VOIP",
    "PHONE OUTLET - ANALOG",
    "BED PHONE OUTLET - ANALOG",
    "HOUSE PHONE OUTLET - ANALOG",
    "ELEVATOR PHONE OUTLET - ANALOG",
    "DATA TV OUTLET - IPTV",
    "COAX TV OUTLET",
    "TV OUTLET - COAX AND DATA",
    "OUTLET - COAX, DATA AND FIBER",
    "ADMIN OUTLET",
    "DATA FLOOR BOX OUTLET",
)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def parse_outlet_type_lines(text: str) -> tuple[str, ...]:
    rows: list[str] = []
    seen: set[str] = set()
    for match in _OUTLET_LINE_RE.finditer(text or ""):
        value = _clean(match.group(1))
        if len(value) < 6:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append(value)
    lowered = (text or "").upper()
    for label in _EXTRA_LABEL_PATTERNS:
        if label in lowered:
            key = label.lower()
            if key not in seen:
                seen.add(key)
                rows.append(label.title())
    return tuple(rows)


def _context_for_label(text: str, label: str) -> str:
    pattern = re.compile(re.escape(label), flags=re.IGNORECASE)
    match = pattern.search(text or "")
    if not match:
        return text or ""
    start = max(0, match.start() - 80)
    end = min(len(text), match.end() + 220)
    return text[start:end]


def parse_outlet_type_definitions(text: str, *, page_index: int) -> tuple[SiteSchematicOutletTypeDefinition, ...]:
    rows = parse_outlet_type_lines(text)
    definitions: list[SiteSchematicOutletTypeDefinition] = []
    for idx, label in enumerate(rows, start=1):
        context = _context_for_label(text, label)
        cable_type_match = _CABLE_TYPE_RE.search(context) or _CABLE_TYPE_RE.search(label)
        port_match = _PORT_RE.search(label)
        mounting_match = _MOUNT_RE.search(context) or _MOUNT_RE.search(label)
        terminate_match = _TERMINATE_RE.search(context)
        power_match = _POWER_RE.search(context)
        remarks = _clean(context)
        definitions.append(
            SiteSchematicOutletTypeDefinition(
                definition_id=f"outlet_def:p{page_index}:{idx}",
                page_index=page_index,
                label=label,
                cable_count=int(port_match.group(1)) if port_match else None,
                cable_type=_clean(cable_type_match.group(1)) if cable_type_match else "",
                closet_termination=_clean(terminate_match.group(1)) if terminate_match else "",
                mounting=_clean(mounting_match.group(1)) if mounting_match else "",
                power_requirement=_clean(power_match.group(0)) if power_match else "",
                remarks=remarks,
                confidence=0.74,
            )
        )
    return tuple(definitions)
