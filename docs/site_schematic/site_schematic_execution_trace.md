# Site Schematic Execution Trace (PDF/Image -> OrbitBrief Outputs)

This is the real execution path in the current repo, focused on `site_schematic_pdf` and `site_schematic_image`.

## 1) Artifact Intake and RouterInput Hydration

Files:

- `src/orbitbrief_core/parser/intake_preview.py`

Entrypoints:

- `hydrate_router_input(...)` and related intake helpers

Input shape:

- File path/bytes + metadata hints (for example `cad_hint`, `site_schematic_hint`)

Output shape:

- `RouterInput` with normalized text/bytes fields and metadata

Assumptions:

- Metadata hints are trustworthy enough to influence parse strategy.
- PDFs may need full-document text extraction when drawing/CAD hints are present.

Implementation type:

- Deterministic/rule-based (no heavy model semantics here).

---

## 2) Routing to Modality/Discourse Parse Plan

Files:

- `src/orbitbrief_core/parser/router.py`
- `config/runtime/parsers/parser_registry.yaml`

Entrypoints:

- `ParserRouter.route(router_input)`

Input shape:

- `RouterInput` from intake.

Output shape:

- `ParsePlan` with:
  - `modality` (for example `site_schematic_pdf`, `site_schematic_image`, or legacy CAD modalities),
  - `discourse_type`,
  - parser profile/strategy chain.

Assumptions:

- Regex/keyword signals and metadata hints can choose a useful modality.
- Ambiguous routing still degrades safely through fallback later.

Implementation type:

- Heuristic/rule-based routing + static config mapping.

---

## 3) Parser Registry Resolution and Adapter Construction

Files:

- `src/orbitbrief_core/parser/registry.py`
- `config/runtime/parsers/parser_registry.yaml`

Entrypoints:

- `ParserRegistry.resolve_spec(...)`
- `ParserRegistry.make_adapter(...)`

Input shape:

- `ParsePlan` modality + parser id.

Output shape:

- Concrete adapter instance (`SiteSchematicPdfAdapter` / `SiteSchematicImageAdapter` when routed there).

Assumptions:

- Registry YAML and code loader remain in sync.

Implementation type:

- Deterministic registry lookup.

---

## 4) Adapter Parse Stage (Where Site Bundle Is Attached)

Files:

- `src/orbitbrief_core/parser/adapters/site_schematic_pdf.py`
- `src/orbitbrief_core/parser/adapters/site_schematic_image.py`
- `src/orbitbrief_core/parser/adapters/cad_pdf.py`
- `src/orbitbrief_core/parser/adapters/cad_image.py`
- `src/orbitbrief_core/parser/adapters/cad_common.py`

Entrypoints:

- `SiteSchematicPdfAdapter.parse(...)`
- `SiteSchematicImageAdapter.parse(...)`

Input shape:

- `RouterInput`, `ParsePlan`, `compiled_pack`.

Output shape:

- `DocumentParse` with evidence spans + metadata, now including:
  - `metadata["site_schematic_bundle"]` (serialized `SiteSchematicBundle`),
  - `metadata["site_schematic_summary"]`,
  - `metadata["site_schematic_alias"]`.

Assumptions:

- Parent CAD adapter parse still provides useful base evidence (sheet refs, title/revision-like structures).
- Site schematic bundle build is safe to run as enrichment on top.

Implementation type:

- Mixed:
  - legacy CAD extraction is rule-based,
  - site bundle build is mostly heuristic/rule-based.

---

## 5) Site Schematic Core Build (Primary Lane Logic)

Files:

- `src/orbitbrief_core/parser/site_schematic/core.py`
- `src/orbitbrief_core/parser/site_schematic/models.py`

Entrypoints:

- `build_site_schematic_bundle_from_router_input(...)`

Input shape:

- `RouterInput` plus source modality hint.

Output shape:

- `SiteSchematicBundle` containing pages, regions, legends, abbreviations, outlet defs, rule objects, instances, links, topology objects, typed graph, and observations.

Internal stage assumptions:

