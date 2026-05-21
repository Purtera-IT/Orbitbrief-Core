"""Pattern miner — frequency tables + margin correlations across the
learning ledger.

Activates meaningfully at ~50 deals per domain pack (below that, the
frequency counts are too noisy to act on; the miner returns empty
``DomainPatterns`` and the UI skips the section). At 100+ deals per
domain you can trust the percentages.

Three families of patterns extracted:

1. **Atom-type frequencies** — "87 % of closed copper_cabling deals
   included quantity atoms; 60 % had open_questions."

2. **Gap rule co-occurrence** — "When ``electrical.panel_breaker``
   gap fires, ``low_voltage_cabling.termination_scheme_missing``
   fires 78 % of the time → bundle the questions."

3. **Margin correlations** — "Deals with the ``vendor_mismatch``
   reconciliation flag lost an average of 4.2 pp of margin." Useful
   for flagging risky deals before SOW lock.
"""
from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from orbitbrief_core.learning.learning_ledger import (
    LearningLedger,
    LearningRecord,
)

# Minimum sample size before a pattern is considered reportable.
# Below this, the miner emits no patterns (avoiding noise-driven UI).
MIN_SAMPLE = 5


@dataclass(frozen=True)
class FrequencyBucket:
    """A label + its frequency across the corpus.

    ``frequency`` is ``count / n_total`` in the 0.0-1.0 range.
    ``count`` and ``n_total`` are also exposed so the UI can render
    e.g. ``"4 of 7 deals (57 %)"``.
    """

    label: str
    count: int
    n_total: int
    frequency: float                                 # 0.0 - 1.0


@dataclass(frozen=True)
class MarginCorrelation:
    """A signal (gap rule / reconciliation kind) and its margin delta.

    ``margin_delta_pp`` is the mean margin among deals carrying the
    signal MINUS the mean margin among deals that didn't. Negative
    values are "this signal correlates with margin loss."
    """

    signal_kind: str                                 # "gap_rule" | "reconciliation_kind" | "risk_id"
    signal_id: str
    n_with: int                                      # deals that had this signal
    n_without: int                                   # deals that didn't
    avg_margin_with: float
    avg_margin_without: float
    margin_delta_pp: float                           # with - without (negative = bad)


@dataclass(frozen=True)
class DomainPatterns:
    """Mined patterns for one domain pack.

    Empty when the corpus has fewer than :data:`MIN_SAMPLE` deals in
    this domain — the UI then renders nothing instead of misleading
    statistics.
    """

    domain: str
    n_deals: int
    common_atom_types: list[FrequencyBucket] = field(default_factory=list)
    common_gap_rules: list[FrequencyBucket] = field(default_factory=list)
    common_reconciliation_kinds: list[FrequencyBucket] = field(default_factory=list)
    common_risk_ids: list[FrequencyBucket] = field(default_factory=list)
    margin_signals: list[MarginCorrelation] = field(default_factory=list)
    avg_margin_pct: float = 0.0
    win_rate: float = 0.0                            # 0.0 - 1.0; deals with outcome="won"


def _frequency_table(
    counts: Counter,
    n_total: int,
    *,
    top_n: int = 10,
) -> list[FrequencyBucket]:
    return [
        FrequencyBucket(label=label, count=c, n_total=n_total, frequency=c / n_total)
        for label, c in counts.most_common(top_n)
    ]


def _margin_correlations(
    records: list[LearningRecord],
    *,
    signal_kind: str,
    signal_id_getter,
) -> list[MarginCorrelation]:
    """For each unique signal_id, compute mean-margin-with vs
    mean-margin-without.

    Returns the top-10 by absolute margin delta (worst first if
    negative — those are the patterns to flag)."""
    signal_to_records: dict[str, list[LearningRecord]] = {}
    for r in records:
        ids = signal_id_getter(r) or []
        for sid in set(ids):
            signal_to_records.setdefault(sid, []).append(r)

    out: list[MarginCorrelation] = []
    record_set = list(records)
    for sid, with_records in signal_to_records.items():
        if len(with_records) < 3 or len(with_records) == len(record_set):
            continue
        without_records = [r for r in record_set if r not in with_records]
        if not without_records:
            continue
        avg_with = statistics.mean(r.final_margin_pct for r in with_records)
        avg_without = statistics.mean(r.final_margin_pct for r in without_records)
        delta = avg_with - avg_without
        if abs(delta) < 0.5:                         # below noise floor
            continue
        out.append(
            MarginCorrelation(
                signal_kind=signal_kind,
                signal_id=sid,
                n_with=len(with_records),
                n_without=len(without_records),
                avg_margin_with=avg_with,
                avg_margin_without=avg_without,
                margin_delta_pp=delta,
            )
        )
    out.sort(key=lambda m: m.margin_delta_pp)        # most negative first
    return out[:10]


