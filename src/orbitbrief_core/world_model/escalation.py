"""Structured escalation logging.

Every LLM call inside the world_model goes through an
:class:`EscalationLog`, never a raw client call. That gives us:

* A single structured place to enforce the < 20 % LLM-call cap
  across the corpus (Phase-3 verify gate).
* Audit trail: per-engine, per-reason counts surfaced in the
  state objects so reviewers can see *why* a model was consulted.
* A clean test seam — fakes can plug an :class:`EscalationLog`
  without a real chat client.

The log is a per-state object (not a global singleton) so two
engines on the same envelope can have independent escalation
budgets.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import Enum


class EscalationReason(str, Enum):
    """Why we asked the LLM. Add to this enum, not to free-form strings."""

    # PackPrior: top-2 packs within the 0.15-confidence band.
    PACK_PRIOR_AMBIGUOUS_TOP2 = "pack_prior_ambiguous_top2"
    # PackPrior: every keyword score is zero — no deterministic signal.
    PACK_PRIOR_NO_SIGNAL = "pack_prior_no_signal"
    # SiteReality: a cluster has multiple competing canonical names.
    SITE_REALITY_AMBIGUOUS_NAME = "site_reality_ambiguous_name"
    # SiteReality: a cluster has zero canonical name candidates.
    SITE_REALITY_UNNAMED_CLUSTER = "site_reality_unnamed_cluster"


@dataclass(frozen=True)
class Escalation:
    """One LLM consultation event, recorded for audit + test."""

    engine: str
    reason: EscalationReason
    detail: str  # short human-readable context
    model_id: str = ""

    def to_dict(self) -> dict:
        return {
            "engine": self.engine,
            "reason": self.reason.value,
            "detail": self.detail,
            "model_id": self.model_id,
        }


@dataclass
class EscalationLog:
    """Append-only log of LLM consultations on one envelope.

    Engines mutate this through :meth:`record` only — no direct
    list access. Reads go through :meth:`as_list` (sorted) so two
    runs over the same envelope produce identical logs.
    """

    entries: list[Escalation] = field(default_factory=list)

    def record(
        self,
        *,
        engine: str,
        reason: EscalationReason,
        detail: str,
        model_id: str = "",
    ) -> Escalation:
        ev = Escalation(
            engine=engine,
            reason=reason,
            detail=detail,
            model_id=model_id,
        )
        self.entries.append(ev)
        return ev

    @property
    def count(self) -> int:
        return len(self.entries)

    def as_list(self) -> list[Escalation]:
        """Stable, sorted copy for serialization / assertions."""
        return sorted(
            self.entries,
            key=lambda e: (e.engine, e.reason.value, e.detail),
        )

    def by_reason(self) -> dict[str, int]:
        """Counts grouped by reason, for state summaries."""
        return dict(
            sorted(
                Counter(e.reason.value for e in self.entries).items()
            )
        )

    def to_dict(self) -> dict:
        """Serialize the whole log for inclusion in state objects."""
        return {
            "count": self.count,
            "by_reason": self.by_reason(),
            "entries": [e.to_dict() for e in self.as_list()],
        }
