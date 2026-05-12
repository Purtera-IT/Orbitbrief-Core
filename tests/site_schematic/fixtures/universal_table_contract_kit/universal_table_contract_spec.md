# Universal Parser-Level Table Contract
Version: 2026-04-12.v1

## Goal
Create a parser-only, lossless table spine that preserves **table -> row -> cell -> semantic lineage** before any legend/schedule/index/outlet semantics are flattened.

This contract is universal across the two packet modalities represented by the benchmark PDFs:
1. **Control / legend / schedule modality** — dense tables, legends, indices, matrices, specs.
2. **Mixed detail / embedded-table modality** — details, risers, rack/equipment sheets that include small but high-value embedded schedules/tables.

OrbitBrief is downstream of this contract. The parser should emit these table objects first, and all higher-level semantic outputs must point back to row/cell provenance.

---

## Hard Gold Pages Chosen from the Two Benchmark PDFs

### Wireless packet (`100643PLANSD-4`)
#### 1. Page 1 — `TC001 TELECOMM SYMBOL LIST`
Why it is hard:
- hybrid page with **symbol list**, **abbreviations**, **drawing list**, **outlet descriptions**, and multiple notes sections
- mixes mini tables and table-like blocks with non-table notes
- is the most universal “control/legend hybrid” page in the wireless packet

Expected table families on this page:
- `drawing_index`
- `abbreviation_matrix`
- `telecommunications_symbol_legend`
- `outlet_type_description`
- `tag_symbols`
- `special_symbols`

### Southern Post packet (`2026-01-19 CONSOLIDATED SET - SOUTHERN POST - T...`)
#### 2. Page 1 — `T000 PROJECT REQUIREMENTS NOTES & SPECS`
Why it is hard:
- dense **multi-column notes/specs**
- includes a **drawing index table**
- tests region fidelity and table separation together

Expected table families on this page:
- `drawing_index`
- `notes_index_like_blocks` (must remain region-separated even if not modeled as full tables)

#### 3. Page 2 — `T001 SYMBOLS & LEGENDS`
Why it is hard:
- dense **multi-table legend matrix**
- multiple adjacent subtables with different semantics
- tests true row/column preservation under a visually crowded page

Expected table families on this page:
- `structured_cabling_symbol_legend`
- `intrusion_detection_symbol_legend`
- `access_control_intercom_symbol_legend`
- `cctv_symbol_legend`
- `responsibility_matrix` (if table-like section detected)
- `legend_notes` blocks kept separate from tables

#### 4. Page 3 — `T002 SCHEDULES & MISCELLANEOUS`
Why it is hard:
- specification/schedule style page
- component/spec tables with repeating rows and multiple columns
- tests schedule/spec extraction and row integrity

Expected table families on this page:
- `component_spec_table`
- `schedule_table`
- `manufacturer_part_table`

#### 5. Page 12 — `T900 ENLARGED EQUIPMENT ROOM LAYOUTS`
Why it is hard:
- mixed layout page
- tables/legend boxes/notes may be embedded among equipment-room views
- tests whether embedded tables remain separate from nearby detail geometry

Expected table families on this page:
- `embedded_legend_table`
- `embedded_schedule_table`
- `equipment_room_local_notes` kept separate from table cells

#### 6. Page 17 — `T905 SECURITY INSTALLATION DETAILS`
Why it is hard:
- detail page with a small embedded schedule / component table inside a non-table detail layout
- best stress case for “mixed detail / embedded-table modality”

Expected table families on this page:
- `embedded_detail_schedule`
- `cctv_component_schedule`
- detail-local notes and callouts must remain outside row/cell text unless explicitly in the table bbox

---

## The Universal Table Contract

### Core Objects

#### Table
A first-class structural object.
Required fields:
- `table_id`
- `packet_id`
- `pdf_id`
- `page_index`
- `sheet_number`
- `sheet_title`
- `region_id`
- `detail_region_id` (nullable)
- `subregion_id` (nullable)
- `pseudo_page_id` (nullable)
- `table_kind`
- `bbox`
- `source_mode`
- `provider`
- `confidence`
- `row_count`
- `column_count`
- `rows`
- `metadata`

