"""Track C — Cross-Authority Consensus Net (CACN).

The novel piece.  For every PM-visible claim (gap, risk, money_mention,
date_mention, quantity_claim, customer_question), CACN finds the
supporting atoms across the envelope graph, groups them by
authority_class, and emits a four-axis confidence ribbon:

    authority_diversity  — # distinct authority classes supporting
    consensus_strength   — rank-weighted support score
    contradiction_count  — # atoms linked via contradicts edges
    confidence_ribbon    — composite 0-1 score, traffic-lit green/yellow/red

The insight: a claim backed by SOW + vendor_quote + transcript (3
distinct authority classes) is MUCH stronger than one backed by 3
emails.  Existing LLM brains don't reason about authority diversity at
all — they treat retrieval atoms as a flat bag.  CACN gives the PM
visibility into this dimension directly.

Architecture differs from the GNN proposal in v46_RISK_PROPAGATION_NET.md
in being TRAIN-FREE.  It uses the parser's pre-computed authority
taxonomy as the supervisor.  Once we have closed-deal labels, this same
output shape can be replaced by a learned ranker — but the API and the
PM-visible columns stay identical.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import replace
from typing import Any, Iterable

from orbitbrief_core.pm_handoff.models import PMHandoff


# Authority-class weights — relative trust contribution per atom.
# contractual_scope = SOW-grade evidence; we weight it highest.
# Email/transcript classes get smaller weight even at high rank because
# the medium is informal.  These weights are calibrated to match parser-os's
# own authority_rank ordering; tune via closed-deal labels later.
AUTHORITY_WEIGHT: dict[str, float] = {
    "contractual_scope": 1.00,
    "approved_site_roster": 0.90,
    "vendor_quote": 0.80,
    "customer_current_authored": 0.75,
    "machine_extractor": 0.65,
    "meeting_note": 0.55,
    "transcript": 0.45,
    "email": 0.35,
    "informal": 0.30,
}


def _safe_dict(v: Any) -> dict:
    return v if isinstance(v, dict) else {}


def _safe_list(v: Any) -> list:
    return v if isinstance(v, list) else []


def _authority_weight(cls: str) -> float:
    return AUTHORITY_WEIGHT.get(cls or "", 0.4)


def _ribbon_color(score: float) -> str:
    if score >= 0.70:
        return "green"
    if score >= 0.40:
        return "yellow"
    return "red"


# ── atom + edge indexes ────────────────────────────────────────────


# Atom ids come on the `id` key (parser-os v45+), `atom_id` in legacy
# fixtures.  Accept both.
def _atom_id_of(a: dict) -> str | None:
    aid = a.get("id") or a.get("atom_id")
    return aid if isinstance(aid, str) else None


def _build_atom_index(envelope: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for a in _safe_list(envelope.get("atoms")):
        if not isinstance(a, dict):
            continue
        aid = _atom_id_of(a)
        if aid:
            out[aid] = a
    return out


# Stopword list — high-frequency English words that match every atom
# and ruin lexical linkage.  Tuned to the SOW/PM domain; kept small so
# adding terms is cheap.
_STOPWORDS = frozenset({
    "the", "and", "for", "with", "from", "this", "that", "have", "are", "was",
    "will", "any", "all", "may", "but", "not", "you", "your", "our", "their",
    "they", "them", "him", "his", "her", "she", "has", "had", "out", "off",
    "per", "into", "onto", "upon", "over", "under", "via",
})


def _tokenize(text: str) -> set[str]:
    """3+ char alphanumeric tokens, lowercased, stopwords removed."""
    if not text:
        return set()
    return {
        t for t in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", text.lower())
        if t not in _STOPWORDS
    }


def _build_text_index(atoms: dict[str, dict]) -> dict[str, list[str]]:
    """Token → atom_ids.  3+ char tokens, stopwords removed.

    Used for lexical claim-to-atom linkage when a claim doesn't carry
    an explicit atom_id.
    """
    idx: dict[str, list[str]] = defaultdict(list)
    for atom_id, atom in atoms.items():
        for tok in _tokenize(atom.get("text") or ""):
            idx[tok].append(atom_id)
    return dict(idx)


def _build_contradiction_index(envelope: dict) -> dict[str, set[str]]:
    """atom_id → set of atoms it contradicts."""
    out: dict[str, set[str]] = defaultdict(set)
    for e in _safe_list(envelope.get("edges")):
        if not isinstance(e, dict):
            continue
        if str(e.get("type") or e.get("edge_type") or "").lower() != "contradicts":
            continue
        src = e.get("from_atom_id") or e.get("src_atom_id") or e.get("src") or e.get("from")
        dst = e.get("to_atom_id") or e.get("dst_atom_id") or e.get("dst") or e.get("to")
        if isinstance(src, str) and isinstance(dst, str):
            out[src].add(dst)
            out[dst].add(src)
    return dict(out)


# ── claim → supporting atoms ───────────────────────────────────────


def _claim_atom_ids(claim: dict, fallback_text: str = "") -> list[str]:
    """Pull explicit atom_ids out of a handoff claim object."""
    out: list[str] = []
    for key in ("supporting_atom_ids", "atom_ids", "source_atom_ids"):
        v = claim.get(key) if isinstance(claim, dict) else None
        if isinstance(v, list):
            out.extend(str(x) for x in v if isinstance(x, str))
    # Also harvest from a `source` pointer if present.
    src = claim.get("source") if isinstance(claim, dict) else None
    if isinstance(src, dict):
        sid = src.get("atom_id")
        if isinstance(sid, str):
            out.append(sid)
    # And from a `citation` field.
    cit = claim.get("citation") if isinstance(claim, dict) else None
    if isinstance(cit, dict):
        sid = cit.get("atom_id")
        if isinstance(sid, str):
            out.append(sid)
    return list(dict.fromkeys(out))  # dedupe, preserve order


def _lexical_link(claim_text: str, text_index: dict[str, list[str]], top_k: int = 12) -> list[str]:
    """Cheap lexical lookup — match discriminating tokens against atom texts.

    Returns up to ``top_k`` atom_ids, ranked by token-overlap count.
    """
    tokens = _tokenize(claim_text)
    if not tokens:
        return []
    counts: Counter = Counter()
    for tok in tokens:
        for aid in text_index.get(tok, [])[:200]:
            counts[aid] += 1
    return [aid for aid, _ in counts.most_common(top_k)]


def _score_supports(
    atoms_idx: dict[str, dict],
    contradict_idx: dict[str, set[str]],
    supporting_atom_ids: list[str],
) -> dict:
    """Compute the four-axis ribbon for a set of supporting atoms."""
    if not supporting_atom_ids:
        return {
            "supporting_atom_ids": [],
            "authority_classes": [],
            "authority_diversity": 0,
            "consensus_strength": 0.0,
            "contradiction_count": 0,
            "confidence_ribbon": 0.0,
            "ribbon_color": "red",
        }
    classes: Counter = Counter()
    total_weight = 0.0
    total_rank = 0.0
    used_ids: list[str] = []
    contradiction_count = 0

    # _RANK_BY_CLASS mirrors scorers.py — authority_class drives an implicit rank
    # when the atom doesn't carry one.
    _RANK_BY_CLASS = {
        "contractual_scope": 90.0, "approved_site_roster": 85.0,
        "vendor_quote": 75.0, "customer_current_authored": 65.0,
        "machine_extractor": 60.0, "meeting_note": 50.0,
        "transcript": 45.0, "email": 40.0, "informal": 30.0,
    }
    for aid in supporting_atom_ids:
        atom = atoms_idx.get(aid)
        if not isinstance(atom, dict):
            continue
        used_ids.append(aid)
        cls = str(atom.get("authority_class") or "")
        classes[cls] += 1
        w = _authority_weight(cls)
        # Per-atom rank or class-derived fallback (parser-os emits class on
        # every atom; rank is implicit via class).
        rank_raw = atom.get("authority_rank")
        rank = (
            float(rank_raw) if isinstance(rank_raw, (int, float))
            else _RANK_BY_CLASS.get(cls, 50.0)
        )
        total_weight += w
        total_rank += rank * w
        contradiction_count += len(contradict_idx.get(aid, set()))

    if not used_ids:
        return {
            "supporting_atom_ids": [],
            "authority_classes": [],
            "authority_diversity": 0,
            "consensus_strength": 0.0,
            "contradiction_count": 0,
            "confidence_ribbon": 0.0,
            "ribbon_color": "red",
        }

    # Diversity: count of distinct authority classes (capped at 6).
    diversity = len(classes)
    # Strength: rank-weighted average authority_rank, normalised to 0-1.
    avg_rank = total_rank / max(total_weight, 1e-6)
    strength = min(avg_rank / 100.0, 1.0)
    # Ribbon: log-scaled diversity (so going from 1 → 2 classes is a bigger
    # bump than 4 → 5) combined with strength, penalised by contradictions.
    import math
    diversity_score = math.log(1 + diversity) / math.log(1 + 4)  # 4-class ≈ 1.0
    diversity_score = min(diversity_score, 1.0)
    ribbon = 0.6 * strength + 0.4 * diversity_score
    if contradiction_count:
        ribbon *= max(0.4, 1.0 - 0.15 * contradiction_count)
    ribbon = max(0.0, min(ribbon, 1.0))

    return {
        "supporting_atom_ids": used_ids[:20],
        "authority_classes": sorted(classes),
        "authority_class_counts": dict(classes),
        "authority_diversity": diversity,
        "consensus_strength": round(strength, 3),
        "contradiction_count": contradiction_count,
        "confidence_ribbon": round(ribbon, 3),
        "ribbon_color": _ribbon_color(ribbon),
    }


# ── per-claim-type linkage ─────────────────────────────────────────


def _gather_claim_text(claim: dict, text_keys: Iterable[str]) -> str:
    """Walk the claim object and harvest every text-bearing field.

    Handles nested ``sources[].snippet`` arrays which are how money/date
    mentions carry their evidence text.  Concatenates everything so the
    lexical linker has more tokens to match against.
    """
    parts: list[str] = []
    for k in text_keys:
        v = claim.get(k)
        if isinstance(v, str) and v.strip():
            parts.append(v)
        elif isinstance(v, (int, float)):
            # money values like 1847250 — stringify so the lexer sees them.
            parts.append(str(v))
    # Nested sources[].snippet / .text — common shape for money & date mentions.
    for nested_key in ("sources", "evidence", "citations"):
        nested = claim.get(nested_key)
        if isinstance(nested, list):
            for s in nested:
                if isinstance(s, dict):
                    for k in ("snippet", "text", "excerpt"):
                        sv = s.get(k)
                        if isinstance(sv, str) and sv.strip():
                            parts.append(sv)
    return " ".join(parts)


def _link_claim(
    claim: dict,
    *,
    atoms_idx: dict[str, dict],
    text_index: dict[str, list[str]],
    contradict_idx: dict[str, set[str]],
    text_keys: Iterable[str] = ("text", "message", "description", "label", "snippet"),
) -> dict:
    """Resolve a handoff claim → supporting atom set → ribbon."""
    explicit = _claim_atom_ids(claim)
    if explicit:
        # Trust explicit citations over lexical guess.
        return _score_supports(atoms_idx, contradict_idx, explicit)
    # Lexical fallback over every text-bearing field including nested sources.
    fallback_text = _gather_claim_text(claim, text_keys)
    lex = _lexical_link(fallback_text, text_index)
    return _score_supports(atoms_idx, contradict_idx, lex)


def _score_claim_list(
    claims: list,
    atoms_idx: dict[str, dict],
    text_index: dict[str, list[str]],
    contradict_idx: dict[str, set[str]],
    text_keys: tuple[str, ...] = ("text", "message", "description", "label", "snippet"),
) -> list[dict]:
    out: list[dict] = []
    for c in claims or []:
        if not isinstance(c, dict):
            out.append({"confidence_ribbon": 0.0, "ribbon_color": "red", "supporting_atom_ids": []})
            continue
        ribbon = _link_claim(c, atoms_idx=atoms_idx, text_index=text_index,
                              contradict_idx=contradict_idx, text_keys=text_keys)
        # Carry a stable identifier so the UI can join the consensus row
        # back to the original claim list by position OR by id.
        ribbon["claim_id"] = c.get("rule_id") or c.get("id") or c.get("internal_id") or c.get("title")
        out.append(ribbon)
    return out


# ── orchestration ──────────────────────────────────────────────────


def apply_claim_consensus(handoff: PMHandoff, envelope: dict) -> PMHandoff:
    """Annotate handoff with per-claim confidence ribbons.

    Reads from the handoff's existing claim lists (gaps, risk_register,
    money_mentions, date_mentions, quantity_claims, customer_questions)
    so the consensus output stays positionally aligned with the source
    lists — UI can render side-by-side.
    """
    if not isinstance(envelope, dict):
        return handoff

    atoms_idx = _build_atom_index(envelope)
    text_index = _build_text_index(atoms_idx)
    contradict_idx = _build_contradiction_index(envelope)

    h = handoff.to_dict()

    gaps = _score_claim_list(
        [g for g in h.get("gaps", [])], atoms_idx, text_index, contradict_idx,
        text_keys=("message", "suggested_open_question", "observed_summary", "label"),
    )
    customer_questions = _score_claim_list(
        [g for g in h.get("customer_questions", [])], atoms_idx, text_index, contradict_idx,
        text_keys=("message", "suggested_open_question", "observed_summary", "label"),
    )
    risks = _score_claim_list(
        h.get("risk_register", []), atoms_idx, text_index, contradict_idx,
        text_keys=("description", "summary", "title"),
    )
    # Money/date/quantity claims carry evidence in nested sources[].snippet
    # — _gather_claim_text walks those for us.  Also include 'value' and
    # 'display' so dollar amounts get tokenised.
    money = _score_claim_list(
        h.get("money_mentions", []), atoms_idx, text_index, contradict_idx,
        text_keys=("text", "label", "display", "value"),
    )
    dates = _score_claim_list(
        h.get("date_mentions", []), atoms_idx, text_index, contradict_idx,
        text_keys=("text", "label", "iso", "display"),
    )
    qty = _score_claim_list(
        h.get("quantity_claims", []), atoms_idx, text_index, contradict_idx,
        text_keys=("snippet", "text", "label", "target", "device", "display"),
    )

    all_ribbons = gaps + customer_questions + risks + money + dates + qty
    ribbon_scores = [r.get("confidence_ribbon", 0.0) for r in all_ribbons]
    by_color: Counter = Counter(r.get("ribbon_color", "red") for r in all_ribbons)

    summary = {
        "total_claims_scored": len(all_ribbons),
        "avg_confidence_ribbon": (
            round(sum(ribbon_scores) / len(ribbon_scores), 3)
            if ribbon_scores else 0.0
        ),
        "by_ribbon_color": dict(by_color),
        "weights": dict(AUTHORITY_WEIGHT),
    }

    return replace(
        handoff,
        claim_consensus={
            "version": "v46.1-cacn",
            "gaps": gaps,
            "customer_questions": customer_questions,
            "risks": risks,
            "money_mentions": money,
            "date_mentions": dates,
            "quantity_claims": qty,
            "summary": summary,
        },
    )
