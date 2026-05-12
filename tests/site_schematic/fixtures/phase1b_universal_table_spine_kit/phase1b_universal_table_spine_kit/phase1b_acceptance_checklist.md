# Phase 1B Acceptance Checklist

## Must stay green
- `tests/site_schematic/test_universal_table_contract.py`
- `tests/site_schematic/test_mixed_detail_decomposition.py`
- `tests/site_schematic/test_subregion_dispatch.py`
- `tests/site_schematic/test_note_scope_resolution.py`
- `tests/site_schematic/test_graph_subregion_edges.py`
- `tests/site_schematic/test_observation_policy_hardening.py`
- `tests/site_schematic/test_model_assisted_observations.py`
- `tests/site_schematic/test_phase2_pdf_smoke.py`
- `tests/site_schematic/test_gold_pdf_eval.py`
- `tests/site_schematic/universal_table_contract_eval.py`

## Must improve
- `required_table_kind_coverage`: 0.6 -> 1.0 target
- `semantic_row_reference_rate`: ~0.0798 -> >= 0.95 target
- `semantic_cell_reference_rate`: ~0.0798 -> >= 0.95 target

## Must remain perfect
- `bbox_presence_rate = 1.0`
- `lineage_completeness_rate = 1.0`
- unflagged row/cell merge/split counts = 0

## Phase 1B done when
- no hard-page required table kinds are missing
- semantic objects on hard pages are row/cell-backed by provenance
- current parser gold/decomposition tests remain green
