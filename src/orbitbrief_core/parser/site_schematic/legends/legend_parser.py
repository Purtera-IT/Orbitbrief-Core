from __future__ import annotations

import re

from orbitbrief_core.parser.site_schematic.legends.abbreviation_parser import parse_abbreviation_entries
from orbitbrief_core.parser.site_schematic.legends.outlet_type_parser import parse_outlet_type_lines
from orbitbrief_core.parser.site_schematic.models import SiteSchematicLegendEntry

_SECTION_RE = re.compile(r"(?im)^\s*([A-Z][A-Z0-9/&()' .,-]{3,120}(?:LEGEND|LEGENDS|SYMBOLS|OUTLET TYPE DESCRIPTION|TAG SYMBOLS|AV SYMBOLS))\s*$")
_TOKEN_RE = re.compile(r"\b(AP|WAP|WM|CM|EXT|AV|RS\d+|CIP|CSP\d+|PP|FIC|TV|POS-T|POS-P|WN|ZN|HC|FE|CRD|AR|DA|MKP|SCP|KP|DAM|LM|BH|TCDS|IC180°|360°|[12]M8|HM8)\b", flags=re.IGNORECASE)
_RULE_LINE_RE = re.compile(r"(?im)^\s*(?:\d+\.|[A-Z]\.|[-*])\s+(.{8,240})$")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def infer_primitive_kind(text: str) -> str:
    lowered = (text or "").lower()
    upper = (text or "").upper()
    if any(token in upper for token in ("AP", "WAP")) and any(token in lowered for token in ("wireless", "access point", "wap")) or upper.strip() in {"AP", "WAP"}:
        return "ap_like_marker"
    if upper.strip() in {"CM", "WM", "EXT", "AV", "CIP", "CSP2", "CSP3", "RS1", "RS2", "RS3"}:
        return "outlet_glyph"
    if upper.strip() in {"PP", "FIC", "TV"}:
        return "rack_or_patch_symbol"
    if any(token in lowered for token in ("wireless", "wap", "access point")):
        return "ap_like_marker"
    if any(token in lowered for token in ("camera", "cctv", "bullet style", "dome")):
        return "camera_like_marker"
    if any(token in lowered for token in ("patch panel", "rack", "cabinet", "fic", "110 block", "busbar")):
        return "rack_or_patch_symbol"
    if any(token in lowered for token in ("reader", "intercom", "phone", "outlet", "data", "voice", "node", "time clock", "signage", "ceiling mounted", "wall mounted", "exterior mounted")):
        return "outlet_glyph"
    if any(token in lowered for token in ("pull box", "junction box")):
        return "pull_box_icon"
    if any(token in lowered for token in ("conduit", "sleeve", "pathway")):
        return "pathway_icon"
    if any(token in lowered for token in ("callout", "tag", "revision bubble", "indexing symbol")):
        return "tag_bubble"
    return "generic_marker"


def _rules_for_text(text: str) -> dict[str, str]:
    lowered = (text or "").lower()
    rules: dict[str, str] = {}
    if "patch panel" in lowered or "terminate" in lowered:
        rules["termination"] = _clean(text)
    if "mount" in lowered or "aff" in lowered:
        rules["mounting"] = _clean(text)
    if "slack" in lowered or "service loop" in lowered:
        rules["service_loop"] = _clean(text)
    if "power" in lowered or "poe" in lowered:
        rules["power"] = _clean(text)
    if any(color in lowered for color in ("red", "green", "blue", "black", "yellow", "aqua", "gray", "grey")):
        rules["color"] = _clean(text)
    return rules


def _section_map(text: str) -> dict[int, str]:
    mapping: dict[int, str] = {}
    current = "legend"
    for idx, line in enumerate(text.splitlines()):
        clean = _clean(line)
        if _SECTION_RE.match(clean):
            current = clean.upper()
        mapping[idx] = current
    return mapping


def parse_legend_entries(text: str, *, page_index: int, overlay_tags: tuple[str, ...] = ()) -> tuple[SiteSchematicLegendEntry, ...]:
    lines = [line.rstrip() for line in (text or "").splitlines() if line.strip()]
    section_map = _section_map(text)
    abbreviations = parse_abbreviation_entries(text, page_index=page_index)
    outlet_lines = parse_outlet_type_lines(text)
    rule_lines = [_clean(match.group(1)) for match in _RULE_LINE_RE.finditer(text)]
    rows: list[SiteSchematicLegendEntry] = []
    seen: set[tuple[str, str, str]] = set()
    counter = 0

    def append_entry(*, section: str, label: str, description: str, symbol_token: str = "", confidence: float = 0.78) -> None:
        nonlocal counter
        label = _clean(label)
        description = _clean(description)
        primitive_kind = infer_primitive_kind(f"{label} {description}")
        key = (label.lower(), description.lower(), primitive_kind)
        if not label or not description or key in seen:
            return
        seen.add(key)
        counter += 1
        rows.append(
            SiteSchematicLegendEntry(
                entry_id=f"legend:p{page_index}:{counter}",
                page_index=page_index,
                section=section,
                label=label,
                description=description,
                primitive_kind=primitive_kind,
                symbol_token=symbol_token.upper(),
                overlay_tags=overlay_tags,
                confidence=confidence,
                rules=_rules_for_text(description),
            )
        )

    for outlet_line in outlet_lines:
        token_match = _TOKEN_RE.search(outlet_line)
        append_entry(section="OUTLET TYPE DESCRIPTION", label=outlet_line, description=outlet_line, symbol_token=token_match.group(1) if token_match else "", confidence=0.84)

    for idx, line in enumerate(lines):
        clean = _clean(line)
        lower = clean.lower()
        section = section_map.get(idx, "legend")
        if len(clean) < 6 or len(clean) > 180:
            continue
        if _SECTION_RE.match(clean):
            continue
        if any(token in lower for token in ("outlet", "camera", "reader", "intercom", "wireless node", "phone", "patch panel", "telecomm", "telecommunications", "data and fiber", "room scheduling", "time clock", "signage", "card reader", "security control panel")):
            token_match = _TOKEN_RE.search(clean)
            append_entry(section=section, label=clean, description=clean, symbol_token=token_match.group(1) if token_match else "", confidence=0.76)

    for entry in abbreviations:
        if entry.category in {"mounting_rule", "color_convention"}:
            append_entry(section="ABBREVIATIONS", label=entry.token, description=entry.meaning, symbol_token=entry.token, confidence=0.74)

    # Promote packet-level rules from legend pages into structured legend entries when they define behavior.
    for rule in rule_lines:
        lower = rule.lower()
        if any(token in lower for token in ("patch panel", "service loop", "slack", "jacks shall be", "jack colors", "wireless", "camera", "wall phones", "elevators", "lan")):
            token_match = _TOKEN_RE.search(rule)
            label = token_match.group(1) if token_match else "LEGEND RULE"
            append_entry(section="LEGEND RULES", label=label, description=rule, symbol_token=token_match.group(1) if token_match else "", confidence=0.7)

    return tuple(rows)


def build_legend_lookup(entries: tuple[SiteSchematicLegendEntry, ...]) -> dict[str, list[SiteSchematicLegendEntry]]:
    lookup: dict[str, list[SiteSchematicLegendEntry]] = {}
    for entry in entries:
        keys = {entry.label.upper(), entry.symbol_token.upper()}
        for match in _TOKEN_RE.finditer(f"{entry.label} {entry.description}"):
            keys.add(match.group(1).upper())
        for key in keys:
            key = key.strip()
            if not key:
                continue
            lookup.setdefault(key, []).append(entry)
    return lookup
