from orbitbrief_core.parser.site_schematic.modality_zero_guard import detect_suspicious_zero_primitive_page
from orbitbrief_core.parser.site_schematic.primitive_dedup import dedup_vector_primitives
from orbitbrief_core.parser.site_schematic.primitive_density_audit import audit_primitive_density
from orbitbrief_core.parser.site_schematic.leader_dimension_quality import score_leader_semantic_quality, score_dimension_semantic_quality
from orbitbrief_core.parser.site_schematic.vector_primitives import extract_vector_primitives_from_drawings


def test_zero_primitive_guard():
    out = detect_suspicious_zero_primitive_page(
        modality="vector_rich",
        vector_path_count=50,
        image_count=0,
        line_art_density=0.6,
        primitive_count=0,
        validated_primitive_count=0,
    )
    assert out.suspicious is True


def test_dedup():
    prims = extract_vector_primitives_from_drawings([{"items": [("l", (0,0), (10,0)), ("l", (0,0), (10,0))]}], page_index=0)
    deduped = dedup_vector_primitives(prims)
    assert len(deduped) <= len(prims)


def test_density_audit():
    audit = audit_primitive_density(raw_count=100, deduped_count=60, validated_count=50)
    assert audit.sanity_ok is True


def test_leader_and_dimension_quality():
    prims = extract_vector_primitives_from_drawings([{"items": [("l", (0,0), (100,0))]}], page_index=0)
    leader = score_leader_semantic_quality(prims[0], nearby_text_hint=True)
    dim = score_dimension_semantic_quality(prims[0], nearby_numeric_text=True, witness_line_hint=True)
    assert leader.score > 0
    assert dim.score > 0