- Page text can be extracted with enough fidelity for regex/token heuristics.
- Sheet typing and zoning are good enough to gate extractor families.
- Local page legend/notes are high-signal local truth.

Implementation type:

- Primarily deterministic heuristics + sheet-family specific rule extraction.

---

## 6) Page Classification and Zoning

Files:

- `src/orbitbrief_core/parser/site_schematic/classification/sheet_type.py`
- `src/orbitbrief_core/parser/site_schematic/classification/overlay_type.py`
- `src/orbitbrief_core/parser/site_schematic/zoning/page_zones.py`

Entrypoints:

- `extract_sheet_number(...)`
- `infer_sheet_title(...)`
- `classify_sheet(...)`
- `build_page_regions(...)`

Input shape:

- Per-page text and page index.

Output shape:

- Sheet type labels (`notes_spec`, `legend_symbol`, `floorplan_overall`, etc.).
- Region slices (`title_block_block`, `legend_block`, `plan_body_block`, etc.).

Assumptions:

- Lexical cues and sheet-number patterns are stable across drawings.

Implementation type:

- Heuristic (regex/keyword/position scoring).

---

## 7) Sheet-Family Extraction Passes

Files:

- `src/orbitbrief_core/parser/site_schematic/extractors/__init__.py`
- `src/orbitbrief_core/parser/site_schematic/extractors/common.py`
- `src/orbitbrief_core/parser/site_schematic/extractors/*_extractor.py`

Entrypoints:

- `extract_by_sheet_type(...)`
- family-specific functions like `extract_legend_sheet(...)`, `extract_floorplan_sheet(...)`, etc.

Input shape:

- Typed page object + zoned regions + raw/normalized text.

Output shape:

- `ExtractedPageArtifacts` fragments merged into bundle-level typed objects.

Assumptions:

- Sheet type routing is mostly correct.
- Per-family parser logic can rely on predictable local formatting patterns.

Implementation type:

- Rule-based extraction with confidence/status tagging.

---

## 8) Legend, Abbreviation, Outlet Definition Parsing

Files:

- `src/orbitbrief_core/parser/site_schematic/legends/legend_parser.py`
- `src/orbitbrief_core/parser/site_schematic/legends/abbreviation_parser.py`
- `src/orbitbrief_core/parser/site_schematic/legends/outlet_type_parser.py`

Entrypoints:

- `parse_legend_entries(...)`
- `parse_abbreviations(...)`
- `parse_outlet_type_definitions(...)`

Input shape:

- Legend-like text blocks and page context.

Output shape:

- Typed definition objects with primitive kind/category/status/confidence metadata.

Assumptions:

- Legend/control sheets express local semantics that should dominate grounding.

Implementation type:

- Rule-based pattern extraction; currently no YOLO/VLM primitive detector in this stage.

---

## 9) Symbol Detection and Grounding

Files:

- `src/orbitbrief_core/parser/site_schematic/symbols/detector.py`
- `src/orbitbrief_core/parser/site_schematic/symbols/linker.py`

Entrypoints:

- `detect_primitive_symbols(...)`
- `link_symbol_instances(...)`

Input shape:

- Page text, legend vocab, abbreviations, local notes/rooms.

Output shape:

- `SiteSchematicSymbolInstance[]`
- `SiteSchematicSymbolLink[]` with statuses like linked/weakly_linked/unresolved.

Assumptions:

- Token-level symbol proxies are present in OCR/text output.
- Nearby lexical context can proxy spatial grounding where bbox precision is weak.

Implementation type:

- Heuristic grounding/link scoring.

---

## 10) Site Schematic Typed Graph Build

Files:

- `src/orbitbrief_core/parser/site_schematic/graph/build_graph.py`

Entrypoints:

- `build_site_schematic_graph(...)` (invoked inside core bundle build)

Input shape:

- All typed bundle objects (pages, legends, rules, symbols, rooms, topology, etc.).

Output shape:

- `SiteSchematicGraph` with typed nodes/edges (`defined_by`, `located_in`, `routed_to`, `grounded_by`, etc.).

