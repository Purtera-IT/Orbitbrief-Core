"""Unit tests for the institutional-memory learning module.

Pin the contracts:

* Ledger schema is backward-compatible with corpus_history.jsonl
* Retrieval ranks deals correctly by domain overlap + value distance
* Pattern miner requires MIN_SAMPLE deals before reporting
* Empty corpus → empty results, never raises
* Margin correlations correctly identify margin-eroding signals
* PM decision serialization round-trips
"""
from __future__ import annotations

import json
from datetime import datetime, timezone  # noqa: F401 — used in some tests
from pathlib import Path

import pytest

from orbitbrief_core.learning import (
    LearningLedger,
    LearningRecord,
    PmDecisionRecord,
    mine_patterns,
    retrieve_similar_deals,
)
from orbitbrief_core.learning.learning_ledger import build_record_from_handoff
from orbitbrief_core.learning.pattern_miner import (
    MIN_SAMPLE,
    format_for_brain_prompt as format_patterns,
)
from orbitbrief_core.learning.retrieve_similar_deals import (
    format_for_brain_prompt as format_retrieval,
    score_deal,
)


# ──────────────────────────────────────────────────────────────────
# Test fixtures
# ──────────────────────────────────────────────────────────────────


def _make_record(
    case_id: str,
    domains: list[str],
    deal_value_usd: int = 100_000,
    closed_at: str = "2026-08-14",
    outcome: str = "won",
    final_margin_pct: float = 22.0,
    gap_rules: list[str] | None = None,
    recon_kinds: list[str] | None = None,
    atom_type_counts: dict[str, int] | None = None,
) -> LearningRecord:
    return LearningRecord(
        case_id=case_id,
        closed_at=closed_at,
        deal_value_usd=deal_value_usd,
        domains=domains,
        sites_count=1,
        phase_count=4,
        final_margin_pct=final_margin_pct,
        outcome=outcome,
        atom_type_counts=atom_type_counts or {"scope_item": 12, "quantity": 3},
        top_gap_rule_ids=gap_rules or [],
        reconciliation_kinds=recon_kinds or [],
    )


@pytest.fixture
def populated_ledger(tmp_path: Path) -> LearningLedger:
    """Ledger with 10 records — 8 wireless deals + 2 cabling deals."""
    ledger = LearningLedger(path=tmp_path / "learning.jsonl")
    for i in range(8):
        ledger.append(
            _make_record(
                case_id=f"WIRELESS_{i:03d}",
                domains=["Wireless / WLAN"],
                deal_value_usd=120_000 + i * 10_000,
                final_margin_pct=18.0 + i * 0.5,
                outcome="won" if i < 6 else "lost",
                gap_rules=[
                    "wireless.controller_unresolved",
                    "wireless.rf_survey_missing",
                ]
                if i % 2 == 0
                else ["wireless.controller_unresolved"],
                recon_kinds=["unit_price_disagreement"] if i in (1, 2, 7) else [],
                atom_type_counts={"scope_item": 10 + i, "quantity": 4},
            )
        )
    for i in range(2):
        ledger.append(
            _make_record(
                case_id=f"CABLING_{i:03d}",
                domains=["Structured cabling"],
                deal_value_usd=80_000,
                final_margin_pct=24.0,
                gap_rules=["electrical.panel_breaker"],
            )
        )
    return ledger


# ──────────────────────────────────────────────────────────────────
# Ledger schema + persistence
# ──────────────────────────────────────────────────────────────────


def test_ledger_round_trip(tmp_path: Path) -> None:
    ledger = LearningLedger(path=tmp_path / "l.jsonl")
    rec = _make_record(case_id="T1", domains=["Wireless / WLAN"])
    ledger.append(rec)
    records = ledger.all()
    assert len(records) == 1
    assert records[0].case_id == "T1"
    assert records[0].domains == ["Wireless / WLAN"]
    assert records[0].atom_type_counts == {"scope_item": 12, "quantity": 3}


def test_ledger_empty(tmp_path: Path) -> None:
    ledger = LearningLedger(path=tmp_path / "empty.jsonl")
    assert ledger.all() == tuple()
    assert ledger.record_count() == 0


