from orbitbrief_core.parser.site_schematic.connector_truth_audit import audit_connector_truth
from orbitbrief_core.parser.site_schematic.family_coverage_enforcement import compute_family_coverage
from orbitbrief_core.parser.site_schematic.hardpage_gate_enforcement import enforce_hardpage_truth
from orbitbrief_core.parser.site_schematic.room_device_truth_audit import audit_room_device_truth
from orbitbrief_core.parser.site_schematic.sample_row_audit import select_grounding_sample_rows


def test_family_coverage() -> None:
    coverage = compute_family_coverage(
        expected_families=["a", "b", "c"],
        grounded_families=["a", "b"],
        hardpage_grounded_families=["a"],
    )
    assert coverage.expected_family_grounded_coverage_rate == 2 / 3
    assert coverage.hardpage_family_grounded_coverage_rate == 1 / 3


def test_room_truth_audit() -> None:
    audit = audit_room_device_truth(
        association_rate=0.9,
        room_assoc_scores=[0.6, 0.7, 0.8],
        near_room_label_hits=2,
        same_region_hits=1,
        leader_attached_hits=1,
    )
    assert audit.evidence_truth_ok is True


def test_connector_truth_audit() -> None:
    audit = audit_connector_truth(
        connector_quality_rate=0.9,
        connector_candidate_rate=0.6,
        connector_scores=[0.7, 0.8],
        leader_attachment_hits=1,
    )
    assert audit.evidence_truth_ok is True


def test_hardpage_gate() -> None:
    gate = enforce_hardpage_truth(
        required_page_types=["legend_symbol", "riser_diagram"],
        satisfied_page_types=["legend_symbol", "riser_diagram"],
        hardpage_grounded_symbol_yield_rate=0.8,
        hardpage_family_grounded_coverage_rate=0.9,
    )
    assert gate.hardpage_requirement_truth_ok is True


def test_sample_rows() -> None:
    rows = [{"grounded_family": "camera", "grounding_state": "grounded"}]
    sampled = select_grounding_sample_rows(rows, limit=5)
    assert len(sampled) == 1