#### Row
Required fields:
- `row_id`
- `table_id`
- `row_index`
- `bbox`
- `is_header`
- `cells`
- `raw_text_joined`
- `metadata`

#### Cell
Required fields:
- `cell_id`
- `table_id`
- `row_id`
- `row_index`
- `col_index`
- `bbox`
- `raw_text`
- `normalized_text`
- `rowspan`
- `colspan`
- `source_token_ids`
- `confidence`
- `metadata`

### Required Provenance
Every table, row, and cell must preserve:
- page/sheet provenance
- region lineage
- bbox
- source mode (`pdf_native`, `docling`, `pp_structure`, etc.)
- provider
- confidence

### Required Table Kinds
At minimum:
- `drawing_index`
- `symbol_legend`
- `abbreviation_matrix`
- `outlet_definition`
- `schedule`
- `component_spec`
- `responsibility_matrix`
- `embedded_detail_schedule`
- `generic_grid`

---

## Semantic Extractors Must Reference Row/Cell Provenance

Every higher-level semantic object derived from a table must carry:
- `source_table_id`
- `source_row_id`
- `source_cell_ids`

This applies to:
- legend entries
- abbreviation entries
- outlet definitions
- drawing index rows
- schedule rows
- component/spec rows
- responsibility matrix rows
- any future relational extractor output

If a semantic object cannot point back to row/cell provenance, the extraction is **not lossless**.

---

## What “Perfect” Means

### A. Perfect Region Fidelity (for table-bearing pages)
- all gold pages are decomposed into the right semantic regions
- table-like blocks are not merged into nearby notes/spec/detail blocks
- page-global notes remain separate from local detail or legend tables
- embedded schedules on mixed pages remain localized to the correct detail/equipment region
- no silent flattening of multi-column structure

### B. Perfect Table Extraction
- all required gold tables are detected
- row order is preserved
- cell order is preserved
- no unflagged split/merge of rows or cells
- every row/cell has bbox + provenance
- semantic outputs point back to row/cell lineage

---

## Perfect Gold Standard (must hit to be “perfect” on these two packets)

### Structural Metrics
- `required_table_kind_coverage = 1.0`
- `bbox_presence_rate = 1.0`
- `row_integrity_rate = 1.0`
- `cell_integrity_rate = 1.0`
- `lineage_completeness_rate = 1.0`
- `unflagged_row_merge_count = 0`
- `unflagged_row_split_count = 0`
- `unflagged_cell_merge_count = 0`
- `unflagged_cell_split_count = 0`

### Semantic Metrics
- `semantic_row_reference_rate = 1.0`
- `semantic_cell_reference_rate = 1.0`
- `drawing_index_row_preservation = 1.0`
- `legend_pairing_integrity = 1.0`
- `abbreviation_pairing_integrity = 1.0`
- `outlet_definition_pairing_integrity = 1.0`
- `component_spec_row_integrity = 1.0`

If any one of these fails on the gold pages, the parser is not “perfect” for this phase.

---

## Integration Targets in the Current Stack

This should integrate into the existing parser stack roughly at these layers:

1. **Observation layer**
- native/Docling/lightweight table candidates reconcile into universal `Table/Row/Cell` objects

2. **Models layer**
- first-class models for `Table`, `Row`, `Cell`, and lineage refs

3. **Extractor layer**
- legend/index/schedule/outlet parsers consume rows/cells instead of flattened page text

4. **Bundle layer**
- tables become first-class bundle outputs
- semantic objects carry `source_table_id`, `source_row_id`, `source_cell_ids`

5. **Graph layer**
- optional later: graph nodes/edges may reference semantic outputs, not raw tables directly
- graph does not need to change first for this phase

---

## First Implementation Scope
Implement **Phase 1 only**:
- universal table contract
- lossless row/cell preservation
- semantic lineage wiring for table-derived outputs
- gold tests on the selected hard pages

Do not broaden into full region-fidelity hardening yet.