def test_ledger_handles_missing_file(tmp_path: Path) -> None:
    ledger = LearningLedger(path=tmp_path / "nonexistent.jsonl")
    assert ledger.all() == tuple()


def test_ledger_backward_compat_with_corpus_history(tmp_path: Path) -> None:
    """Old corpus_history.jsonl rows (only 8 fields) hydrate cleanly."""
    path = tmp_path / "legacy.jsonl"
    legacy_row = {
        "case_id": "OLD_001",
        "closed_at": "2026-01-01",
        "deal_value_usd": 50_000,
        "domains": ["Structured cabling"],
        "sites_count": 1,
        "phase_count": 0,
        "final_margin_pct": 20.0,
        "outcome": "won",
    }
    path.write_text(json.dumps(legacy_row) + "\n", encoding="utf-8")
    ledger = LearningLedger(path=path)
    records = ledger.all()
    assert len(records) == 1
    assert records[0].case_id == "OLD_001"
    # New fields default to empty
    assert records[0].atom_type_counts == {}
    assert records[0].pm_decisions == []
    assert records[0].post_mortem == ""


def test_pm_decision_round_trip(tmp_path: Path) -> None:
    ledger = LearningLedger(path=tmp_path / "d.jsonl")
    rec = LearningRecord(
        case_id="T1",
        closed_at="2026-08-14",
        deal_value_usd=100_000,
        domains=["Wireless / WLAN"],
        sites_count=1,
        phase_count=4,
        final_margin_pct=22.0,
        outcome="won",
        pm_decisions=[
            PmDecisionRecord(
                target_kind="atom",
                target_id="atm_abc123",
                action="accepted",
                raw_text="Install 52 APs",
                final_text="Install 52 APs",
                reviewer="priya@",
            ),
            PmDecisionRecord(
                target_kind="gap",
                target_id="R-WIFI-001",
                action="rejected",
                reviewer="priya@",
            ),
        ],
    )
    ledger.append(rec)
    rt = ledger.all()
    assert len(rt[0].pm_decisions) == 2
    assert rt[0].pm_decisions[0].action == "accepted"
    assert rt[0].pm_decisions[1].action == "rejected"


def test_ledger_filters_by_domain(populated_ledger: LearningLedger) -> None:
    wireless = populated_ledger.all_by_domain("Wireless / WLAN")
    assert len(wireless) == 8
    cabling = populated_ledger.all_by_domain("Structured cabling")
    assert len(cabling) == 2
    none = populated_ledger.all_by_domain("DOES NOT EXIST")
    assert len(none) == 0


# ──────────────────────────────────────────────────────────────────
# Retrieval
# ──────────────────────────────────────────────────────────────────


def test_retrieval_returns_top_k(populated_ledger: LearningLedger) -> None:
    hits = retrieve_similar_deals(
        target_domains=["Wireless / WLAN"],
        target_value_usd=130_000,
        ledger_path=populated_ledger.path,
        limit=5,
    )
    assert len(hits) == 5
    # Wireless deals should rank higher than cabling
    assert all("WIRELESS" in h.record.case_id for h in hits)


def test_retrieval_domain_overlap_dominates(populated_ledger: LearningLedger) -> None:
    """A wireless query should not surface cabling deals before wireless."""
    hits = retrieve_similar_deals(
        target_domains=["Wireless / WLAN"],
        target_value_usd=80_000,                     # exactly matches cabling deal value
        ledger_path=populated_ledger.path,
        limit=3,
    )
    # Top hit should still be wireless (domain overlap beats value match)
    assert "WIRELESS" in hits[0].record.case_id


def test_retrieval_excludes_self(populated_ledger: LearningLedger) -> None:
    hits = retrieve_similar_deals(
        target_domains=["Wireless / WLAN"],
        ledger_path=populated_ledger.path,
        limit=10,
        exclude_case_ids=["WIRELESS_001", "WIRELESS_002"],
    )
    found = {h.record.case_id for h in hits}
    assert "WIRELESS_001" not in found
    assert "WIRELESS_002" not in found