Assumptions:

- Object ids and cross-references are stable enough to form deterministic edges.

Implementation type:

- Deterministic graph construction.

---

## 11) Generic Parser Strategy + Graph + Packetization (Runtime Spine Path)

Files:

- `src/orbitbrief_core/parser/strategies/site_package.py`
- `src/orbitbrief_core/parser/graph_builder.py`
- `src/orbitbrief_core/parser/graph/cad_passes.py`
- `src/orbitbrief_core/parser/packetizer.py`

Entrypoints:

- strategy apply via runtime parse stack
- `build_graph(...)`
- packet build inside packetizer (`_build_cad_packets(...)` branch for CAD/site modalities)

Input shape:

- `DocumentParse` evidence spans and metadata.

Output shape:

- Graph-enriched parse + `PacketCandidate[]`.

Assumptions:

- CAD-oriented neighborhood heuristics are still valid for site-schematic packets.

Implementation type:

- Deterministic heuristic graph passes and anchor scoring.

---

## 12) Extractor Resolution and Claim Emission

Files:

- `src/orbitbrief_core/runtime_spine/extractors/registry.py`
- `src/orbitbrief_core/runtime_spine/extractors/runtime_impl.py`
- `src/orbitbrief_core/runtime_spine/extractors/narrative_extractor.py`
- `src/orbitbrief_core/runtime_spine/extractors/packet_to_claims.py`
- `src/orbitbrief_core/runtime_spine/extractors/cad_packet_to_claims.py`

Entrypoints:

- `resolve_extractor(...)`
- `run_narrative_extractor(...)`
- `extract_claims_from_packet(...)`

Input shape:

- packet candidates + runtime policy context.

Output shape:

- `InternalClaim[]` + `ExtractionDiagnostic[]` with evidence refs, status/confidence, verification flags.

Assumptions:

- Packet family labels and semantic guards are sufficient to keep claim emission bounded and auditable.

Implementation type:

- Deterministic bounded extraction with optional model assist hooks in CAD packet extraction.

---

## 13) Projection, Legality, and Downstream Contracts

Files:

- `src/orbitbrief_core/runtime_spine/extractors/narrative_projector.py`
- `src/orbitbrief_core/runtime_spine/postprocess/legality.py`
- `src/orbitbrief_core/runtime_spine/postprocess/normalizers.py`
- `src/orbitbrief_core/runtime_spine/postprocess/contradictions.py`
- `src/orbitbrief_core/runtime_spine/contracts.py`
- `src/orbitbrief_core/runtime_spine/package_pipeline.py`
- `src/orbitbrief_core/runtime_spine/package_joiner.py`

Entrypoints:

- `project_internal_claims_to_field_claims(...)`
- postprocess orchestration in `postprocess.py`
- `deterministic_mixed_package_join(...)`

Input shape:

- `InternalClaim[]` and extraction diagnostics.

Output shape:

- field claims and package-level joined facts with review flags/contradiction handling.

Assumptions:

- Contract policy tables and allowed field-path mappings are complete enough for selected claim families.

Implementation type:

- Deterministic and policy-driven.

---

## 14) Where Model-Backed Parsing Fits in This Trace

PDF parsing backend surfaces:

- `src/orbitbrief_core/parser/adapters/pdf_text.py`
- `src/orbitbrief_core/parser/adapters/pdf_ocr.py`
- `src/orbitbrief_core/parser/adapters/pdf_common.py`
- `src/orbitbrief_core/parser/adapters/arbitration.py`
- `src/orbitbrief_core/parser/adapters/pdf_page_judge.py`
- provider adapters in `src/orbitbrief_core/parser/adapters/providers/`

Site schematic model config wiring:

- `config/runtime/site_schematic_models.yaml`
- `src/orbitbrief_core/parser/site_schematic/config/model_registry.py`

Current practical state:

- Model seams are wired and configurable, but site schematic extraction still mostly operates as deterministic heuristics over text/regions and optional upstream OCR/PDF hypotheses.
