from __future__ import annotations

from pathlib import Path

from .phase_v0_v1_eval import ARTIFACT_ROOT, run_phase_v0_v1_eval


def test_phase_v0_v1_eval_artifacts() -> None:
    summary_path = ARTIFACT_ROOT / "phase_v0_v1_summary.json"
    rows_path = ARTIFACT_ROOT / "phase_v0_v1_packet_rows.json"
    if not summary_path.exists() or not rows_path.exists():
        run_phase_v0_v1_eval()
    assert summary_path.exists()
    assert rows_path.exists()
