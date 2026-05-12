# Site Schematic Extraction Methods (Current Behavior + Model Upgrade Seams)

This document catalogs the extraction methods in `parser/site_schematic` and describes what each does today.

## 1) Classification and Page Decomposition

### Sheet type classification

Files:

- `src/orbitbrief_core/parser/site_schematic/classification/sheet_type.py`

Main methods:

- `extract_sheet_number(...)`
- `infer_sheet_title(...)`
- `classify_sheet(...)`

Detection goal:

- Assign each page to a sheet family (`index`, `legend_symbol`, `notes_spec`, `schedule`, `floorplan_overall`, `floorplan_detail`, `equipment_room_layout`, `riser_diagram`, `rack_detail`, `installation_detail`, etc.).

Signals:

- Sheet-number regexes, title tokens, keyword density.

Emitted structure:

- Sheet type labels and metadata used by downstream extractor dispatch.

Strengths:

- Fast and deterministic.
- Works on typical telecom drawing naming conventions.

Brittleness:

- OCR noise in sheet IDs/titles can misroute whole pages.
- Non-standard title block conventions reduce confidence.

Model upgrade seam:

- **Docling/Paddle** can provide stronger structural page understanding before classification.
- **Qwen (bounded)** can arbitrate only when deterministic confidence is low.

### Page zoning

Files:

- `src/orbitbrief_core/parser/site_schematic/zoning/page_zones.py`

Main method:

- `build_page_regions(...)`

Detection goal:

- Split page text into semantically meaningful blocks (title/revision/legend/notes/schedule/plan-body/detail/noise).

Signals:

- Position-like line ordering + cue phrases + block boundaries.

Emitted structure:

- `SiteSchematicRegion[]` with kind and source text.

Strengths:

- Enables sheet-family specific extraction.
- Keeps intermediate representation auditable.

Brittleness:

- Weak spatial fidelity when only text streams are available.
- Complex multi-column sheets can blur region boundaries.

Model upgrade seam:

- **PaddleOCR-VL** or layout-aware parsing for better region segmentation and reading order.

## 2) Legend and Definition Extraction

### Legend parser

Files:

- `src/orbitbrief_core/parser/site_schematic/legends/legend_parser.py`

Goal:

- Parse legend rows and derive symbol primitive meaning plus rule-like semantics.

Signals:

- Symbol tokens, legend delimiters, domain keywords.

Emitted objects:

- `SiteSchematicLegendEntry[]`

Strengths:

- Gives local semantic anchor for symbol grounding.

Brittleness:

- Dense legend tables with broken OCR rows can merge/split entries incorrectly.

Model upgrade seam:

- **Docling** table structure recovery; **YOLO** primitive detector to reconcile text legend with visual primitives.

### Abbreviation parser

Files:

- `src/orbitbrief_core/parser/site_schematic/legends/abbreviation_parser.py`

Goal:

- Parse abbreviation/meaning pairs and infer category (mounting/color/etc.).

Signals:

- Token shape, separator patterns, category keywords.

Emitted objects:

- `SiteSchematicAbbreviationEntry[]`

Strengths:

- Useful expansion vocabulary for symbol detector and note interpretation.

Brittleness:

- False positives from short uppercase tokens in unrelated regions.

Model upgrade seam:

- Better region confidence and table extraction upstream; limited **Qwen** classification assist for ambiguous abbreviations.

### Outlet type parser

Files:

- `src/orbitbrief_core/parser/site_schematic/legends/outlet_type_parser.py`

Goal:

- Parse structured cabling outlet definitions (cable count/type, terminations, mounting, power, remarks).

Signals:

- Outlet labels + field-like row patterns and cable/termination vocabulary.

Emitted objects:

- `SiteSchematicOutletTypeDefinition[]`

Strengths:

- Directly captures high-value implementation constraints.

Brittleness:

- Table alignment errors can scramble per-column attributes.

Model upgrade seam:

- **Docling** table normalization and confidence-weighted cell mapping.

