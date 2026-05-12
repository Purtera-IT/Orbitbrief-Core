# PDF-Native First Stage Report (2026-04-09)

1. files changed
- `src/orbitbrief_core/parser/site_schematic/observations.py`
- `src/orbitbrief_core/parser/site_schematic/models.py`
- `src/orbitbrief_core/parser/site_schematic/core.py`
- `src/orbitbrief_core/parser/site_schematic/zoning/page_zones.py`
- `src/orbitbrief_core/parser/site_schematic/__init__.py`
- `config/runtime/site_schematic_models.yaml`
- `tests/site_schematic/test_model_assisted_observations.py`
- `src/orbitbrief_core/parser/adapters/providers/paddleocr_vl_provider.py`
- `src/orbitbrief_core/parser/adapters/providers/pp_structure_provider.py`

2. what native/vector extractor(s) were used
- Primary extractor: PyMuPDF (`fitz`) PDF-native pass.
- Captured native word boxes via `page.get_text("words")`.
- Captured native text blocks via `page.get_text("dict")`.
- Captured vector/path metadata via `page.get_drawings()`.
- Source metadata marked as `source_mode=pdf_native`, `provider=fitz`.

3. what normalized observation structure now exists
- `SiteSchematicPageObservation` now includes:
  - `words: tuple[SiteSchematicWordObservation, ...]`
  - `layout_blocks: tuple[SiteSchematicLayoutBlockObservation, ...]`
  - `table_blocks: tuple[SiteSchematicTableObservation, ...]`
  - `vector_items: tuple[SiteSchematicVectorObservation, ...]`
  - `reading_order`, `page_text`, `provider`, `source_mode`, `confidence`, `metadata`
- Added:
  - `SiteSchematicWordObservation`
  - `SiteSchematicVectorObservation`

4. exactly where it plugs into site_schematic
- Observation builder entrypoint:
  - `build_site_schematic_page_observations(...)` in `site_schematic/observations.py`
- Pipeline insertion:
  - `build_site_schematic_bundle_from_router_input(...)` in `site_schematic/core.py`
- Consumed by decomposition seams:
  - `build_page_regions(..., page_observation=...)`
  - `build_nested_detail_regions(..., page_observation=...)`
  - `build_pseudo_pages(..., page_observation=...)`
  - `resolve_note_scope(..., page_observation=...)`

5. how it interacts with Docling
- Flow is now `pdf_native -> optional docling merge`.
- Native observations are always built first for PDFs.
- Docling enriches observations by adding high-value blocks/tables (deduped, bounded merge).
- Docling does not replace deterministic extraction or graph logic.
- Diagnostic winner is `pdf_native_docling` when merge is active.

6. results on the two PDFs
- `100643PLANSD-4.pdf`
  - Baseline: `regions=124`, `detail_regions=44`, `pseudo_pages=44`, `legend_entries=105`, `drawing_index_rows=34`
  - Native+Docling: `regions=166`, `detail_regions=56`, `pseudo_pages=56`, `legend_entries=105`, `drawing_index_rows=34`
  - Key page checks:
    - Page 1 sheet type preserved: `legend_symbol` -> `legend_symbol`
    - Page 1 pseudo-pages improved: `2 -> 1`
- `2026-01-19 CONSOLIDATED SET - SOUTHERN POST - T (1) (1) (1).pdf`
  - Baseline: `regions=76`, `detail_regions=85`, `pseudo_pages=85`, `legend_entries=80`, `drawing_index_rows=22`
  - Native+Docling: `regions=99`, `detail_regions=90`, `pseudo_pages=90`, `legend_entries=80`, `drawing_index_rows=22`
  - Key page checks:
    - Page 1 sheet type preserved: `notes_spec` -> `notes_spec`
    - Page 2 sheet type preserved: `legend_symbol` -> `legend_symbol`
    - Page 2 pseudo-pages reduced: `23 -> 8`
    - T700 pseudo-pages stable: `2 -> 2`
    - T900 pseudo-pages increased: `2 -> 9` (still noisy)

7. which pages improved most
- Wireless page 1 (TC001): better decomposition restraint (`2 -> 1` pseudo-pages) with sheet type preserved.
- Southern Post page 2 (T001): substantial over-segmentation reduction (`23 -> 8` pseudo-pages).
- Southern Post page 1 (T000): structure preserved; still heavy note density but not catastrophic decomposition.

8. whether mixed-detail decomposition got better inputs
- Yes, partially:
  - observation-driven decomposition is now gated to mixed-detail sheet types
  - confidence/role filtering caps observation-induced subregion explosion
- Remaining issue:
  - T900 still shows extra pseudo-page fragmentation (`2 -> 9`), so further tightening is needed.

9. what the next step should be after this
- Add selective Docling merge policy per sheet type:
  - strong merge for `notes_spec`, `legend_symbol`, `schedule_sheet`
  - conservative merge for `floorplan_detail`, `equipment_room_layout`, `installation_detail`
- Add bounded block budget and geometric clustering before `build_nested_detail_regions(...)`.
- Introduce lightweight native table segmentation for drawing-index/legend grids using words + vector rails.
- Add page-level confidence gate so heavy OCR escalation (Paddle) only runs on low-confidence native/docling pages.
