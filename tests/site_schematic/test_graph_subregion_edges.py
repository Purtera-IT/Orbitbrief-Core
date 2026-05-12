from __future__ import annotations

from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.site_schematic import build_site_schematic_bundle_from_router_input


GRAPH_SAMPLE = """
<PARSED TEXT FOR PAGE: 1 / 1>
T906 INSTALLATION DETAILS
GENERAL NOTES:
1. DETAIL A AP OUTLET SHALL TERMINATE ON DEDICATED PATCH PANEL.
DETAIL A - CEILING AP OUTLET DETAIL
AP CEILING OUTLET DETAIL
DETAIL B - GROUNDING DETAIL
TGB TO TMGB BONDING
""".strip()


def test_graph_contains_subregion_hierarchy_edges() -> None:
    bundle = build_site_schematic_bundle_from_router_input(
        RouterInput(
            doc_id="graph-subregion",
            filename="t906.pdf",
            mime_type="application/pdf",
            metadata={"full_text": GRAPH_SAMPLE},
        ),
        source_modality="site_schematic_pdf",
    )
    relations = {edge.relation for edge in bundle.graph.edges}
    assert "contains" in relations
    assert "projected_as" in relations
    assert "scoped_to_subregion" in relations or len(bundle.scoped_note_links) > 0
    assert any(node.kind == "detail_region" for node in bundle.graph.nodes)
    assert any(node.kind == "subregion" for node in bundle.graph.nodes)
    assert any(node.kind == "pseudo_page" for node in bundle.graph.nodes)