## 3) Common Clause/Entity Extraction

Files:

- `src/orbitbrief_core/parser/site_schematic/extractors/common.py`

Core methods:

- `extract_note_clauses(...)`
- `extract_room_labels(...)`
- `extract_equipment_labels(...)`
- `extract_drawing_index_rows(...)`
- `build_structured_rule_sets(...)`
- clause classifiers (`classify_clause_type`, `classify_clause_status`)

Goals:

- Extract reusable entities/rules used across sheet families.

Signals:

- Regex and controlled vocab for room/equipment IDs, note syntax, index patterns, and requirement language.

Emitted objects:

- `SiteSchematicNoteClause`, room/equipment labels, `SiteSchematicDrawingIndexRow`, typed requirement/rule dataclasses.

Strengths:

- Centralized shared logic reduces extractor duplication.

Brittleness:

- Clause segmentation can over/under-split in noisy OCR.

Model upgrade seam:

- **Qwen bounded verifier** for clause typing only when deterministic classifier confidence is low.

## 4) Sheet-Family Extractors

Dispatcher:

- `src/orbitbrief_core/parser/site_schematic/extractors/__init__.py`
  - `extract_by_sheet_type(...)`

### Index sheet extractor

File:

- `extractors/index_sheet_extractor.py`

Goal:

- Capture drawing index rows and control-sheet references.

Primary output:

- `SiteSchematicDrawingIndexRow[]`

Strength:

- Good for downstream sheet cross-reference graph edges.

Brittle point:

- Non-tabular index formatting.

### Legend sheet extractor

File:

- `extractors/legend_sheet_extractor.py`

Goal:

- Pull legends, abbreviations, outlet definitions, and related note clauses.

Primary output:

- Legend/abbreviation/outlet typed objects.

Strength:

- High value when control sheets are clean.

Brittle point:

- OCR breaks symbol-description pairing.

### Notes/spec extractor

File:

- `extractors/notes_spec_extractor.py`

Goal:

- Extract spec clauses into structured requirement/rule families (termination, pathway, grounding, testing, labeling, responsibilities, etc.).

Primary output:

- `SiteSchematicNoteClause[]` + typed rule/requirement objects.

Strength:

- Captures most policy-level constraints needed by graph reasoning.

Brittle point:

- Long compound clauses with nested exceptions.

### Schedule extractor

File:

- `extractors/schedule_sheet_extractor.py`

Goal:

- Parse schedule table-like entries into device/outlet/rule-supporting attributes.

Primary output:

- Schedule-derived artifacts used to build instances/rules.

Strength:

- Structured extraction when table headers are recoverable.

Brittle point:

- Header drift and column shift in OCR text.

### Floorplan extractor

File:

- `extractors/floorplan_extractor.py`

Goal:

- Parse plan-body markers and labels (AP/WAP/CM/AV/CIP/CSP-like tokens), room associations, and pathway hints.

Primary output:

- Device/outlet candidates, room labels, note attachments.

Strength:

- Brings placement and local routing context into bundle.

Brittle point:

- Weak geometry and symbol collisions when no robust bbox layer exists.

### Riser extractor

File:

- `extractors/riser_extractor.py`

Goal:

- Extract topology/riser relationships and connectivity cues.

Primary output:

- `SiteSchematicRiserEdge[]`, `SiteSchematicTopologySegment[]`.

Strength:

- Captures trunk/homerun-like connectivity semantics.

Brittle point:

- Directionality and endpoint identity can be ambiguous.

### Equipment room extractor

File:

- `extractors/equipment_room_extractor.py`

Goal:

- Parse MDF/IDF/AV/TR room constraints, rack/cabinet references, environmental and grounding requirements.

Primary output:

- room/closet/rack objects plus associated requirements.

Strength:

- Strong alignment with low-voltage route requirements.

Brittle point:

- Dense room legends with mixed note blocks.

### Installation/detail extractor

File:

- `extractors/installation_detail_extractor.py`