def mine_patterns(
    domain: str,
    *,
    ledger_path: Path | str | None = None,
) -> DomainPatterns:
    """Compute frequency tables + margin correlations for one domain.

    Returns an empty :class:`DomainPatterns` if the corpus has fewer
    than :data:`MIN_SAMPLE` deals in this domain.
    """
    if ledger_path is None:
        ledger = LearningLedger.at(out_dir=None)
    else:
        ledger = LearningLedger(path=Path(ledger_path))

    records = list(ledger.all_by_domain(domain))
    n = len(records)
    if n < MIN_SAMPLE:
        return DomainPatterns(domain=domain, n_deals=n)

    atom_counter: Counter[str] = Counter()
    gap_counter: Counter[str] = Counter()
    recon_counter: Counter[str] = Counter()
    risk_counter: Counter[str] = Counter()
    wins = 0
    margins: list[float] = []
    for r in records:
        for k, c in r.atom_type_counts.items():
            atom_counter[k] += c
        gap_counter.update(set(r.top_gap_rule_ids))   # set → presence count
        recon_counter.update(set(r.reconciliation_kinds))
        risk_counter.update(set(r.risk_ids))
        if r.outcome == "won":
            wins += 1
        if r.final_margin_pct:
            margins.append(r.final_margin_pct)

    return DomainPatterns(
        domain=domain,
        n_deals=n,
        common_atom_types=_frequency_table(atom_counter, n),
        common_gap_rules=_frequency_table(gap_counter, n),
        common_reconciliation_kinds=_frequency_table(recon_counter, n),
        common_risk_ids=_frequency_table(risk_counter, n),
        margin_signals=(
            _margin_correlations(
                records,
                signal_kind="gap_rule",
                signal_id_getter=lambda r: r.top_gap_rule_ids,
            )
            + _margin_correlations(
                records,
                signal_kind="reconciliation_kind",
                signal_id_getter=lambda r: r.reconciliation_kinds,
            )
        ),
        avg_margin_pct=(statistics.mean(margins) if margins else 0.0),
        win_rate=(wins / n if n else 0.0),
    )


def format_for_brain_prompt(p: DomainPatterns) -> str:
    """Render a DomainPatterns object as a brain-prompt section.

    Empty string when the domain has fewer than MIN_SAMPLE deals —
    safe to inject unconditionally; cold-start renders nothing.
    """
    if p.n_deals < MIN_SAMPLE:
        return ""

    lines: list[str] = [
        f"INSTITUTIONAL MEMORY — {p.domain} ({p.n_deals} closed deals):",
        f"  win_rate: {p.win_rate * 100:.0f}% · avg_margin: {p.avg_margin_pct:.1f}%",
        "",
    ]
    if p.common_gap_rules:
        lines.append("  Most common gaps in past deals (auto-include in checklist):")
        for b in p.common_gap_rules[:5]:
            lines.append(f"    - {b.label} ({b.count}/{b.n_total} = {b.frequency*100:.0f}%)")
        lines.append("")
    if p.margin_signals:
        lines.append("  Margin-eroding signals (flag aggressively):")
        for s in p.margin_signals[:5]:
            if s.margin_delta_pp < 0:
                lines.append(
                    f"    - {s.signal_kind}={s.signal_id} "
                    f"({s.n_with} deals, avg margin {s.avg_margin_with:.1f}% "
                    f"vs {s.avg_margin_without:.1f}% without; "
                    f"delta {s.margin_delta_pp:+.1f}pp)"
                )
        lines.append("")
    return "\n".join(lines).rstrip()
