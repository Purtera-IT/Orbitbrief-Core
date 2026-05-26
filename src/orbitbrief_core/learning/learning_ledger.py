"""Learning ledger — append-only JSONL of every closed deal.

Extends the legacy ``corpus_history.jsonl`` schema with the fields
needed for retrieval + pattern mining + calibrator retraining:

* ``pm_decisions`` — every atom the PM accepted / rejected / hand-added
* ``atom_type_counts`` + ``packet_family_counts`` — distribution snapshots
* ``top_gap_rule_ids`` — the gap rules that fired (for pattern mining)
* ``reconciliation_kinds`` — kinds of contradictions found
* ``post_mortem`` — free-text notes from the PM at deal close

Backwards compatible: the original 8 fields (``case_id``, ``closed_at``,
``deal_value_usd``, ``domains``, ``sites_count``, ``phase_count``,
``final_margin_pct``, ``outcome``) are preserved as the first-class
keys. New fields are additive — old readers (
:func:`pm_intelligence.load_comparable_deals`) ignore them.

File path defaults to ``$ORBITBRIEF_LEARNING_LEDGER`` or
``<artifacts>/.orbitbrief_learning_ledger.jsonl``.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class PmDecisionRecord:
    """One PM decision captured at deal close.

    ``action`` is one of:

    * ``accepted``  — PM kept the auto-generated item
    * ``rejected``  — PM removed it (the system was wrong)
    * ``edited``    — PM kept it but rewrote the text
    * ``added``     — PM hand-added (the system missed this)
    """

    target_kind: str        # "atom" | "gap" | "risk" | "sow_section" | "rfp_line"
    target_id: str          # atom_id, rule_id, risk_id, section_name, etc.
    action: str             # "accepted" | "rejected" | "edited" | "added"
    raw_text: str = ""      # original text the system emitted (or "")
    final_text: str = ""    # what the PM left in the SOW (or "")
    reviewer: str = ""      # PM name / email (for bias detection)


@dataclass(frozen=True)
class LearningRecord:
    """One closed deal as a corpus entry.

    Two readers consume this:

    * Legacy ``load_comparable_deals`` only reads the first 8 fields
      — schema-compatible with the original ``corpus_history.jsonl``.
    * New ``retrieve_similar_deals`` + ``mine_patterns`` use all fields.
    """

    # ── Original (legacy-compatible) fields ──────────────────────
    case_id: str
    closed_at: str                                    # ISO date "2026-08-14"
    deal_value_usd: int
    domains: list[str]                                # active domain pack labels
    sites_count: int
    phase_count: int
    final_margin_pct: float
    outcome: str                                      # "won" | "lost" | "active" | ""

    # ── Extension: distributions ─────────────────────────────────
    atom_type_counts: dict[str, int] = field(default_factory=dict)
    packet_family_counts: dict[str, int] = field(default_factory=dict)
    authority_class_counts: dict[str, int] = field(default_factory=dict)
    entity_type_counts: dict[str, int] = field(default_factory=dict)

    # ── Extension: gap + reconciliation rule IDs that fired ──────
    top_gap_rule_ids: list[str] = field(default_factory=list)
    reconciliation_kinds: list[str] = field(default_factory=list)
    risk_ids: list[str] = field(default_factory=list)

    # ── Extension: PM decisions (the learning signal) ────────────
    pm_decisions: list[PmDecisionRecord] = field(default_factory=list)

    # ── Extension: post-mortem ───────────────────────────────────
    post_mortem: str = ""

    # ── Extension: run telemetry ─────────────────────────────────
    compile_id: str = ""
    parser_quality_score: int = 0
    parser_quality_grade: str = ""
    polish_items_polished: int = 0
    polish_items_fallback: int = 0

    def to_jsonable(self) -> dict[str, Any]:
        out = asdict(self)
        # PmDecisionRecord nested dataclasses serialize fine via asdict
        return out

    @classmethod
    def from_jsonable(cls, row: dict[str, Any]) -> "LearningRecord":
        """Tolerant constructor — falls through on missing fields so
        old corpus_history.jsonl rows hydrate as LearningRecords with
        empty extensions."""
        decisions_raw = row.get("pm_decisions") or []
        decisions: list[PmDecisionRecord] = []
        for d in decisions_raw:
            if not isinstance(d, dict):
                continue
            try:
                decisions.append(
                    PmDecisionRecord(
                        target_kind=str(d.get("target_kind", "")),
                        target_id=str(d.get("target_id", "")),
                        action=str(d.get("action", "")),
                        raw_text=str(d.get("raw_text", "")),
                        final_text=str(d.get("final_text", "")),
                        reviewer=str(d.get("reviewer", "")),
                    )
                )
            except (TypeError, ValueError):
                continue

        def _intmap(v: Any) -> dict[str, int]:
            if not isinstance(v, dict):
                return {}
            out: dict[str, int] = {}
            for k, c in v.items():
                try:
                    out[str(k)] = int(c or 0)
                except (TypeError, ValueError):
                    continue
            return out

        return cls(
            case_id=str(row.get("case_id", "")),
            closed_at=str(row.get("closed_at", "")),
            deal_value_usd=int(row.get("deal_value_usd") or 0),
            domains=[str(x) for x in (row.get("domains") or [])],
            sites_count=int(row.get("sites_count") or 0),
            phase_count=int(row.get("phase_count") or 0),
            final_margin_pct=float(row.get("final_margin_pct") or 0),
            outcome=str(row.get("outcome", "")),
            atom_type_counts=_intmap(row.get("atom_type_counts")),
            packet_family_counts=_intmap(row.get("packet_family_counts")),
            authority_class_counts=_intmap(row.get("authority_class_counts")),
            entity_type_counts=_intmap(row.get("entity_type_counts")),
            top_gap_rule_ids=[str(x) for x in (row.get("top_gap_rule_ids") or [])],
            reconciliation_kinds=[str(x) for x in (row.get("reconciliation_kinds") or [])],
            risk_ids=[str(x) for x in (row.get("risk_ids") or [])],
            pm_decisions=decisions,
            post_mortem=str(row.get("post_mortem", "")),
            compile_id=str(row.get("compile_id", "")),
            parser_quality_score=int(row.get("parser_quality_score") or 0),
            parser_quality_grade=str(row.get("parser_quality_grade", "")),
            polish_items_polished=int(row.get("polish_items_polished") or 0),
            polish_items_fallback=int(row.get("polish_items_fallback") or 0),
        )


def _default_ledger_path(out_dir: Path | None = None) -> Path:
    env = os.environ.get("ORBITBRIEF_LEARNING_LEDGER")
    if env:
        return Path(env)
    if out_dir is not None:
        return Path(out_dir) / ".orbitbrief_learning_ledger.jsonl"
    return Path(".orbitbrief_learning_ledger.jsonl")


@dataclass
class LearningLedger:
    """Append-only JSONL ledger of closed deals.

    Used by:

    * ``retrieve_similar_deals`` (read every row, score by similarity)
    * ``mine_patterns`` (aggregate across all rows in a domain)
    * ``calibrator_retrain`` (filter to ``outcome != ""`` rows)
    """

    path: Path

    def __post_init__(self) -> None:
        self.path = Path(self.path)

    def append(self, record: LearningRecord) -> None:
        """Add one closed deal. Atomic per-line write."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record.to_jsonable(), ensure_ascii=False) + "\n")

    def all(self) -> tuple[LearningRecord, ...]:
        """Read every record. Empty tuple when ledger is missing."""
        if not self.path.exists():
            return tuple()
        out: list[LearningRecord] = []
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                out.append(LearningRecord.from_jsonable(row))
        return tuple(out)

    def all_by_domain(self, domain: str) -> tuple[LearningRecord, ...]:
        """All records whose ``domains`` list contains the given pack."""
        return tuple(r for r in self.all() if domain in r.domains)

    def record_count(self) -> int:
        return len(self.all())

    @classmethod
    def at(cls, out_dir: Path | None = None) -> "LearningLedger":
        """Open the ledger at the conventional path (env-overridable)."""
        return cls(path=_default_ledger_path(out_dir))


