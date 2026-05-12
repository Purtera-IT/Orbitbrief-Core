from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List


@dataclass
class ResidualTitleblockProfile:
    packet_hint: str
    families: Dict[str, List[str]] = field(default_factory=dict)
    footer_keywords: List[str] = field(default_factory=list)
    title_keywords: List[str] = field(default_factory=list)


RESIDUAL_TITLEBLOCK_PROFILES = [
    ResidualTitleblockProfile(
        packet_hint="school_admin_security",
        families={
            "legend_symbol": ["symbols", "legend", "communications legend"],
            "notes_spec": ["project requirements", "general notes", "specifications", "requirements"],
            "riser_diagram": ["riser diagram", "communications riser", "telecom riser"],
            "installation_detail": ["details", "installation details", "communications details", "security details"],
            "floorplan": ["floor plan", "overall", "part plan", "telecomm plan"],
        },
        footer_keywords=["issued for construction", "drawing issue", "project no", "title", "number"],
        title_keywords=["telecomm", "communications", "security", "technology"],
    ),
    ResidualTitleblockProfile(
        packet_hint="hospitality_security",
        families={
            "legend_symbol": ["symbols & legends", "legend", "matrix"],
            "notes_spec": ["project requirements notes & specs", "notes & specs"],
            "schedule_sheet": ["schedules", "miscellaneous", "specifications list"],
            "equipment_room_layout": ["equipment room", "rack details", "closet layouts"],
            "installation_detail": ["installation details", "security installation details"],
            "riser_diagram": ["conduit riser", "cabling riser", "matv cabling riser"],
        },
        footer_keywords=["sheet number", "sheet title", "of", "drawing index"],
        title_keywords=["structured cabling", "security", "voice and data", "matv"],
    ),
]


def score_residual_titleblock_families(text_candidates: Iterable[str], sheet_id_candidates: Iterable[str] | None = None) -> Dict[str, float]:
    text_join = " | ".join((t or "").lower() for t in text_candidates)
    sheet_id_candidates = [s.upper() for s in (sheet_id_candidates or [])]
    scores: Dict[str, float] = {}

    for profile in RESIDUAL_TITLEBLOCK_PROFILES:
        profile_score = 0.0
        if any(kw in text_join for kw in profile.footer_keywords):
            profile_score += 0.5
        if any(kw in text_join for kw in profile.title_keywords):
            profile_score += 0.5
        for family, kws in profile.families.items():
            fam_score = 0.0
            for kw in kws:
                if kw in text_join:
                    fam_score += 0.75
            if fam_score:
                scores[family] = scores.get(family, 0.0) + fam_score + profile_score

    # additional sheet prefix priors
    for sid in sheet_id_candidates:
        if sid.startswith(("TC", "T1", "T7", "T9", "C", "S")):
            scores["floorplan"] = scores.get("floorplan", 0.0) + 0.1

    return scores