def test_retrieval_empty_ledger(tmp_path: Path) -> None:
    """Cold-start: no past deals → empty list, never raises."""
    hits = retrieve_similar_deals(
        target_domains=["Wireless / WLAN"],
        ledger_path=tmp_path / "missing.jsonl",
    )
    assert hits == []


def test_retrieval_score_won_deal_better(tmp_path: Path) -> None:
    """Won deals score better than lost deals (we want winning patterns)."""
    won = _make_record(
        case_id="W1",
        domains=["Wireless / WLAN"],
        outcome="won",
    )
    lost = _make_record(
        case_id="L1",
        domains=["Wireless / WLAN"],
        outcome="lost",
    )
    won_score, _ = score_deal(
        won,
        target_domains={"Wireless / WLAN"},
        target_value_usd=100_000,
    )
    lost_score, _ = score_deal(
        lost,
        target_domains={"Wireless / WLAN"},
        target_value_usd=100_000,
    )
    assert won_score < lost_score                    # lower = better


def test_retrieval_format_for_prompt(populated_ledger: LearningLedger) -> None:
    hits = retrieve_similar_deals(
        target_domains=["Wireless / WLAN"],
        ledger_path=populated_ledger.path,
        limit=3,
    )
    text = format_retrieval(hits)
    assert "PAST PATTERNS" in text
    assert "WIRELESS" in text


def test_retrieval_format_empty() -> None:
    """No hits → empty string, safe to inject unconditionally."""
    assert format_retrieval([]) == ""


# ──────────────────────────────────────────────────────────────────
# Pattern miner
# ──────────────────────────────────────────────────────────────────


def test_pattern_miner_returns_empty_below_threshold(tmp_path: Path) -> None:
    """Below MIN_SAMPLE deals → empty patterns, no noise."""
    ledger = LearningLedger(path=tmp_path / "small.jsonl")
    for i in range(MIN_SAMPLE - 1):
        ledger.append(_make_record(case_id=f"S{i}", domains=["Wireless / WLAN"]))
    patterns = mine_patterns("Wireless / WLAN", ledger_path=ledger.path)
    assert patterns.n_deals == MIN_SAMPLE - 1
    assert patterns.common_atom_types == []
    assert patterns.common_gap_rules == []


def test_pattern_miner_extracts_frequencies(populated_ledger: LearningLedger) -> None:
    patterns = mine_patterns("Wireless / WLAN", ledger_path=populated_ledger.path)
    assert patterns.n_deals == 8
    # controller_unresolved appears in all 8 deals
    rule_freqs = {b.label: b.frequency for b in patterns.common_gap_rules}
    assert rule_freqs.get("wireless.controller_unresolved") == 1.0
    # rf_survey_missing appears in 4 of 8 (the even-indexed ones)
    assert rule_freqs.get("wireless.rf_survey_missing") == 0.5


def test_pattern_miner_win_rate(populated_ledger: LearningLedger) -> None:
    patterns = mine_patterns("Wireless / WLAN", ledger_path=populated_ledger.path)
    # 6 of 8 wireless deals won
    assert patterns.win_rate == 0.75


def test_pattern_miner_avg_margin(populated_ledger: LearningLedger) -> None:
    patterns = mine_patterns("Wireless / WLAN", ledger_path=populated_ledger.path)
    # 8 wireless deals, margins 18.0, 18.5, 19.0, … 21.5 → mean 19.75
    assert abs(patterns.avg_margin_pct - 19.75) < 0.01


def test_pattern_miner_margin_correlation(tmp_path: Path) -> None:
    """Deals with `reconciliation_flag: X` should show margin_delta < 0
    if those deals had lower margins."""
    ledger = LearningLedger(path=tmp_path / "margin.jsonl")
    # 5 deals with the flag, low margin
    for i in range(5):
        ledger.append(
            _make_record(
                case_id=f"BAD_{i}",
                domains=["Wireless / WLAN"],
                final_margin_pct=15.0,
                recon_kinds=["unit_price_disagreement"],
            )
        )
    # 5 deals without the flag, high margin
    for i in range(5):
        ledger.append(
            _make_record(
                case_id=f"GOOD_{i}",
                domains=["Wireless / WLAN"],
                final_margin_pct=25.0,
                recon_kinds=[],
            )
        )
    patterns = mine_patterns("Wireless / WLAN", ledger_path=ledger.path)
    flagged = [
        s for s in patterns.margin_signals if s.signal_id == "unit_price_disagreement"
    ]
    assert len(flagged) == 1
    assert flagged[0].margin_delta_pp < 0
    assert abs(flagged[0].margin_delta_pp - (15.0 - 25.0)) < 0.1


