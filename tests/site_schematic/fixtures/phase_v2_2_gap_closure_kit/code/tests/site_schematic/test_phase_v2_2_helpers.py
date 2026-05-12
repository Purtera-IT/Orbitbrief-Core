from orbitbrief_core.parser.site_schematic.hardpage_requirement_registry import derive_required_hardpage_types
from orbitbrief_core.parser.site_schematic.grounded_yield_metrics import compute_grounded_yield_metrics
from orbitbrief_core.parser.site_schematic.room_device_association_refinement import score_room_device_association
from orbitbrief_core.parser.site_schematic.connector_context_scoring import score_connector_context


def test_hardpage_registry():
    rows = [
        {"sheet_type": "legend_symbol"},
        {"sheet_type": "riser_diagram"},
        {"sheet_type": "floorplan_overall"},
    ]
    req = derive_required_hardpage_types(rows)
    assert req == ["legend_symbol", "riser_diagram", "floorplan_overall"]


def test_grounded_yield_metrics():
    m = compute_grounded_yield_metrics(
        total_candidates=100,
        grounded_symbols=60,
        unresolved_symbols=30,
        hardpage_candidates=40,
        hardpage_grounded=30,
        expected_family_total=10,
        expected_family_grounded=8,
    )
    assert m.grounded_symbol_yield_rate == 0.6
    assert m.unresolved_symbol_ratio == 0.3


def test_room_device_association():
    out = score_room_device_association(
        symbol_bbox=(0,0,10,10),
        room_label_bboxes=[(20,20,80,40)],
        same_region=True,
        leader_attached=True,
    )
    assert out.score > 0


def test_connector_context():
    out = score_connector_context(
        connector_candidate_count=2,
        leader_attachment_count=1,
        riser_context=True,
    )
    assert out.score > 0
