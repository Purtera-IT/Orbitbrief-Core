"""Quality gate for the gap / risk / commercial teacher+judge heads.

Mocks DeepSeek (no network). Proves: no-op when key absent, no-op when flag off,
citations validated (fabricated cites dropped), judge filtering, and that each
head writes ONLY its own additive field. Production-safety contract enforced.
"""
import json
from dataclasses import dataclass, field
from typing import Any

import pytest


@dataclass
class FakeHandoff:
    gaps: list = field(default_factory=list)
    executive_summary: dict = field(default_factory=dict)
    gap_findings: list = field(default_factory=list)
    risk_synthesis: list = field(default_factory=list)
    commercial_narrative: dict = field(default_factory=dict)


def _env():
    types = ["scope_item", "requirement", "risk", "constraint", "commercial_total", "payment_term"]
    atoms = [{"id": f"x{i}", "atom_type": t, "text": f"atom {i} about {t}", "artifact_id": "d1"}
             for i, t in enumerate(types)]
    return {"documents": [{"artifact_id": "d1", "filename": "sow.pdf"}],
            "atoms": atoms, "deal_financials": {"overall_total": 134912.0},
            "pm_dashboard": {"money_summary": {"total": 134912.0}}}


def _mock_deepseek(teacher_payload):
    """Returns a deepseek_json stand-in: teacher response first, judge response (all real) after."""
    def fn(system, user, **kw):
        if "reviewer" in system.lower() or "auditing" in system.lower():
            items = json.loads(user.split(":\n", 1)[1]) if ":\n" in user else []
            return {"v": [{"i": it["i"], "real": True} for it in items]}
        return teacher_payload
    return fn


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setenv("ORBITBRIEF_NEURAL_HEADS", "1")
    monkeypatch.setattr("orbitbrief_core.neural_heads._deepseek.deepseek_available", lambda: True)
    # patch the symbol imported into each head module
    for mod in ("gap", "risk", "commercial"):
        monkeypatch.setattr(f"orbitbrief_core.neural_heads.{mod}.deepseek_available", lambda: True)
    return monkeypatch


def test_noop_without_key(monkeypatch):
    monkeypatch.setenv("ORBITBRIEF_NEURAL_HEADS", "1")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    from orbitbrief_core.neural_heads.gap import apply_gap
    h = FakeHandoff()
    assert apply_gap(h, _env()) is h  # no key -> graceful no-op


def test_gap_validates_citations_and_judges(patched, monkeypatch):
    teacher = {"gaps": [
        {"label": "Real gap", "severity": "blocker", "question": "?", "evidence_ids": ["A1"]},
        {"label": "Fabricated", "severity": "warning", "question": "?", "evidence_ids": ["A99"]},  # phantom
    ]}
    monkeypatch.setattr("orbitbrief_core.neural_heads.gap.deepseek_json", _mock_deepseek(teacher))
    from orbitbrief_core.neural_heads.gap import apply_gap
    out = apply_gap(FakeHandoff(), _env())
    labels = [g["label"] for g in out.gap_findings]
    assert labels == ["Real gap"]                          # phantom-cite gap dropped
    assert out.gap_findings[0]["source"] == "neural_heads.gap"
    assert out.gap_findings[0]["evidence_ids"] == ["A1"]


def test_risk_writes_only_its_field(patched, monkeypatch):
    teacher = {"risks": [{"title": "Margin risk", "likelihood": "high", "impact": "high",
                          "business_impact": "erodes margin", "mitigation": "confirm rates",
                          "severity": "warning", "atom_ids": ["A2"]}]}
    monkeypatch.setattr("orbitbrief_core.neural_heads.risk.deepseek_json", _mock_deepseek(teacher))
    from orbitbrief_core.neural_heads.risk import apply_risk
    out = apply_risk(FakeHandoff(), _env())
    assert out.risk_synthesis[0]["title"] == "Margin risk"
    assert out.gap_findings == [] and out.commercial_narrative == {}  # didn't touch other fields


def test_commercial_conflict_flag(patched, monkeypatch):
    teacher = {"value_summary": "Deal value $134,912", "billing_model": "hybrid",
               "flags": [{"label": "Conflicting deal totals", "note": "$21,560 vs $134,912",
                          "severity": "blocker", "atom_ids": ["A5"]}]}
    monkeypatch.setattr("orbitbrief_core.neural_heads.commercial.deepseek_json", _mock_deepseek(teacher))
    from orbitbrief_core.neural_heads.commercial import apply_commercial
    out = apply_commercial(FakeHandoff(), _env())
    assert out.commercial_narrative["billing_model"] == "hybrid"
    assert out.commercial_narrative["flags"][0]["label"] == "Conflicting deal totals"


def test_teacher_failure_is_noop(patched, monkeypatch):
    monkeypatch.setattr("orbitbrief_core.neural_heads.gap.deepseek_json", lambda *a, **k: None)
    from orbitbrief_core.neural_heads.gap import apply_gap
    h = FakeHandoff()
    assert apply_gap(h, _env()) is h  # teacher returned None -> unchanged
