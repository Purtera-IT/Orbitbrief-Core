from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Tuple


@dataclass
class TitleblockProfile:
    family: str
    aliases: List[str] = field(default_factory=list)
    header_keywords: List[str] = field(default_factory=list)
    sheet_prefixes: List[str] = field(default_factory=list)


DEFAULT_HOLDOUT_PROFILES = [
    TitleblockProfile(
        family="legend_symbol",
        aliases=["symbols and legends", "symbol legend", "legend", "legend sheet"],
        header_keywords=["legend", "symbols", "responsibility matrix", "abbreviations"],
        sheet_prefixes=["T001", "TC001", "L001"],
    ),
    TitleblockProfile(
        family="notes_spec",
        aliases=["project requirements notes & specs", "notes & specs", "general notes", "requirements"],
        header_keywords=["notes", "requirements", "spec", "project requirements"],
        sheet_prefixes=["T000", "G000", "N000"],
    ),
    TitleblockProfile(
        family="riser_diagram",
        aliases=["conduit riser diagram", "cabling riser diagram", "matv cabling riser diagram", "riser"],
        header_keywords=["riser", "conduit riser", "cabling riser", "matv"],
        sheet_prefixes=["T901", "T902", "T903", "TC301"],
    ),
    TitleblockProfile(
        family="equipment_room_layout",
        aliases=["enlarged equipment room layouts", "equipment room", "rack details"],
        header_keywords=["equipment room", "rack", "idf", "mdf", "telecom room"],
        sheet_prefixes=["T900", "T904", "TC502"],
    ),
    TitleblockProfile(
        family="installation_detail",
        aliases=["security installation details", "installation details", "telecomm details"],
        header_keywords=["details", "installation", "security", "telecomm details"],
        sheet_prefixes=["T905", "T906", "TC502"],
    ),
    TitleblockProfile(
        family="floorplan",
        aliases=["floor plan", "plan overall", "part plan", "guestroom layouts"],
        header_keywords=["plan", "overall", "part", "guestroom"],
        sheet_prefixes=["T100", "T101", "T102", "T103", "T104", "T105", "T106", "T700", "TC100", "TC101", "TC102", "TC103", "TC104", "TC105", "TC200"],
    ),
]


def score_sheet_text_against_holdout_profiles(
    text_candidates: Iterable[str],
    sheet_id_candidates: Iterable[str] | None = None,
) -> Dict[str, float]:
    text_lower = " | ".join((t or "").lower() for t in text_candidates)
    sheet_id_candidates = list(sheet_id_candidates or [])
    scores: Dict[str, float] = {}

    for profile in DEFAULT_HOLDOUT_PROFILES:
        score = 0.0
        for alias in profile.aliases:
            if alias in text_lower:
                score += 2.0
        for kw in profile.header_keywords:
            if kw in text_lower:
                score += 0.5
        for sid in sheet_id_candidates:
            sid_u = sid.upper()
            if any(sid_u.startswith(prefix) for prefix in profile.sheet_prefixes):
                score += 1.5
        if score:
            scores[profile.family] = scores.get(profile.family, 0.0) + score

    # guardrails
    if "riser_diagram" in scores and "legend_symbol" in scores:
        scores["riser_diagram"] += 0.75
    if "floorplan" in scores and "notes_spec" in scores and "project requirements" not in text_lower:
        scores["floorplan"] += 0.25

    return scores