# ──────────────────────────────────────────────────────────────────
# Builder helpers — extract a LearningRecord from a PMHandoff dict
# ──────────────────────────────────────────────────────────────────


def build_record_from_handoff(
    handoff: dict[str, Any],
    *,
    outcome: str = "",
    final_margin_pct: float | None = None,
    pm_decisions: Iterable[PmDecisionRecord] = (),
    post_mortem: str = "",
    closed_at: str | None = None,
    polish_report: dict[str, Any] | None = None,
) -> LearningRecord:
    """Project a closed-deal record from a PM_HANDOFF.json dict + the
    operator's post-close inputs (``outcome``, ``post_mortem``).

    Field-safe: tolerant of missing fields in the handoff dict; uses
    zero defaults rather than raising.
    """
    margin_view = handoff.get("margin_view") or {}
    parser_q = handoff.get("parser_quality_score") or {}
    run_tele = handoff.get("run_telemetry") or {}
    polish_report = polish_report or {}

    domains = [
        d.get("label", "")
        for d in (handoff.get("domains") or [])
        if d.get("active_for_sow")
    ]

    # Count distributions
    atom_type_counts: dict[str, int] = {}
    authority_class_counts: dict[str, int] = {}
    for cards in (handoff.get("facts_by_category") or {}).values():
        for c in cards:
            cat = c.get("category", "")
            if cat:
                atom_type_counts[cat] = atom_type_counts.get(cat, 0) + 1

    rec_flags = [str(f.get("kind", "")) for f in (handoff.get("reconciliation_flags") or [])]

    return LearningRecord(
        case_id=str(handoff.get("case_id", "")),
        closed_at=closed_at or datetime.now(timezone.utc).date().isoformat(),
        deal_value_usd=int(margin_view.get("deal_total") or 0),
        domains=domains,
        sites_count=len(handoff.get("sites") or []),
        phase_count=len(handoff.get("schedule_phases") or []),
        final_margin_pct=(
            float(final_margin_pct)
            if final_margin_pct is not None
            else float(margin_view.get("margin_pct") or 0)
        ),
        outcome=outcome,
        atom_type_counts=atom_type_counts,
        authority_class_counts=authority_class_counts,
        top_gap_rule_ids=[g.get("rule_id", "") for g in (handoff.get("gaps") or [])],
        reconciliation_kinds=[k for k in rec_flags if k],
        risk_ids=[r.get("risk_id", "") for r in (handoff.get("risk_register") or [])],
        pm_decisions=list(pm_decisions),
        post_mortem=post_mortem,
        compile_id=str(run_tele.get("compile_id", "")),
        parser_quality_score=int(parser_q.get("score") or 0),
        parser_quality_grade=str(parser_q.get("grade", "")),
        polish_items_polished=int(polish_report.get("items_polished") or 0),
        polish_items_fallback=int(polish_report.get("items_fallback") or 0),
    )
