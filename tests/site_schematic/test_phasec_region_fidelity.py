from __future__ import annotations

from .phasec_region_fidelity_eval import run_phasec_region_fidelity_eval


def test_phasec_region_fidelity_eval_status() -> None:
    report = run_phasec_region_fidelity_eval()
    assert report["status"] == "perfect"
    metrics = report["metrics"]
    assert metrics["required_region_kind_coverage"] >= 1.0
    assert metrics["region_bbox_presence_rate"] >= 1.0
    assert metrics["region_hierarchy_completeness_rate"] >= 1.0
    assert metrics["locality_provenance_rate"] >= 1.0
    assert metrics["global_vs_local_note_separation_rate"] >= 0.95
    assert metrics["detail_locality_reference_rate"] >= 0.95
    assert metrics["multi_column_preservation_rate"] >= 0.95
    assert metrics["table_region_reuse_rate"] >= 0.95
    assert metrics["hybrid_page_overflatten_count"] == 0
    assert metrics["pseudo_page_fragmentation_error_count"] == 0
    assert metrics["silent_note_scope_conflict_count"] == 0
    assert metrics["untyped_region_count"] == 0
