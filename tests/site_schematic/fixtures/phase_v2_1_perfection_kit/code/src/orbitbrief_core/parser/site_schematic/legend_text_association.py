from __future__ import annotations

import re
from typing import Dict, Iterable, List


ALIAS_NORMALIZATIONS = {
    "wap": "wireless access point",
    "ap": "wireless access point",
    "cctv": "camera",
    "cam": "camera",
    "tv": "television",
    "idf": "telecom closet",
    "mdf": "main telecom room",
    "pb": "pull box",
    "jbox": "junction box",
}


def normalize_semantic_text(text: str) -> str:
    lowered = (text or "").lower()
    for src, dst in ALIAS_NORMALIZATIONS.items():
        lowered = re.sub(rf"\\b{re.escape(src)}\\b", dst, lowered)
    return " ".join(lowered.split())


def score_legend_text_association(
    *,
    legend_text: str,
    nearby_note_text: str = "",
    outlet_definition_text: str = "",
    abbreviation_text: str = "",
) -> float:
    pieces = [
        normalize_semantic_text(legend_text),
        normalize_semantic_text(nearby_note_text),
        normalize_semantic_text(outlet_definition_text),
        normalize_semantic_text(abbreviation_text),
    ]
    joined = " | ".join(p for p in pieces if p)
    if not joined:
        return 0.0
    signal_terms = ["wireless", "camera", "telecom", "data", "voice", "rack", "patch", "reader", "door", "intercom", "runway", "pathway", "riser"]
    hits = sum(1 for t in signal_terms if t in joined)
    return min(1.0, 0.2 + 0.1 * hits)
