from orbitbrief_core.parser.site_schematic.page_modality_router import classify_page_modality
from orbitbrief_core.parser.site_schematic.vector_primitives import extract_vector_primitives_from_drawings
from orbitbrief_core.parser.site_schematic.vector_primitive_graph import build_vector_primitive_graph


def test_page_modality_router_vector_rich() -> None:
    decision = classify_page_modality(
        page_index=1,
        sheet_type="riser_diagram",
        page_text="Riser diagram notes and labels",
        vector_path_count=120,
        image_count=0,
        line_art_density=0.8,
        table_count=0,
    )
    assert decision.modality == "vector_rich"


def test_extract_vector_primitives_from_drawings() -> None:
    drawings = [
        {
            "items": [
                ("l", (0, 0), (10, 0)),
                ("re", (0, 0, 5, 5)),
                ("qu", [(0, 0), (1, 1), (2, 1)]),
            ]
        }
    ]
    primitives = extract_vector_primitives_from_drawings(drawings, page_index=1)
    assert len(primitives) >= 3


def test_build_vector_primitive_graph() -> None:
    drawings = [{"items": [("l", (0, 0), (100, 0)), ("l", (0, 10), (100, 10))]}]
    primitives = extract_vector_primitives_from_drawings(drawings, page_index=1)
    graph = build_vector_primitive_graph(tuple(primitives), page_index=1)
    assert graph.diagnostics["primitive_count"] >= 2
