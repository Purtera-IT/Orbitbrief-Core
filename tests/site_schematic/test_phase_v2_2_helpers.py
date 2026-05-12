from orbitbrief_core.parser.site_schematic.connector_context_scoring import score_connector_context
from orbitbrief_core.parser.site_schematic.grounded_yield_metrics import compute_grounded_yield_metrics
from orbitbrief_core.parser.site_schematic.hardpage_requirement_registry import derive_required_hardpage_types
from orbitbrief_core.parser.site_schematic.room_device_association_refinement import score_room_device_association


def test_hardpage_registry() -> None:
    rows = [
        {"sheet_type": "legend_symbol"},
        {"sheet_type": "riser_diagram"},
        {"sheet_type": "floorplan_overall"},
    ]
    requirements = derive_required_hardpage_types(rows)
    assert requirements == ["legend_symbol", "riser_diagram", "floorplan_overall"]


def test_grounded_yield_metrics() -> None:
    metrics = compute_grounded_yield_metrics(
        total_candidates=100,
        grounded_symbols=60,
        unresolved_symbols=30,
        hardpage_candidates=40,
        hardpage_grounded=30,
        expected_family_total=10,
        expected_family_grounded=8,
    )
    assert metrics.grounded_symbol_yield_rate == 0.6
    assert metrics.unresolved_symbol_ratio == 0.3


def test_room_device_association() -> None:
    assoc = score_room_device_association(
        symbol_bbox=(0.0, 0.0, 10.0, 10.0),
        room_label_bboxes=[(20.0, 20.0, 80.0, 40.0)],
        same_region=True,
        leader_attached=True,
    )
    assert assoc.score > 0.0


def test_connector_context() -> None:
    connector = score_connector_context(
        connector_candidate_count=2,
        leader_attachment_count=1,
        riser_context=True,
    )
    assert connector.score > 0.0
