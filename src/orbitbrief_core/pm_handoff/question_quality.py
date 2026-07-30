"""Hard quality gate for curated customer questions / evidence pool.

A question ships only when it is:
  - an open decision (interrogative or Confirm/Which/Who stem)
  - evidence-grounded (≥1 real source with filename + snippet)
  - not junk (table rows, smalltalk, meta, self-cite only)
  - not a Confirm-paste of SOW/email prose
  - sharp enough that a PM would actually ask it
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from orbitbrief_core.pm_handoff.models import GapCard

_DECISION_STEM = re.compile(
    r"^(?:confirm|decide|clarify|which|who|what|when|where|how|is\s+it|are\s+we|"
    r"can\s+we|do\s+we|does|should|need\s+to\s+know|include|lock)\b",
    re.I,
)
_JUNK_RE = re.compile(
    r"(?i)(?:"
    r"big\s+plans\s+for\s+the\s+weekend|"
    r"why\s+do\s+you\s+chase|"
    r"you\s+know\s+what\s+i\s+mean|"
    r"biggest\s+point\s+of\s+emphasis|"
    r"rhyme\s+or\s+reason|"
    r"atom_type\s*=|"
    r"kind\s*=\s*physical_site|"
    r"urldefense\.proofpoint|"
    r"mimecast|"
    r"regarding\s+this\s+engagement\??\s*$|"
    r"^\s*risks?\s*:"
    r")"
)
_TABLE_ROW_RE = re.compile(r"\|.+\|.+\|")
_RISK_ID_ROW_RE = re.compile(r"\|\s*r\d+\s*\|", re.I)

# Lazy Confirm-wrap of raw atom text — banned. Generators must rewrite.
_PASTE_PREFIX_RE = re.compile(
    r"(?i)^confirm\s+(?:"
    r"customer\s+instruction|"
    r"pricing\s+assumption\s+is\s+still\s+valid|"
    r"this\s+is\s+in-scope\s+for\s+the\s+quote|"
    r"this\s+requirement\s+is\s+binding(?:\s+for\s+the\s+quote)?|"
    r"how\s+this\s+risk\s+is\s+handled(?:\s+in\s+the\s+quote\s*/?\s*sow)?|"
    r"bom\s+line\s+is\s+in\s+this\s+quote\s+as\s+written|"
    r"this\s+deliverable\s+is\s+included\s+in\s+the\s+quote|"
    r"this\s+task\s+is\s+in-scope\s+and\s+scheduled|"
    r"this\s+exclusion\s+stands\s+as\s+written|"
    r"acceptance\s+criterion\s+for\s+delivery|"
    r"commercial\s+term\s+is\s+accepted\s+for\s+this\s+quote|"
    r"keyed-note\s+scope\s+is\s+in\s+quote"
    r")\s*:\s*"
)

_EMAIL_CHROME_RE = re.compile(
    r"(?i)(?:"
    r"hope\s+(?:you(?:'re|\s+are)?|my\s+email)|"
    r"great\s+start\s+to\s+the\s+week|"
    r"don'?t\s+hesitate|"
    r"thank\s+you\s+so\s+much|"
    r"looking\s+forward|"
    r"best\s+regards|"
    r"kind\s+regards|"
    r"draw\s+up\s+a\s+quote|"
    r"could\s+you\s+please\s+draw\s+up|"
    r"i\s+hope\s+this\s+(?:email|note)|"
    r"excited\s+(?:to|about)|"
    r"chat\s+tomorrow"
    r")"
)

_BOILERPLATE_RE = re.compile(
    r"(?i)(?:"
    r"material\s+breach|"
    r"terminate\s+this\s+(?:sow|agreement)|"
    r"either\s+party\s+may\s+terminate|"
    r"form\s+w-?9|"
    r"indemnif|"
    r"governing\s+law|"
    r"force\s+majeure"
    r")"
)

# Sharp asks have a choice, owner, or concrete lock — not a prose dump.
_SHARP_RE = re.compile(
    r"(?i)(?:"
    r"\bvs\.?\b|\bversus\b|\bor\b|\bwhich\b|\bwho\b|\bwhat\b|\bwhen\b|\bwhere\b|"
    r"\bhow\s+many\b|\bin[\-\s]?scope\b|\bout\s+of\s+scope\b|"
    r"\bofe\b|\bcustomer[\-\s]?furnish|\bpurtera[\-\s]?furnish|"
    r"\bkeep\b|\bremove\b|\breuse\b|\bdefer\b|\bapprove\b|\block\b|"
    r"\binclude\b|\bexclude\b|\bauthoritative\b|\bpass/fail\b|"
    r"\braceway\b|\bin[\-\s]?wall\b|\bhome\s+runs?\b|"
    r"\?$"
    r")"
)


@dataclass(frozen=True)
class QualityViolation:
    rule_id: str
    code: str
    detail: str


def _qtext(card: GapCard | Mapping[str, Any]) -> str:
    if isinstance(card, GapCard):
        return (card.suggested_open_question or card.message or "").strip()
    return str(card.get("suggested_open_question") or card.get("message") or "").strip()


def _sources(card: GapCard | Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if isinstance(card, GapCard):
        return list(card.sources or [])
    raw = card.get("sources") or card.get("evidence_sources") or []
    return [s for s in raw if isinstance(s, Mapping)]


def _rule_id(card: GapCard | Mapping[str, Any]) -> str:
    if isinstance(card, GapCard):
        return card.rule_id
    return str(card.get("rule_id") or "")


def validate_question_card(card: GapCard | Mapping[str, Any]) -> list[QualityViolation]:
    """Return violations for one card (empty = perfect)."""
    rid = _rule_id(card)
    text = _qtext(card)
    out: list[QualityViolation] = []
    if len(text) < 18:
        out.append(QualityViolation(rid, "too_short", text[:80]))
    if len(text) > 200:
        out.append(QualityViolation(rid, "too_long", text[:120]))
    if _JUNK_RE.search(text):
        out.append(QualityViolation(rid, "junk_phrase", text[:120]))
    if _EMAIL_CHROME_RE.search(text):
        out.append(QualityViolation(rid, "email_chrome", text[:120]))
    if _BOILERPLATE_RE.search(text):
        out.append(QualityViolation(rid, "boilerplate", text[:120]))
    if _PASTE_PREFIX_RE.search(text):
        out.append(QualityViolation(rid, "confirm_paste", text[:120]))
    if text.count("|") >= 3 or _TABLE_ROW_RE.search(text) or _RISK_ID_ROW_RE.search(text):
        out.append(QualityViolation(rid, "table_row", text[:120]))
    if "?" not in text and not _DECISION_STEM.search(text):
        out.append(QualityViolation(rid, "not_decision", text[:120]))
    # Soft sharpness: long Confirm without choice/owner language is a dump.
    if len(text) > 110 and not _SHARP_RE.search(text):
        out.append(QualityViolation(rid, "not_sharp", text[:120]))
    # Quoted-anchor Confirm still OK; bare multi-sentence paste after Confirm is not.
    if text.lower().startswith("confirm ") and text.count(".") >= 2 and "?" not in text:
        out.append(QualityViolation(rid, "prose_dump", text[:120]))

    sources = _sources(card)
    if not sources:
        # PM gold is allowed without cites (authored by human).
        if not rid.startswith("pm_gold"):
            out.append(QualityViolation(rid, "no_evidence", "missing sources"))
    else:
        good = 0
        for s in sources:
            fn = str(s.get("filename") or s.get("source") or "").strip()
            snip = str(s.get("snippet") or s.get("quote") or s.get("text") or "").strip()
            # Accept locator-only cites from schematics (page/sheet) when filename missing
            locator = str(s.get("locator") or "").strip()
            if len(snip) < 12:
                continue
            if not fn and not locator:
                continue
            # True self-cite: snippet == question with no distinct locator/filename
            snip_norm = re.sub(r"\W+", " ", snip.lower()).strip()
            q_norm = re.sub(r"\W+", " ", text.lower()).strip()
            if (
                snip_norm
                and q_norm
                and snip_norm == q_norm
                and not fn
                and not locator
            ):
                continue
            good += 1
        if good == 0 and not rid.startswith("pm_gold"):
            out.append(QualityViolation(rid, "weak_evidence", "no usable filename+snippet"))
    return out


def filter_perfect_questions(
    cards: Iterable[GapCard],
) -> tuple[list[GapCard], list[QualityViolation]]:
    """Keep only cards with zero violations."""
    kept: list[GapCard] = []
    dropped: list[QualityViolation] = []
    for c in cards:
        viols = validate_question_card(c)
        if viols:
            dropped.extend(viols)
            continue
        kept.append(c)
    return kept, dropped


def pool_scorecard(cards: Iterable[GapCard | Mapping[str, Any]]) -> dict[str, Any]:
    cards_list = list(cards)
    perfect = 0
    by_code: dict[str, int] = {}
    for c in cards_list:
        viols = validate_question_card(c)
        if not viols:
            perfect += 1
            continue
        for v in viols:
            by_code[v.code] = by_code.get(v.code, 0) + 1
    return {
        "total": len(cards_list),
        "perfect": perfect,
        "imperfect": len(cards_list) - perfect,
        "violation_codes": by_code,
        "grade": "A++++++" if perfect >= 50 else ("A+" if perfect >= 30 else ("B" if perfect >= 15 else "F")),
    }
