"""Regression tests for PR12 (other-as-fallback) and PR13 (per-source
keyword cap + margin-based confidence)."""
from __future__ import annotations

from orbitbrief_core.world_model.pack_prior.router import PackPrior


def test_other_demotes_when_specialized_pack_strong():
    """When a specialized pack has >= 20 % of top score, other → 0."""
    raw = {"wireless": 100, "msp": 30, "other": 50}
    out = PackPrior._demote_other_when_specialized_exists(raw)
    # msp has 30 % of wireless → other demoted.
    assert out["other"] == 0
    assert out["wireless"] == 100


def test_other_kept_when_no_specialized_signal():
    """All-zero specialized → other can keep its score."""
    raw = {"wireless": 0, "msp": 0, "other": 12}
    out = PackPrior._demote_other_when_specialized_exists(raw)
    assert out["other"] == 12


def test_other_demoted_even_when_other_is_top():
    """Even if other has the highest raw_score, demote when any
    specialized pack has >= 20 % of the top specialized score."""
    raw = {"other": 200, "wireless": 60, "msp": 10}
    out = PackPrior._demote_other_when_specialized_exists(raw)
    # wireless (60) is the top SPECIALIZED → msp must be >= 12 to count.
    # msp at 10 < 12 BUT wireless itself qualifies (>= 20 % of top
    # specialized = wireless itself), so other gets demoted.
    assert out["other"] == 0


def test_calibrated_confidence_never_returns_one():
    """No pack should be at 1.0 — that's the user's red flag."""
    raw = {"wireless": 1000, "msp": 1, "other": 0}
    confs = PackPrior._calibrated_confidences(raw)
    assert all(c < 1.0 for c in confs.values()), confs
    # Top pack should be at the calibrator ceiling (0.985) when the
    # margin is huge.
    assert max(confs.values()) <= 0.985 + 1e-6


def test_calibrated_confidence_low_when_margin_thin():
    """A 5 % margin should produce a confidence well under 0.8."""
    raw = {"wireless": 100, "msp": 95, "other": 0}
    confs = PackPrior._calibrated_confidences(raw)
    assert confs["wireless"] < 0.70, confs


def test_calibrated_confidence_zero_for_zero_score():
    raw = {"wireless": 50, "msp": 0, "other": 0}
    confs = PackPrior._calibrated_confidences(raw)
    assert confs["msp"] == 0.0
    assert confs["other"] == 0.0


def test_select_pack_ids_never_includes_other():
    from orbitbrief_core.world_model.pack_prior.state import PackScore

    scores = [
        PackScore(pack_id="other", display_name="other", raw_score=200, confidence=0.9, matched_keywords=()),
        PackScore(pack_id="wireless", display_name="wireless", raw_score=100, confidence=0.7, matched_keywords=()),
        PackScore(pack_id="msp", display_name="msp", raw_score=80, confidence=0.5, matched_keywords=()),
    ]
    selected = PackPrior._select_pack_ids(scores)
    assert "other" not in selected
    assert "wireless" in selected
