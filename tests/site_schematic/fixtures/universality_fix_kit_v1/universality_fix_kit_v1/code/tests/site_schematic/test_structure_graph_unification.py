from orbitbrief_core.parser.site_schematic.structure_graph import build_page_structure_graph
from orbitbrief_core.parser.site_schematic.structure_graph_sheet_hints import build_sheet_archetype_hints
from orbitbrief_core.parser.site_schematic.structure_graph_table_router import infer_table_kind_from_structure_graph
from orbitbrief_core.parser.site_schematic.structure_graph_locality import infer_note_scope_with_structure_graph


def test_structure_graph_builds_columns_tables_and_regions():
    layout_blocks = [
        {"block_id": "b1", "bbox": [0, 0, 200, 100], "text": "PROJECT REQUIREMENTS NOTES & SPECS", "kind": "header"},
        {"block_id": "b2", "bbox": [10, 120, 180, 500], "text": "General notes...", "kind": "notes_block"},
        {"block_id": "b3", "bbox": [250, 120, 430, 500], "text": "More notes...", "kind": "notes_block"},
    ]
    universal_tables = [{
        "table_id": "t1",
        "bbox": [450, 100, 850, 500],
        "table_kind": "drawing_index",
        "rows": [{
            "row_id": "r1",
            "bbox": [450, 120, 850, 150],
            "cells": [
                {"cell_id": "c1", "bbox": [450, 120, 520, 150], "text": "Sheet Number"},
                {"cell_id": "c2", "bbox": [520, 120, 850, 150], "text": "Sheet Title"},
            ],
        }],
    }]
    regions = [{"region_id": "reg:notes", "bbox": [0, 80, 440, 520], "region_kind": "notes_spec_block"}]
    g = build_page_structure_graph(
        page_index=0,
        sheet_type="notes_spec",
        layout_blocks=layout_blocks,
        universal_tables=universal_tables,
        regions=regions,
        page_width=900.0,
    )
    assert g.diagnostics["column_count"] >= 1
    assert g.diagnostics["table_count"] == 1
    assert g.diagnostics["region_count"] == 1


def test_sheet_hints_and_table_kind_router():
    layout_blocks = [{"block_id": "b1", "bbox": [0,0,300,80], "text": "SYMBOLS & LEGENDS", "kind": "header"}]
    universal_tables = [{
        "table_id": "t1",
        "bbox": [0,100,600,400],
        "table_kind": "generic_grid",
        "rows": [{
            "row_id": "r1",
            "bbox": [0,100,600,130],
            "cells": [
                {"cell_id": "c1", "bbox": [0,100,100,130], "text": "SYMBOL"},
                {"cell_id": "c2", "bbox": [100,100,300,130], "text": "DESCRIPTION"},
                {"cell_id": "c3", "bbox": [300,100,420,130], "text": "CABLE COUNT"},
                {"cell_id": "c4", "bbox": [420,100,520,130], "text": "TERMINATION"},
                {"cell_id": "c5", "bbox": [520,100,600,130], "text": "POWER"},
            ],
        }],
    }]
    g = build_page_structure_graph(page_index=1, sheet_type="legend_symbol", layout_blocks=layout_blocks, universal_tables=universal_tables, regions=[], page_width=700)
    hints = build_sheet_archetype_hints(g)
    assert "legend_symbol" in hints.family_scores
    kind, scores = infer_table_kind_from_structure_graph(universal_tables[0], g)
    assert kind == "symbol_legend"


def test_note_scope_uses_structure_graph():
    layout_blocks = [{"block_id": "note1", "bbox": [20,20,150,100], "text": "NOTE 1", "kind": "notes_block"}]
    g = build_page_structure_graph(
        page_index=0,
        sheet_type="notes_spec",
        layout_blocks=layout_blocks,
        universal_tables=[],
        regions=[],
        detail_regions=[{"detail_region_id": "det1", "bbox": [0,0,200,200], "region_kind": "detail_block"}],
        page_width=300
    )
    decision = infer_note_scope_with_structure_graph({"block_id": "note1"}, g, detail_tokens=["D1"])
    assert decision.scope_class == "detail_local"
    assert decision.locality_confidence >= 0.8
