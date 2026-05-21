"""Retrieval — top-K nearest past deals.

Pure-Python scoring. No vector DB needed for the first ~500 deals.
Above that, swap the ``score_deal`` function for an embedding-based
retriever (the rest of the API stays identical).

Scoring blends:

* **Domain overlap** — count of shared active domain packs
* **Deal value distance** — log-scale (so a $50K deal isn't compared to a $5M deal)
* **Same-quarter recency** — small boost for deals closed in the last 90d
* **Outcome bias** — won deals weighted higher than lost (since they're the patterns to repeat)

Returns are ordered best-match-first.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from orbitbrief_core.learning.learning_ledger import (
    LearningLedger,
    LearningRecord,
)


@dataclass(frozen=True)
class RetrievalHit:
    """One past deal retrieved as a similarity match."""

    record: LearningRecord
    score: float                                     # lower = closer
    rationale: str                                   # human-readable why


def _value_distance(target_usd: int, candidate_usd: int) -> float:
    """Log-scale distance. Returns ``10.0`` when either value is missing
    (so deals with no recorded value never dominate the rankings)."""
    if target_usd <= 0 or candidate_usd <= 0:
        return 10.0
    return abs(math.log(candidate_usd) - math.log(target_usd))


def _recency_boost(closed_at: str) -> float:
    """Negative score adjustment for recent deals (last 90 days)."""
    if not closed_at:
        return 0.0
    try:
        when = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
    except ValueError:
        return 0.0
    days = (datetime.now(timezone.utc) - when).days
    if days < 0:
        return 0.0
    if days <= 90:
        return -0.25
    if days <= 180:
        return -0.1
    return 0.0


def _outcome_bias(outcome: str) -> float:
    """Won deals slight boost (we want to repeat their patterns)."""
    if outcome == "won":
        return -0.3
    if outcome == "lost":
        return -0.1                              # still useful — patterns to avoid
    return 0.0


def score_deal(
    candidate: LearningRecord,
    *,
    target_domains: set[str],
    target_value_usd: int,
) -> tuple[float, str]:
    """Score a candidate against the target. Lower is closer."""
    overlap = len(target_domains & set(candidate.domains))
    overlap_term = -0.5 * overlap                    # more overlap → lower (better)
    vdist = _value_distance(target_value_usd, candidate.deal_value_usd)
    recency = _recency_boost(candidate.closed_at)
    outcome = _outcome_bias(candidate.outcome)
    score = vdist + overlap_term + recency + outcome
    rationale_bits: list[str] = []
    if overlap:
        rationale_bits.append(f"{overlap} domain overlap")
    if vdist < 1.0:
        rationale_bits.append(f"within {vdist:.1f} log-USD")
    if recency < 0:
        rationale_bits.append("recent")
    if candidate.outcome:
        rationale_bits.append(f"outcome={candidate.outcome}")
    rationale = " · ".join(rationale_bits) or "weak match"
    return score, rationale


def retrieve_similar_deals(
    *,
    target_domains: list[str],
    target_value_usd: int = 0,
    ledger_path: Path | str | None = None,
    limit: int = 5,
    exclude_case_ids: list[str] | None = None,
) -> list[RetrievalHit]:
    """Return top-K most similar past deals.

    Returns ``[]`` when the ledger is empty (cold start). Caller
    should gracefully degrade — UI shows "no comparable deals yet."
    """
    if ledger_path is None:
        ledger = LearningLedger.at(out_dir=None)
    else:
        ledger = LearningLedger(path=Path(ledger_path))

    exclude_set = set(exclude_case_ids or [])
    targets_set = set(target_domains or [])

    hits: list[RetrievalHit] = []
    for rec in ledger.all():
        if rec.case_id in exclude_set:
            continue
        score, rationale = score_deal(
            rec,
            target_domains=targets_set,
            target_value_usd=target_value_usd,
        )
        hits.append(RetrievalHit(record=rec, score=score, rationale=rationale))

    hits.sort(key=lambda h: h.score)
    return hits[:limit]


# ──────────────────────────────────────────────────────────────────
# Prompt-injection helper — formats retrieval hits for a brain prompt
# ──────────────────────────────────────────────────────────────────


def format_for_brain_prompt(hits: list[RetrievalHit]) -> str:
    """Render hits as a 'past patterns' block for a brain prompt.

    Empty result when ``hits`` is empty (cold-start safe).
    """
    if not hits:
        return ""
    lines: list[str] = [
        f"PAST PATTERNS (from {len(hits)} similar closed deals):",
        "",
    ]
    for h in hits:
        r = h.record
        marker = "[won]" if r.outcome == "won" else ("[lost]" if r.outcome == "lost" else "[----]")
        lines.append(
            f"  {marker} {r.case_id} | {r.closed_at} | "
            f"${r.deal_value_usd:,} | margin {r.final_margin_pct:.1f}% | "
            f"{', '.join(r.domains) or 'no domains'}"
        )
        if r.top_gap_rule_ids:
            common = ", ".join(r.top_gap_rule_ids[:5])
            lines.append(f"      gaps that fired: {common}")
        if r.reconciliation_kinds:
            lines.append(
                f"      reconciliation flags: {', '.join(r.reconciliation_kinds[:3])}"
            )
        if r.post_mortem:
            lines.append(f"      post-mortem: {r.post_mortem[:160]}")
        lines.append("")

    lines.append(
        "Use these as anchors. Do not invent — only surface a pattern if at "
        "least 2 of the retrieved deals confirm it."
    )
    return "\n".join(lines)
