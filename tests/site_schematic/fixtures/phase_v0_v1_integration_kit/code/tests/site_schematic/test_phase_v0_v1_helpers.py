from orbitbrief_core.parser.site_schematic.page_modality_router import classify_page_modality
from orbitbrief_core.parser.site_schematic.vector_primitives import extract_vector_primitives_from_drawings
from orbitbrief_core.parser.site_schematic.vector_primitive_graph import build_vector_primitive_graph


def test_page_modality_router_vector_rich():
    d = classify_page_modality(
        page_index=0,
        sheet_type="riser_diagram",
        page_text="Riser diagram notes and labels",
        vector_path_count=120,
        image_count=0,
        line_art_density=0.8,
        table_count=0,
    )
    assert d.modality == "vector_rich"


def test_extract_vector_primitives_from_drawings():
    drawings = [{"items": [
        ("l", (0, 0), (10, 0)),
        ("re", (0, 0, 5, 5)),
        ("qu", [(0, 0), (1, 1), (2, 1)]),
    ]}]
    prims = extract_vector_primitives_from_drawings(drawings, page_index=0)
    assert len(prims) >= 3


def test_build_vector_primitive_graph():
    drawings = [{"items": [
        ("l", (0, 0), (100, 0)),
        ("l", (0, 10), (100, 10)),
    ]}]
    prims = extract_vector_primitives_from_drawings(drawings, page_index=0)
    g = build_vector_primitive_graph(prims, page_index=0)
    assert g.diagnostics["primitive_count"] >= 2
