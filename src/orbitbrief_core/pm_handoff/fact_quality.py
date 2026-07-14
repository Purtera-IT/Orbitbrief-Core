"""Neural project-fact gate for PM-visible evidence cards.

Stops conversation filler (greetings, soft prompts) from landing in
commercial / scope fact lanes when typed as ``deal_metadata``.
"""
from __future__ import annotations

import os
import re
from typing import Any, Mapping, Sequence

from orbitbrief_core.pm_handoff.semantic_dedupe import (
    cosine_similarity,
    resolve_question_embedder,
)
from orbitbrief_core.retrieval.embedder import DeterministicHashEmbedder

# Minimum (fact_proto − filler_proto) cosine margin to keep an atom as a fact.
FACT_MARGIN = float(os.environ.get("ORBITBRIEF_FACT_NEURAL_MARGIN", "0.04"))

_FACT_PROTOTYPES: tuple[str, ...] = (
    "Project evidence: commercial terms payment pricing CDW paper PO NTE fee quote approval authority",
    "Project evidence: physical site address office location circuit carrier Meraki MX BOM quantity",
    "Project evidence: SOP runbook POC smart hands remote hands install scope schedule milestone",
    "Project evidence: stakeholder owner signatory customer decision scope exclusion constraint risk",
)

_FILLER_PROTOTYPES: tuple[str, ...] = (
    "Conversation filler greeting: how you doing how are you guys doing well weekend plans volleyball",
    "Conversation filler soft prompt with no deal content: what are your thoughts you know what I mean who knows",
    "Conversation filler screen share smalltalk: seeing my screen what about you olympian last name",
)

_LEXICAL_FILLER_RE = re.compile(
    r"(?i)^(?:"
    r"(?:so|and|but|well|yeah|ok|okay|um+|uh+|i\s+mean)[, ]+)?"
    r"(?:(?:nick|chase|quinton|trent|hey)[, ]+)?"
    r"(?:how(?:'s| is| are)?\s+you(?:r)?(?:\s+guys)?(?:\s+doing)?|"
    r"you\s+guys\s+doing\s+well|"
    r"any\s+big\s+plans|"
    r"what\s+about\s+you|"
    r"who\s+knows|"
    r"(?:i\s+mean[, ]+)?what\s+are\s+your\s+thoughts(?:\s+on\s+that)?|"
    r"you\s+know\s+what\s+i\s+mean|"
    r"seeing\s+my\s+screen|"
    r"volleyball|"
    r"good\s+morning|good\s+afternoon|"
    r"how(?:'s|\s+is|\s+are)\s+it\s+going"
    r")[\s\?\!\.]*$"
)

_COMMERCIAL_SUBSTANCE_RE = re.compile(
    r"(?i)\b("
    r"price|pricing|payment|invoice|po\b|purchase\s+order|nte|not\s+to\s+exceed|"
    r"fixed\s+fee|t\s*&\s*m|time\s+and\s+materials|margin|discount|quote|"
    r"cdw\s+(?:us\s+)?paper|us\s+paper|change\s+order|msa|sow\b|commercial|"
    r"per[\-\s]?site\s+(?:fee|rate|charge)|survey\s+charge|bill(?:ing|able)"
    r")\b"
)

_DEAL_SUBSTANCE_RE = re.compile(
    r"(?i)\b("
    r"site|office|address|circuit|meraki|mx\b|sd[\-\s]?wan|sop|poc|"
    r"smart\s+hands|remote\s+hands|bom|device|install|survey|walkthrough|"
    r"montreal|canada|maitland|carrier|topology|config(?:uration)?|"
    r"approval|paper|quote|schedule|milestone|scope|rack|stack"
    r")\b"
)

_STRUCTURED_KEEP = frozenset(
    {
        "physical_site",
        "bom_line",
        "site_allocation",
        "decision",
        "risk",
        "action_item",
        "constraint",
        "milestone_phase",
        "scope_item",
    }
)


def _atom_text(atom: Mapping[str, Any] | Any) -> str:
    if isinstance(atom, Mapping):
        for key in ("text", "raw_text", "normalized_text", "claim"):
            val = atom.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        value = atom.get("value")
        if isinstance(value, Mapping):
            for key in ("text", "claim", "summary"):
                val = value.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
        return ""
    for attr in ("text", "raw_text", "normalized_text"):
        val = getattr(atom, attr, None)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _atom_type(atom: Mapping[str, Any] | Any) -> str:
    if isinstance(atom, Mapping):
        return str(atom.get("atom_type") or "").lower()
    at = getattr(atom, "atom_type", None)
    return str(getattr(at, "value", at) or "").lower()


def _atom_payload(atom: Mapping[str, Any] | Any) -> Mapping[str, Any]:
    """Parser puts conversation_meta flags on ``value`` or ``structured``."""
    if isinstance(atom, Mapping):
        for key in ("value", "structured"):
            val = atom.get(key)
            if isinstance(val, Mapping) and val:
                return val
        return {}
    for attr in ("value", "structured"):
        val = getattr(atom, attr, None)
        if isinstance(val, Mapping) and val:
            return val
    return {}


def _payload_role_kind(atom: Mapping[str, Any] | Any) -> tuple[str, str]:
    payload = _atom_payload(atom)
    return (
        str(payload.get("role") or "").lower(),
        str(payload.get("kind") or "").lower(),
    )


