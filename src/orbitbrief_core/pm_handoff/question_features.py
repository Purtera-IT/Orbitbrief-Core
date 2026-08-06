"""Structural features for the question-quality head's fallback model.

Must stay byte-identical in behaviour to the training-time extractor, or the
fallback weights are meaningless. Hashed lexical n-grams are deliberately absent:
they measurably *overfit* — including them scored worse on held-out deals than
dropping them — so the trained artifact carries no lexical weights either.
"""

from __future__ import annotations

import re

_QUOTED_SPAN_RE = re.compile(r'"([^"]{6,})"')
_BULLET_RE = re.compile(r"[•·●▪]")
_LEGAL_RE = re.compile(
    r"(?i)\b(terminat|indemnif|warrant|liabilit|governing law|dispute|"
    r"confidential|net\s*\d{2}\b|purchase order (?:terms|number)|"
    r"insurance|force majeure|assignment|severab)"
)
_RFP_BOILER_RE = re.compile(
    r"(?i)\b(?:the\s+)?(?:selected\s+)?(?:vendor|contractor|bidder|supplier)\s+"
    r"(?:shall|must|will)\b"
)
_INTERNAL_STEM_RE = re.compile(
    r"(?i)(which quote wave includes|remain in fixed fee|move to t&m|"
    r"include as written,\s*defer,\s*or remove|who owns delivery of)"
)
_DANGLING_RE = re.compile(r"(?i)\b(and|or|with|for|to|of|the|a|an|in|on|per|that)$")
_WORD_RE = re.compile(r"[a-z0-9']+")
_VERB_RE = re.compile(r"(?i)\b(is|are|shall|will|provide|install|be)\b")
_UNIT_RE = re.compile(r"(?i)\b(cat6|cat5e|rj45|poe|watt|volt|ft|inch|\")\b")
_MODEL_TOKEN_RE = re.compile(r"[A-Z]{2,}[- ]?\d{2,}")
_PAREN_QTY_RE = re.compile(r"\(\s*\d+\s*\)")


def rule_family(rule_id: str) -> str:
    parts = (rule_id or "?").split(".")
    return ".".join(parts[:2]) if len(parts) > 1 else (rule_id or "?")


def extract_features(
    *,
    question: str,
    rule_id: str = "",
    severity: str = "",
    sources: list | None = None,
    observed: str = "",
) -> dict:
    """Sparse {feature_name: value} map for one question card."""
    q = question or ""
    low = q.lower()
    feats: dict[str, float] = {"__bias__": 1.0}

    feats["len_chars"] = min(len(q), 300) / 300.0
    words = _WORD_RE.findall(low)
    feats["len_words"] = min(len(words), 60) / 60.0
    feats["has_qmark"] = 1.0 if "?" in q else 0.0
    feats["n_dashes"] = min(q.count("—"), 6) / 6.0
    feats["n_commas"] = min(q.count(","), 8) / 8.0

    srcs = sources or []
    feats["n_sources"] = min(len(srcs), 5) / 5.0
    snippet_len = 0
    for s in srcs[:5]:
        if isinstance(s, dict):
            snippet_len += len(str(s.get("quote") or s.get("snippet") or s.get("text") or ""))
    feats["evidence_len"] = min(snippet_len, 800) / 800.0
    feats["observed_len"] = min(len(observed or ""), 400) / 400.0

    m = _QUOTED_SPAN_RE.search(q)
    feats["has_quote"] = 1.0 if m else 0.0
    if m:
        frag = m.group(1).strip()
        feats["quote_len"] = min(len(frag), 160) / 160.0
        feats["quote_bullets"] = 1.0 if _BULLET_RE.search(frag) else 0.0
        feats["quote_legal"] = 1.0 if _LEGAL_RE.search(frag) else 0.0
        feats["quote_rfp"] = 1.0 if _RFP_BOILER_RE.search(frag) else 0.0
        feats["quote_lower_start"] = 1.0 if frag[:1].islower() else 0.0
        feats["quote_punct_start"] = 1.0 if frag[:1] in ",;:-–—/&" else 0.0
        feats["quote_dangling_end"] = 1.0 if _DANGLING_RE.search(frag) else 0.0
        feats["quote_no_verb"] = 0.0 if _VERB_RE.search(frag) else 1.0

    feats["internal_stem"] = 1.0 if _INTERNAL_STEM_RE.search(q) else 0.0
    feats["starts_confirm"] = 1.0 if low.startswith("confirm") else 0.0
    feats["starts_who"] = 1.0 if low.startswith("who") else 0.0
    feats["starts_what"] = 1.0 if low.startswith("what") else 0.0
    feats["starts_which"] = 1.0 if low.startswith("which") else 0.0

    # Deal-specificity: a generic template carries no numbers, a real ask names
    # a quantity, a model, or a unit.
    feats["has_digit"] = 1.0 if re.search(r"\d", q) else 0.0
    feats["has_paren_qty"] = 1.0 if _PAREN_QTY_RE.search(q) else 0.0
    feats["has_model_token"] = 1.0 if _MODEL_TOKEN_RE.search(q) else 0.0
    feats["has_unit"] = 1.0 if _UNIT_RE.search(q) else 0.0

    feats[f"fam={rule_family(rule_id)}"] = 1.0
    feats[f"sev={severity or '?'}"] = 1.0
    return feats
