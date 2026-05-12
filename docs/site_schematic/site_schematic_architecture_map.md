# OrbitBrief Core Site Schematic Architecture Map

This document maps the current `site_schematic` lane as implemented today in OrbitBrief Core. It is intentionally concrete and code-path oriented.

## 1) System Positioning (Current Reality)

- The runtime is still **parser-runtime + packet-extractor** oriented.
- `site_schematic` exists as a first-class parser namespace under `parser/site_schematic/`.
- `cad_*` still participates in the execution path and is not fully reduced to wrappers.
- `site_schematic` structured outputs are produced (bundle + graph), but downstream claim generation is still packet-family oriented and not yet graph-native.

## 2) Top-Level Entry Points

Primary runtime entrypoints:

- `src/orbitbrief_core/runtime_spine/pipeline.py`
  - `run_pipeline()`
  - `parse_extract_and_postprocess()`

Parser runtime entrypoints:

- `src/orbitbrief_core/parser/runtime.py`
  - `run_parser_runtime()`
  - `parse_and_packetize()`

Router + registry entrypoints:

- `src/orbitbrief_core/parser/router.py`
  - `ParserRouter.route()`
- `src/orbitbrief_core/parser/registry.py`
  - `ParserRegistry.resolve_spec()`
  - `ParserRegistry.make_adapter()`

Site schematic adapter entrypoints:

- `src/orbitbrief_core/parser/adapters/site_schematic_pdf.py`
  - `SiteSchematicPdfAdapter.parse()`
- `src/orbitbrief_core/parser/adapters/site_schematic_image.py`
  - `SiteSchematicImageAdapter.parse()`

Site schematic core entrypoint:

- `src/orbitbrief_core/parser/site_schematic/core.py`
  - `build_site_schematic_bundle_from_router_input()`

## 3) Package/Module Map

### Runtime spine and parser orchestration

- `src/orbitbrief_core/runtime_spine/`
  - `pipeline.py` (end-to-end orchestration)
  - `fallback.py` (extract/intake_only/park decisions)
  - `extractors/` (packet->claim conversion and projection)
  - `postprocess/` (legality, normalizers, contradictions)
  - `contracts.py` (typed runtime contracts)

- `src/orbitbrief_core/parser/`
  - `intake_preview.py` (artifact hydration / early parsing hints)
  - `router.py` (modality/discourse routing)
  - `registry.py` (adapter/spec resolution)
  - `runtime.py` (adapter+strategy+graph+packet pipeline)
  - `graph_builder.py` and `graph/` (generic graph passes)
  - `packetizer.py` (anchor-first packet building)

### Site schematic lane

- `src/orbitbrief_core/parser/site_schematic/`
  - `core.py` (main lane orchestrator)
  - `models.py` (typed dataclasses: pages, regions, legends, rules, instances, graph, bundle)
  - `classification/`
    - `sheet_type.py` (sheet identity/type inference)
    - `overlay_type.py` (overlay/tag inference)
  - `zoning/page_zones.py` (region decomposition)
  - `legends/`
    - `legend_parser.py`
    - `abbreviation_parser.py`
    - `outlet_type_parser.py`
  - `extractors/`
    - `index_sheet_extractor.py`
    - `legend_sheet_extractor.py`
    - `notes_spec_extractor.py`
    - `schedule_sheet_extractor.py`
    - `floorplan_extractor.py`
    - `riser_extractor.py`
    - `equipment_room_extractor.py`
    - `installation_detail_extractor.py`
    - `common.py` (shared extraction utilities)
  - `symbols/`
    - `detector.py` (primitive symbol detection)
    - `linker.py` (legend/note/room grounding)
  - `graph/build_graph.py` (site-schematic typed graph assembly)
  - `projection/orbitbrief_projection.py` (bundle projection helper)
  - `config/model_registry.py` (model-provider wiring)

### Related legacy CAD modules that still touch this lane

- `src/orbitbrief_core/parser/adapters/cad_pdf.py`
- `src/orbitbrief_core/parser/adapters/cad_image.py`
- `src/orbitbrief_core/parser/adapters/cad_common.py`
- `src/orbitbrief_core/parser/graph/cad_passes.py`
- `src/orbitbrief_core/parser/graph/cad_signals.py`
- `src/orbitbrief_core/runtime_spine/extractors/cad_packet_to_claims.py`

