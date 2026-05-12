from __future__ import annotations

GLOBAL_NOTE_KEYWORDS = [
    "general note",
    "general notes",
    "keyed note",
    "keyed notes",
    "project requirements",
    "requirements",
    "drawing index",
    "general infrastructure installation notes",
]

def is_strong_global_note(text: str) -> bool:
    lowered = (text or "").lower()
    return any(kw in lowered for kw in GLOBAL_NOTE_KEYWORDS)
