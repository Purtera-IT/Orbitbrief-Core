from orbitbrief_core.parser.site_schematic.holdout_titleblock_profiles import score_sheet_text_against_holdout_profiles
from orbitbrief_core.parser.site_schematic.column_structure_fusion import infer_holdout_columns, classify_note_scope_with_columns
from orbitbrief_core.parser.site_schematic.table_family_router_holdouts import choose_holdout_table_family
from orbitbrief_core.parser.site_schematic.observation_escalation_policy import choose_page_escalation_policy


def test_holdout_titleblock_profiles_score_expected_family():
    scores = score_sheet_text_against_holdout_profiles(
        ["PROJECT REQUIREMENTS NOTES & SPECS", "DRAWING INDEX"],
        ["T000"],
    )
    assert scores.get("notes_spec", 0) > 0


def test_column_fusion_finds_two_columns():
    blocks = [
        {"block_id": "b1", "bbox": [0, 0, 180, 120], "text": "left col"},
        {"block_id": "b2", "bbox": [10, 140, 190, 260], "text": "left col 2"},
        {"block_id": "b3", "bbox": [260, 0, 430, 120], "text": "right col"},
        {"block_id": "b4", "bbox": [270, 140, 440, 260], "text": "right col 2"},
    ]
    cols = infer_holdout_columns(blocks, page_width=500)
    assert len(cols) >= 2


def test_table_family_router_picks_symbol_legend():
    family, scores = choose_holdout_table_family(
        "SYMBOLS & LEGENDS",
        ["SYMBOL", "DESCRIPTION", "CABLE COUNT", "TERMINATION", "POWER"],
        sheet_family_hint="legend_symbol",
        region_kind_hint="legend_block",
    )
    assert family == "symbol_legend"


def test_obs_escalation_prefers_stronger_policy_when_ambiguous():
    out = choose_page_escalation_policy(
        sheet_family_hint="notes_spec",
        locality_confidence=0.4,
        table_family_confidence=0.5,
        column_ambiguity=0.5,
        titleblock_confidence=0.6,
    )
    assert out["policy"] in {"native_plus_pp_structure", "native_plus_docling_plus_pp_structure"}
