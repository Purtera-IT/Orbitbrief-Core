from orbitbrief_core.parser.site_schematic.symbol_candidate_grouping import group_symbol_candidates_from_primitives
from orbitbrief_core.parser.site_schematic.semantic_mapper import build_legend_grounding_dictionary
from orbitbrief_core.parser.site_schematic.grounding_resolver import resolve_grounded_symbols
from orbitbrief_core.parser.site_schematic.vector_primitives import extract_vector_primitives_from_drawings

def test_group_symbol_candidates_from_primitives():
    drawings = [{"items": [("re", (0,0,10,10)), ("l", (0,0), (100,0))]}]
    prims = extract_vector_primitives_from_drawings(drawings, page_index=0)
    cands = group_symbol_candidates_from_primitives(page_index=0, vector_primitives=prims, nearby_text_hints=["AP", "Patch Panel"])
    assert len(cands) >= 1

def test_build_legend_grounding_dictionary():
    legends = [{"label": "WIRELESS ACCESS POINT", "source_row_id": "r1", "source_cell_ids": ["c1"]}]
    entries = build_legend_grounding_dictionary(page_index=0, legend_entries=legends)
    assert len(entries) == 1
    assert entries[0].family in {"ap_wap_marker", "unknown_symbol_group"}

def test_resolve_grounded_symbols():
    drawings = [{"items": [("re", (0,0,10,10))]}]
    prims = extract_vector_primitives_from_drawings(drawings, page_index=0)
    cands = group_symbol_candidates_from_primitives(page_index=0, vector_primitives=prims, nearby_text_hints=["PATCH PANEL"])
    legends = [{"label": "PATCH PANEL", "source_row_id": "r1", "source_cell_ids": ["c1"]}]
    entries = build_legend_grounding_dictionary(page_index=0, legend_entries=legends)
    grounded = resolve_grounded_symbols(candidates=cands, legend_dictionary=entries)
    assert len(grounded) >= 1
