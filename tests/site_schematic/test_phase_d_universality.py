from __future__ import annotations

from .phase_d_universality_eval import run_phase_d_universality_eval


def test_phase_d_universality_eval_honesty_contract() -> None:
    report = run_phase_d_universality_eval()
    assert report["downloaded_holdout_count"] + report["missing_holdout_count"] == 10
    assert report["registry_metrics"]["packet_registry_activation_honesty_rate"] >= 1.0
    assert report["registry_metrics"]["production_kpi_regression_count"] >= 0
    assert report["registry_metrics"]["contradiction_lane_separation_rate"] >= 1.0