def is_marked_conversation_meta(atom: Mapping[str, Any] | Any) -> bool:
    """True when parser tagged the atom as non-deal chat (may still carry facts)."""
    payload = _atom_payload(atom)
    role, kind = _payload_role_kind(atom)
    if kind in {"conversation_meta", "smalltalk", "filler", "greeting"}:
        return True
    if role in {"filler", "greeting", "smalltalk", "soft_prompt"}:
        return True
    if payload.get("non_deal") or payload.get("head_exclude"):
        return True
    if isinstance(atom, Mapping):
        flags = list(atom.get("review_flags") or [])
        atype = str(atom.get("atom_type") or "").lower()
    else:
        flags = list(getattr(atom, "review_flags", None) or [])
        at = getattr(atom, "atom_type", None)
        atype = str(getattr(at, "value", at) or "").lower()
    if atype in {"conversation_meta", "smalltalk"}:
        return True
    return "conversation_meta" in {str(f).lower() for f in flags}


def is_hard_conversation_filler(atom: Mapping[str, Any] | Any, text: str) -> bool:
    """Drop-only: greetings / soft prompts. Do not drop substance-bearing soft commits."""
    role, kind = _payload_role_kind(atom)
    if role in {"greeting", "smalltalk", "soft_prompt"}:
        return True
    if kind in {"greeting", "smalltalk"}:
        return True
    if is_lexical_conversation_filler(text):
        return True
    # Parser marks many soft commitments as conversation_meta/filler; keep those
    # that still carry deal substance for the neural / substance path.
    if is_marked_conversation_meta(atom) and not (
        deal_substance(text) or commercial_substance(text)
    ):
        return True
    return False


def is_lexical_conversation_filler(text: str) -> bool:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return True
    if _LEXICAL_FILLER_RE.match(t):
        return True
    # Soft prompts / greetings with optional leading discourse marker.
    if re.search(
        r"(?i)^(?:so|and|but|well|yeah|ok|okay|um+|uh+)[, ]+"
        r"(?:what\s+are\s+your\s+thoughts|how\s+(?:are\s+)?you(?:\s+doing)?)\b",
        t,
    ):
        return True
    if len(t) < 56 and t.endswith("?") and not _DEAL_SUBSTANCE_RE.search(t):
        if re.search(r"(?i)\b(how|what|who|where|why)\b", t):
            return True
    return False


def commercial_substance(text: str) -> bool:
    return bool(_COMMERCIAL_SUBSTANCE_RE.search(text or ""))


def deal_substance(text: str) -> bool:
    return bool(_DEAL_SUBSTANCE_RE.search(text or ""))


def neural_fact_scores(
    texts: Sequence[str],
    *,
    embedder=None,
) -> tuple[list[float], str]:
    """Return fact−filler margin per text (higher ⇒ more project-fact-like)."""
    emb = resolve_question_embedder(embedder)
    if not texts:
        return [], emb.model_id
    corpus = [*_FACT_PROTOTYPES, *_FILLER_PROTOTYPES, *[t or "" for t in texts]]
    try:
        vecs = emb.embed(list(corpus))
    except Exception:
        emb = DeterministicHashEmbedder(dim=256)
        vecs = emb.embed(list(corpus))
    n_fact = len(_FACT_PROTOTYPES)
    n_fill = len(_FILLER_PROTOTYPES)
    fact_vecs = vecs[:n_fact]
    fill_vecs = vecs[n_fact : n_fact + n_fill]
    out: list[float] = []
    for i in range(len(texts)):
        tv = vecs[n_fact + n_fill + i]
        best_fact = max(cosine_similarity(tv, fv) for fv in fact_vecs)
        best_fill = max(cosine_similarity(tv, fv) for fv in fill_vecs)
        out.append(best_fact - best_fill)
    return out, emb.model_id


def filter_pm_visible_atoms(
    atoms: Sequence[Mapping[str, Any] | Any],
    *,
    embedder=None,
) -> tuple[list[Any], dict[str, Any]]:
    """Batch-filter atoms for fact cards; returns (kept, debug meta)."""
    if not atoms:
        return [], {
            "fact_quality_input": 0,
            "fact_quality_kept": 0,
            "fact_quality_dropped_pre": 0,
            "fact_quality_dropped_neural": 0,
            "fact_quality_embedder": "none",
            "fact_quality_margin": FACT_MARGIN,
            "fact_quality_neural": False,
        }

    hard_keep: list[Any] = []
    judge: list[tuple[Any, str]] = []
    dropped_pre = 0

    for atom in atoms:
        text = _atom_text(atom)
        if len(text.strip()) < 8 or is_hard_conversation_filler(atom, text):
            dropped_pre += 1
            continue
        atype = _atom_type(atom)
        if atype in _STRUCTURED_KEEP:
            hard_keep.append(atom)
            continue
        if atype == "open_question" and (deal_substance(text) or commercial_substance(text)):
            hard_keep.append(atom)
            continue
        # Substance-bearing soft commits: keep without neural (hash embedder is weak).
        if deal_substance(text) or commercial_substance(text):
            hard_keep.append(atom)
            continue
        # deal_metadata and weak misc types → neural judge
        judge.append((atom, text))

    scores: list[float] = []
    model_id = "skipped"
    if judge:
        scores, model_id = neural_fact_scores([t for _, t in judge], embedder=embedder)

    neural = "deterministic-hash" not in (model_id or "").lower() and model_id != "skipped"
    kept: list[Any] = list(hard_keep)
    dropped_neural = 0
    for (atom, text), score in zip(judge, scores or []):
        if neural:
            ok = score >= FACT_MARGIN
        else:
            ok = deal_substance(text) or commercial_substance(text)
        if ok:
            kept.append(atom)
        else:
            dropped_neural += 1

    meta = {
        "fact_quality_input": len(atoms),
        "fact_quality_kept": len(kept),
        "fact_quality_dropped_pre": dropped_pre,
        "fact_quality_dropped_neural": dropped_neural,
        "fact_quality_embedder": model_id,
        "fact_quality_margin": FACT_MARGIN,
        "fact_quality_neural": neural,
    }
    return kept, meta
