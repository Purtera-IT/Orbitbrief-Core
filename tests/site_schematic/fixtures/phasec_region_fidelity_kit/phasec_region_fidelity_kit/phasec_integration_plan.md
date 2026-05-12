# Phase C — Region Fidelity + Local Note Semantics (Parser-Only)

## Goal
Make the `site_schematic` parser lossless on **complex page decomposition** after Phase 1B (universal table spine).
OrbitBrief remains downstream-only.

## What Phase C is
Phase C is the parser-only upgrade that turns hard pages into stable, hierarchical region structures:

- page
  - coarse regions
  - detail regions
  - subregions
  - pseudo-pages
  - page-global notes
  - local detail notes
  - table-backed regions from Phase 1B

The parser should stop flattening mixed pages into generic blobs and should stop mixing global notes with local detail semantics.

## Why Phase C comes after Phase 1B
Phase 1B gave you a stable universal table spine.
Phase C must **use** that table spine instead of rediscovering tables from flat text.

Phase C should:
- treat universal tables as first-class region anchors
- preserve region bbox + hierarchy + provenance
- preserve local vs global note scope
- preserve multi-column reading order
- keep mixed pages decomposed into semantically meaningful units

## Hard-page families Phase C must handle
1. Hybrid control sheets
2. Dense multi-table legend pages
3. Multi-column notes/spec pages
4. Guestroom/multi-detail tiled sheets
5. Mixed equipment-room plan/elevation/rack/riser sheets
6. Riser diagram pages
7. Security detail sheets with embedded schedule boxes
8. Installation detail sheets

## Required outputs
Every region-like object must carry:
- `page_index`
- `sheet_id`
- `sheet_type`
- `region_id`
- `region_kind`
- `bbox`
- `confidence`
- `source_mode`
- `text`
- `parent_region_id` or hierarchy provenance
- `note_scope_status` when relevant
- `source_table_ids` if region is table-backed or overlaps table regions from Phase 1B

## Required integration with Phase 1B
Phase C must be explicitly table-aware:

- universal table regions participate in coarse region building
- table-backed blocks must not be reclassified as generic notes blobs
- legend/schedule/index/outlet-definition blocks should be regionized as distinct semantic regions
- local note blocks adjacent to table/detail frames should remain local
- page-global note columns should not be silently attached to local details

## Recommended implementation order
### Step 1 — Table-backed coarse regions
Use Phase 1B universal tables as coarse-region anchors in zoning.

### Step 2 — Header-aware semantic block splitter
Split complex pages using:
- boxed headers
- local titles
- local table bounds
- vertical separator logic
- section-level geometry

### Step 3 — Column-aware notes segmentation
Preserve multi-column notes/spec pages as distinct columns/blocks with reading order.

### Step 4 — Detail-frame clustering
Detect tiled detail frames and cluster them into pseudo-pages without mixing unrelated details.

### Step 5 — Note locality resolver
Explicitly separate:
- page-global notes
- column-local notes
- detail-local notes
- table-local notes

### Step 6 — Hard eval harness
Fail build if hard-page region fidelity metrics fall below target.

## Perfect Phase C target
- `required_region_kind_coverage = 1.0`
- `region_bbox_presence_rate = 1.0`
- `region_hierarchy_completeness_rate = 1.0`
- `locality_provenance_rate = 1.0`
- `global_vs_local_note_separation_rate >= 0.95`
- `detail_locality_reference_rate >= 0.95`
- `multi_column_preservation_rate >= 0.95`
- `pseudo_page_fragmentation_error_count = 0`
- `hybrid_page_overflatten_count = 0`
- `table_region_reuse_rate >= 0.95`
- `silent_note_scope_conflict_count = 0`

## Deliverables expected from implementation
- parser code changes
- hard-page eval report
- new focused tests
- no regressions in current parser suites
