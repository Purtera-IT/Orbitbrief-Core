# Site Schematic Performance Hardening Stage 2 (2026-04-09)

1. files changed
- `src/orbitbrief_core/parser/site_schematic/observations.py`
- `src/orbitbrief_core/parser/site_schematic/core.py`
- `src/orbitbrief_core/parser/site_schematic/zoning/page_zones.py`
- `src/orbitbrief_core/parser/site_schematic/models.py`
- `src/orbitbrief_core/parser/site_schematic/__init__.py`
- `config/runtime/site_schematic_models.yaml`
- `tests/site_schematic/test_observation_policy_hardening.py`
- `src/orbitbrief_core/parser/adapters/providers/paddleocr_vl_provider.py`
- `src/orbitbrief_core/parser/adapters/providers/pp_structure_provider.py`

2. exact provider policy implemented
- `pdf_native` observation is always first-pass for PDF pages.
- Page-level policy path is selected per page:
  - `native_only`
  - `native_docling_limited`
  - `native_docling_full`
- Aggressive Docling policy for:
  - `notes_spec`, `legend_symbol`, `schedule_sheet`
- Conservative policy for:
  - `floorplan_overall`, `floorplan_detail`, `equipment_room_layout`, `installation_detail`, `rack_detail`, `riser_diagram`
- Conservative sheets default to `native_only` unless mixed-detail table/ambiguity gate triggers limited merge.
- Optional benchmark override:
  - `observation_layer.force_docling_all_pages`

3. exact confidence gate logic
- Per-page native complexity metrics:
  - `native_block_count`
  - `native_table_count`
  - `native_word_count`
  - `table_density`
  - `ambiguity` (tiered by native block count)
- Path selection:
  - Aggressive sheets:
    - `native_docling_full` when high complexity/ambiguity (`block_count > 180` or ambiguity tier high)
    - else `native_docling_limited`
  - Conservative sheets:
    - `native_only` default
    - optional `native_docling_limited` only for mixed-detail with table/ambiguity trigger
  - Others:
    - limited merge only on complex pages.
- Page-level reason codes are recorded in diagnostics.

4. exact block budget logic
- Configurable budgets:
  - `native_block_budget`
  - `docling_limited_block_budget`
  - `docling_full_block_budget`
  - `mixed_detail_native_budget`
  - `mixed_detail_docling_budget`
- Budget is applied after merge:
  - Prioritize table + heading blocks, then body blocks.
  - Trim to budget while preserving reading order re-normalization.
- `block_budget_applied` recorded per page in diagnostics.

5. exact clustering logic
- New geometric clustering step before pseudo-page creation for mixed-detail sheet families.
- Triggered in `build_pseudo_pages(...)` for:
  - `equipment_room_layout`, `installation_detail`, `rack_detail`, `floorplan_detail`
- Clustering groups subregions by:
  - role similarity
  - bbox vertical adjacency/overlap
  - x-alignment tolerance
- Cluster cap: `max_clusters=8` for mixed-detail grouping.
- Pseudo-pages become cluster-derived (merged text + union bbox) with `clustering_applied` metadata.

6. exact native table/grid improvements
- Native extraction (`fitz`) now captures:
  - words with bboxes and reading order
  - block text from PDF dictionary
  - vector/path metadata from `get_drawings()`
- Table/grid detection improved via:
  - lexical table cues (`legend`, `schedule`, `drawing index`, separators)
  - vector-overlap grid score between text blocks and drawing boxes/lines
- Table candidates are normalized into `SiteSchematicTableObservation` + derived cell observations.

7. before/after runtime on two judgment PDFs
- Compared three modes:
  - baseline deterministic (`observation_layer.enabled=false`)
  - prior style (`force_docling_all_pages=true`, no practical budgets)
  - current selective policy

## 100643PLANSD-4.pdf
- baseline: `1.175s`
- always-merge(native+docling all pages): `135.374s`
- selective policy: `29.110s`
- improvement vs always-merge: ~`4.65x` faster

## Southern Post PDF
- baseline: `1.004s`
- always-merge(native+docling all pages): `97.075s`
- selective policy: `40.861s`
- improvement vs always-merge: ~`2.38x` faster

8. before/after pseudo-page counts for key pages
- Mode comparison shown as `baseline / always-merge / selective`.

## 100643PLANSD-4.pdf
- Page 1 (wireless control/legend): `2 / 1 / 1`
- Page 2: `1 / 1 / 1`

## Southern Post PDF
- Page 1 (`T000` notes/spec): `2 / 3 / 2` (typing preserved)
- Page 2 (`T001` legend): `23 / 1 / 8` (much less fragmented than baseline)
- `T700` page: `2 / 1 / 2` (stays stable in selective path)
- `T900` page: `1 / 3 / 6` (selective still fragmented, but reduced from prior stage spike of 9)

9. test results
- `pytest tests/site_schematic/test_mixed_detail_decomposition.py -q` -> pass
- `pytest tests/site_schematic/test_subregion_dispatch.py -q` -> pass
- `pytest tests/site_schematic/test_note_scope_resolution.py -q` -> pass
- `pytest tests/site_schematic/test_graph_subregion_edges.py -q` -> pass
- `pytest tests/site_schematic/test_phase2_pdf_smoke.py -q` -> pass
- `pytest tests/site_schematic/test_gold_pdf_eval.py -q` -> 2 fail, 1 pass
  - failing assertions:
    - wireless `graph_expectations_match`
    - Southern Post exact anchor `color_cables`
- New focused hardening tests:
  - `pytest tests/site_schematic/test_observation_policy_hardening.py -q` -> pass

10. remaining weak spots
- Gold-eval graph/anchor expectations still have residual misses (not hard crashes):
  - wireless graph expectations
  - Southern Post color-cable exact anchor
- `T900` selective pseudo-pages remain higher than ideal (`6`), though reduced from prior-stage over-fragmentation.
- Docling load still dominates selective runtime on aggressive pages; further page-budgeting and symbol/table precision tuning would help.

11. whether this stage is now ready for the lightweight layout-model tier
- **Yes, conditionally ready**:
  - Provider policy, gating, budgets, clustering, and diagnostics are now in place.
  - Deterministic path remains authoritative and non-breaking.
  - Runtime is materially better than always-merge policy.
  - Remaining gaps are quality tuning issues (not architecture blockers), so this is a suitable base for a lightweight layout-model escalation tier.