def test_pattern_miner_format_for_prompt(populated_ledger: LearningLedger) -> None:
    patterns = mine_patterns("Wireless / WLAN", ledger_path=populated_ledger.path)
    text = format_patterns(patterns)
    assert "Wireless / WLAN" in text
    assert "8 closed deals" in text
    assert "win_rate" in text


def test_pattern_miner_format_empty_below_threshold(tmp_path: Path) -> None:
    ledger = LearningLedger(path=tmp_path / "tiny.jsonl")
    ledger.append(_make_record(case_id="ONLY", domains=["x"]))
    patterns = mine_patterns("x", ledger_path=ledger.path)
    assert format_patterns(patterns) == ""


# ──────────────────────────────────────────────────────────────────
# Builder — project a handoff dict into a LearningRecord
# ──────────────────────────────────────────────────────────────────


def test_build_record_from_handoff_minimal() -> None:
    handoff = {
        "case_id": "TEST_001",
        "margin_view": {"deal_total": 250_000, "margin_pct": 21.5},
        "domains": [
            {"label": "Wireless / WLAN", "active_for_sow": True},
            {"label": "Audio / visual", "active_for_sow": False},
        ],
        "sites": [{"name": "atl hq"}],
        "schedule_phases": [{"phase": "P1"}, {"phase": "P2"}],
        "gaps": [
            {"rule_id": "wireless.controller_unresolved"},
            {"rule_id": "wireless.rf_survey_missing"},
        ],
        "reconciliation_flags": [{"kind": "unit_price_disagreement"}],
        "risk_register": [{"risk_id": "RSK-001"}, {"risk_id": "RSK-002"}],
        "parser_quality_score": {"score": 92, "grade": "A"},
        "run_telemetry": {"compile_id": "cmp_abc123"},
    }
    rec = build_record_from_handoff(
        handoff,
        outcome="won",
        post_mortem="Smooth deal — repeat the BOM pattern.",
        polish_report={"items_polished": 130, "items_fallback": 2},
    )
    assert rec.case_id == "TEST_001"
    assert rec.deal_value_usd == 250_000
    assert rec.outcome == "won"
    assert rec.final_margin_pct == 21.5
    assert rec.domains == ["Wireless / WLAN"]    # only active_for_sow
    assert rec.sites_count == 1
    assert rec.phase_count == 2
    assert "wireless.controller_unresolved" in rec.top_gap_rule_ids
    assert rec.reconciliation_kinds == ["unit_price_disagreement"]
    assert "RSK-001" in rec.risk_ids
    assert rec.parser_quality_score == 92
    assert rec.parser_quality_grade == "A"
    assert rec.polish_items_polished == 130
    assert rec.compile_id == "cmp_abc123"
    assert rec.post_mortem.startswith("Smooth deal")


def test_build_record_handles_missing_fields() -> None:
    """Tolerant of sparse handoffs (e.g., COPPER_001 with no risks)."""
    handoff: dict = {"case_id": "SPARSE"}
    rec = build_record_from_handoff(handoff, outcome="active")
    assert rec.case_id == "SPARSE"
    assert rec.deal_value_usd == 0
    assert rec.sites_count == 0
    assert rec.outcome == "active"
    # closed_at defaults to today
    today_iso = datetime.now(timezone.utc).date().isoformat()
    assert rec.closed_at == today_iso


def test_build_record_overrides_margin_when_provided() -> None:
    """PM-supplied actual margin overrides the auto-computed estimate."""
    handoff = {
        "case_id": "T",
        "margin_view": {"margin_pct": 18.0},
    }
    rec = build_record_from_handoff(handoff, outcome="won", final_margin_pct=24.7)
    assert rec.final_margin_pct == 24.7
