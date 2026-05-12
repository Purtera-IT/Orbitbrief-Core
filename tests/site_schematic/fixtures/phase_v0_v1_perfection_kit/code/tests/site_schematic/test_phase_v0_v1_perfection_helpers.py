from orbitbrief_core.parser.site_schematic.modality_calibration import calibrate_modality_decision
from orbitbrief_core.parser.site_schematic.vector_primitives import extract_vector_primitives_from_drawings
from orbitbrief_core.parser.site_schematic.primitive_validation import validate_vector_primitive
from orbitbrief_core.parser.site_schematic.packet_v0_v1_quality import summarize_packet_v0_v1


def test_modality_calibration():
    out = calibrate_modality_decision(
        modality="vector_rich",
        confidence=0.95,
        vector_path_count=10,
        image_count=3,
        line_art_density=0.1,
        text_density=0.2,
    )
    assert out.modality in {"hybrid", "vector_rich"}


def test_primitive_validation():
    drawings = [{"items": [("l", (0, 0), (100, 0)), ("re", (0, 0, 5, 5))]}]
    prims = extract_vector_primitives_from_drawings(drawings, page_index=0)
    vals = [validate_vector_primitive(p) for p in prims]
    assert any(v.valid for v in vals)


def test_packet_quality_summary():
    packet = summarize_packet_v0_v1(
        packet_id="packet",
        page_modality_rows=[{"modality": "vector_rich", "ambiguous": False}],
        primitive_graph_rows=[{"primitive_count": 3, "validated_primitive_count": 3, "leader_candidate_count": 1, "dimension_candidate_count": 1}],
    )
    assert packet.modality_fail is False
    assert packet.primitive_graph_fail is False