Goal:

- Capture detail-sheet installation instructions (mounting, brackets, service loops, testing/labeling notes).

Primary output:

- rule/requirement objects linked to detail context.

Strength:

- High-value constraints often missed by coarse extraction.

Brittle point:

- Detail callouts can be fragmented by OCR line breaks.

## 5) Symbol Detection and Linking

### Primitive symbol detection

Files:

- `src/orbitbrief_core/parser/site_schematic/symbols/detector.py`

Main method:

- `detect_primitive_symbols(...)`

Goal:

- Detect symbol instances in page text and label with primitive kind.

Signals:

- Legend vocab + abbreviation vocab + token/context heuristics.

Output:

- `SiteSchematicSymbolInstance[]`

Strength:

- Uses local legend as vocabulary prior.

Brittleness:

- Text-only proxies miss pure graphical symbols.

Model seam:

- **YOLO** should become primary primitive detector with text-based fallback.

### Symbol grounding/linking

Files:

- `src/orbitbrief_core/parser/site_schematic/symbols/linker.py`

Main method:

- `link_symbol_instances(...)`

Goal:

- Link symbol instance -> legend definition -> nearby notes/rooms and mark linkage quality.

Signals:

- token similarity, local co-occurrence, note proximity, room label proximity.

Output:

- `SiteSchematicSymbolLink[]` statuses:
  - `linked`
  - `weakly_linked`
  - `unresolved`
  - (and conflict-like outcomes through diagnostic metadata)

Strength:

- Establishes grounded semantics, not just detection.

Brittleness:

- Similar symbol tokens and sparse local context produce over-linking.

Model seam:

- **Qwen bounded verifier** for disputed links only (abstain-allowed).

## 6) Graph Node/Edge Formation

Files:

- `src/orbitbrief_core/parser/site_schematic/graph/build_graph.py`
- plus bundle object builders in `core.py`

Goal:

- Convert typed extracted objects into a typed site-schematic graph.

Signals:

- explicit ids, shared references, inferred relation rules.

Output:

- `SiteSchematicGraphNode[]` and `SiteSchematicGraphEdge[]`
- edges like `defined_by`, `appears_on_sheet`, `located_in`, `routed_to`, `terminates_at`, `requires`, `grounded_by`, `derived_from_note`, `derived_from_legend`.

Strength:

- Rich typed relation surface with provenance hooks.

Brittleness:

- If upstream linking is weak, graph inherits uncertainty.

Model seam:

- Keep deterministic graph construction primary; use model only as advisory scorer for unresolved edges.

## 7) Confidence / Status / Unresolved Handling

Files:

- `site_schematic` models and linkers/extractors
- `runtime_spine/extractors/narrative_claim_ontology.py`
- `runtime_spine/postprocess/legality.py`

Current pattern:

- Extraction emits confidence + status metadata at object/claim level.
- Runtime claim layer enforces evidence references (`EvidenceRefSet`) and bounded statuses (`asserted`, `possible`, `ambiguous`, `needs_review`, etc.).
- Postprocess legality catches unsupported/invalid shapes and raises diagnostics/review flags.

Strength:

- Fail-closed behavior is present and explicit.

Remaining brittleness:

- Some unresolved/conflicting site-schematic graph outcomes still degrade into packet claims rather than first-class graph-level unresolved artifacts.

## 8) What Paddle/Docling/YOLO/Qwen Should Improve (Without Replacing Deterministic Core)

- **PaddleOCR-VL**: better page text/region fidelity, especially multi-column/detail sheets.
- **Docling**: robust table/block structure for legends, schedules, and outlet definitions.
- **YOLO**: visual primitive symbol detection, reducing text-proxy misses.
- **Qwen2.5-VL (bounded)**: verifier-only role for low-confidence classifications/links; no unconstrained claim generation.

Target principle:

- Deterministic extraction and graph remain source-of-truth.
- Models only improve ambiguous recognition/linking seams with abstain paths.
