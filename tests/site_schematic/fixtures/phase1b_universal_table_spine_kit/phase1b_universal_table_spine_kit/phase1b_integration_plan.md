# Phase 1B Integration Plan: Universal Lossless Table Spine

## Goal
Turn the existing Phase 1 table contract into a near-lossless parser spine by fixing the four concrete gaps that prevented the hard-page gold evaluation from reaching the Phase 1 target:

1. Header-aware multi-table splitting on hybrid pages
2. Stronger table-kind routing
3. Embedded-table promotion on detail pages
4. Mandatory table-first semantic extractor routing

## Why Phase 1 was not perfect
Phase 1 already proved the table contract works when a table is found:
- `bbox_presence_rate = 1.0`
- `lineage_completeness_rate = 1.0`
- `unflagged row/cell merge/split counts = 0`

The failure modes were upstream and downstream of the contract:
- **Upstream:** under-splitting and under-classifying hybrid pages
- **Downstream:** semantic extractors still relied too often on regex/text fallbacks rather than row/cell provenance

### Concrete misses from the Phase 1 gold eval
- `wireless_tc001_page1`
  - missing: `drawing_index`, `symbol_legend`, `outlet_definition`, `generic_grid`
- `southern_t001_page2`
  - missing: `generic_grid`
- `southern_t900_page12`
  - missing: `embedded_detail_schedule`

## Files most likely to change
### Core parser table spine
- `src/orbitbrief_core/parser/site_schematic/universal_table_spine.py`
- `src/orbitbrief_core/parser/site_schematic/core.py`

### Table-first semantic routing
- `src/orbitbrief_core/parser/site_schematic/extractors/common.py`
- `src/orbitbrief_core/parser/site_schematic/extractors/index_sheet_extractor.py`
- `src/orbitbrief_core/parser/site_schematic/extractors/legend_sheet_extractor.py`
- `src/orbitbrief_core/parser/site_schematic/extractors/notes_spec_extractor.py`
- `src/orbitbrief_core/parser/site_schematic/extractors/schedule_sheet_extractor.py`
- `src/orbitbrief_core/parser/site_schematic/extractors/__init__.py`

### Tests / eval
- `tests/site_schematic/universal_table_contract_eval.py`
- `tests/site_schematic/test_universal_table_contract.py`

## Implementation plan

### Fix 1 — Header-aware multi-table splitting
Add a splitting pass before table-kind inference.

#### What it should do
For every page-level table candidate or hybrid block, split into distinct table candidates using:
- boxed headers
- title/header text
- vertical separator logic
- local grid boundaries
- section-level geometry

#### Must recognize at minimum
- **Wireless `TC001` page 1**
  - `ABBREVIATIONS`
  - `DRAWING LIST`
  - `OUTLET TYPE DESCRIPTION`
  - `TELECOMMUNICATIONS SYMBOLS`
- **Southern Post `T001` page 2**
  - `RESPONSIBILITY MATRIX`
  - structured cabling symbol legend
  - intrusion legend
  - access/intercom legend
  - CCTV legend

#### Suggested code shape
Inside `universal_table_spine.py`, add helpers like:
- `split_hybrid_table_candidates(...)`
- `_find_header_bands(...)`
- `_split_by_vertical_separators(...)`
- `_split_by_local_box_geometry(...)`

Each split child should keep:
- parent table/source id
- bbox
- header text
- source mode/provider
- ambiguity flags

### Fix 2 — Stronger table-kind router
Run table-kind inference after splitting, not before.

#### Inputs to use
- normalized header text
- column signature
- row token patterns
- family-specific keywords
- local page context (sheet type / region type)

#### Required mappings
- `DWG No / DRAWING NAME` -> `drawing_index`
- `SYMBOL / DESCRIPTION / CABLE COUNT / TERMINATION / POWER / REMARKS` -> `symbol_legend`
- abbreviation-like two-column code/meaning grids -> `abbreviation_matrix` or `generic_grid`
- outlet-definition style tables -> `outlet_definition`
- description/manufacturer/part number/comments -> `component_spec` / `manufacturer_part_table` / `schedule`
- small boxed schedule inside detail page -> `embedded_detail_schedule`

#### Suggested code shape
Inside `universal_table_spine.py`, add:
- `infer_table_kind_v2(...)`
- `_score_table_kind_from_header(...)`
- `_score_table_kind_from_columns(...)`
- `_score_table_kind_from_rows(...)`
- `_resolve_kind_from_scores(...)`

### Fix 3 — Embedded-table promoter for detail pages
On pages like `T900` / `T905`, promote local boxed schedule-like regions into table candidates.

#### Promotion conditions
Promote when all of the following are sufficiently true:
- local header exists
- row-like alignment exists
- geometry is box-like or schedule-like
- region lives inside a detail page
- candidate is more schedule-like than note-block-like

#### Suggested code shape
Inside `universal_table_spine.py`, add:
- `promote_embedded_detail_tables(...)`
- `_detect_boxed_schedule_candidates(...)`
- `_is_schedule_like_region(...)`

### Fix 4 — Mandatory table-first extractor routing
Semantic extractors must use universal table rows/cells first.

#### Required routing order
For these extractors:
- drawing index
- legend
- abbreviations
- outlet definitions
- schedule/spec rows

Use:
1. Universal table rows/cells of the expected kind
2. Semantic objects with `source_table_id`, `source_row_id`, `source_cell_ids`
3. Regex/text fallback only if no valid expected table exists

#### Required provenance rule
Every table-derived semantic object must carry:
- `source_table_id`
- `source_row_id`
- `source_cell_ids`

## Acceptance target for Phase 1B

### Structural gold
- `required_table_kind_coverage = 1.0`
- `bbox_presence_rate = 1.0`
- `lineage_completeness_rate = 1.0`
- `unflagged row/cell merge/split counts = 0`

### Semantic lineage gold
- `semantic_row_reference_rate >= 0.95`
- `semantic_cell_reference_rate >= 0.95`

### Hard-page gold
No missing required kinds on:
- `wireless_tc001_page1`
- `southern_t001_page2`
- `southern_t900_page12`

Keep current good behavior on:
- `southern_t000_page1`
- `southern_t002_page3`
- `southern_t905_page17`

## Integration sequence
1. Add splitter
2. Add stronger kind router
3. Add embedded-table promoter
4. Wire table-first extractor routing
5. Re-run hard-page gold eval
6. Re-run parser regression suites

## Definition of success
The table spine is “perfect” for Phase 1B when the parser:
- preserves every required hard-page table family
- preserves row/cell provenance
- routes semantic extraction through rows/cells first
- and the hard-page gold report reaches the acceptance targets above.