## 4) Routing and Registration Layer

Static registry config:

- `config/runtime/parsers/parser_registry.yaml`
  - Includes `site_schematic_pdf_v1` and `site_schematic_image_v1`.
  - Maps to `SiteSchematicPdfAdapter` / `SiteSchematicImageAdapter`.
  - Uses `site_package` strategy for CAD/site drawings.

- `config/runtime/extractors/extractor_registry.yaml`
  - Includes `ps_site_schematic_v1` for `drawing_packet` role and `site_schematic_*` modalities.

Router behavior:

- `ParserRouter` classifies container type and discourse profile from `RouterInput`.
- Hint signals (`cad_hint`, `site_schematic_hint`) influence routing.
- Drawing-like PDFs/images generally route into drawing/CAD-family modalities where `site_schematic_*` is now available.

## 5) Site Schematic Data Model Surface

Core model container:

- `SiteSchematicBundle` in `parser/site_schematic/models.py`

Main typed families inside bundle:

- Page and zoning:
  - `SiteSchematicPage`
  - `SiteSchematicRegion`
- Legend and definitions:
  - `SiteSchematicLegendEntry`
  - `SiteSchematicAbbreviationEntry`
  - `SiteSchematicOutletTypeDefinition`
- Notes and requirement/rule artifacts:
  - `SiteSchematicNoteClause`
  - rule/requirement dataclasses for mounting, termination, grounding, testing, labeling, pathway, service loop, responsibility, etc.
- Symbols and placed entities:
  - `SiteSchematicSymbolInstance`
  - `SiteSchematicSymbolLink`
  - `SiteSchematicDeviceInstance`
  - `SiteSchematicOutletInstance`
- Spatial/topology:
  - `SiteSchematicRoom`
  - `SiteSchematicCloset`
  - `SiteSchematicRack`
  - `SiteSchematicRiserEdge`
  - `SiteSchematicTopologySegment`
- Graph:
  - `SiteSchematicGraph`
  - `SiteSchematicGraphNode`
  - `SiteSchematicGraphEdge`
- Diagnostics/observations:
  - `SiteSchematicObservation`

## 6) High-Level Execution Graph (Current)

1. `run_pipeline()` receives artifact + metadata.
2. `run_parser_runtime()` routes, resolves parser spec, and invokes adapter parse.
3. `SiteSchematic*Adapter.parse()`:
   - runs parent CAD adapter parse (legacy evidence surface),
   - then builds `site_schematic_bundle` via `build_site_schematic_bundle_from_router_input()`,
   - injects bundle dict + summary into parse metadata.
4. Parser strategy (`site_package`) enriches evidence/edges.
5. Generic graph builder runs pass stack (including `CadStructuralPass` for CAD/site-like modalities).
6. Packetizer builds packet candidates from graph/evidence neighborhoods.
7. Extractor registry resolves extractor for `drawing_packet`.
8. Narrative extractor converts packets to internal claims, using CAD-aware packet extractors where packet families are CAD-like.
9. Projector maps internal claims to field claims.
10. Deterministic postprocess runs legality, normalization, dedupe, contradiction/review handling.
11. Package-level join reconciles claims across artifacts.

## 7) What Is Heuristic vs Model-Backed Today

- Strongly heuristic/rule-based today:
  - sheet typing, zoning, legend/abbreviation/outlet parsing,
  - symbol detection/linking,
  - many extractors and graph edge formation.
- Optional model seams exist:
  - `pdf_text.py`, `pdf_ocr.py`, `pdf_common.py` providers (Docling/Paddle/etc),
  - `pdf_page_judge.py` for hard-page arbitration,
  - bounded Qwen assist in CAD packet extraction path.
- Site schematic lane itself currently behaves mostly deterministic with lexical/regex/geometric heuristics.

## 8) Intended Boundary vs Current Boundary

Intended:

- OrbitBrief consumers should rely on grounded site-schematic graph/projection objects.

Current:

- Runtime still heavily claim/packet-oriented; `site_schematic_bundle` is attached in metadata and partially projected, but not yet the sole downstream truth boundary.
