# Site Schematic Gap Assessment (Current vs Intended Architecture)

This compares current implementation to the intended target:

- site_schematic-first
- first-class zoning/sheet typing/legend grounding/symbol grounding
- typed provenance-aware graph
- unresolved/conflict first-class outputs
- OrbitBrief consuming graph-projected outputs
- clean seams for Paddle/Docling/YOLO/Qwen

## 1) Scorecard

### 1. Are we truly site_schematic-first yet?

Current:

- **Partially**. `site_schematic` lane exists and produces rich typed bundle+graph.
- Runtime still relies heavily on CAD adapters, CAD graph passes, and CAD packet claim extraction.

Gap:

- Site-schematic graph is not yet the sole authoritative extraction boundary in runtime.

### 2. Is page zoning first-class?

Current:

- **Yes, functionally**. Dedicated zoning module and typed region objects are present.

Gap:

- Region quality depends on text-only/heuristic segmentation; spatial fidelity can degrade on hard layouts.

### 3. Are legends treated as local truth?

Current:

- **Mostly yes**. Legend, abbreviations, and outlet definitions are explicit extractors and feed symbol detection/linking.

Gap:

- Disambiguation under noisy OCR needs stronger structural/table support and dispute handling.

### 4. Are extractors sheet-type specific?

Current:

- **Yes**. Family-specific extractors are implemented and dispatched by sheet type.

Gap:

- Misclassification upstream can route to wrong extractor family; fallback strategy is still heuristic-heavy.

### 5. Is the graph typed and provenance-aware?

Current:

- **Yes at site-schematic graph level** (`SiteSchematicGraphNode/Edge`, observations, object IDs).
- **Partially in runtime contract level** via evidence refs/packet metadata.

Gap:

- Downstream consumption is still claim-centric; graph provenance is not uniformly preserved as first-class external contract.

### 6. Is unresolved/conflicting output first-class?

Current:

- **Partially**. Status/confidence/review flags and diagnostics exist; linkers can mark unresolved states.

Gap:

- Need stronger graph-native unresolved/conflict contract outputs, not only claim-level review flags.

### 7. Is OrbitBrief downstream of graph yet?

Current:

- **Not fully**. OrbitBrief runtime path still goes packet -> claim -> field claim as primary.
- Site-schematic graph exists but is not yet primary consumed artifact.

Gap:

- Build graph-first projection contract and make claims a derivative view.

### 8. Are model integration seams clean?

Current:

- **Good seam placement**:
  - OCR/PDF providers and arbitration,
  - model registry config,
  - bounded assist hooks.

Gap:

- Need explicit arbitration hooks in site-schematic internals (classification/linking) with abstain-safe behavior.

### 9. Is repo organization clean enough for model hookup?

Current:

- **Mostly yes** in `parser/site_schematic/*` layout.

Gap:

- Runtime still split across site-schematic and CAD legacy surfaces, which can duplicate logic and blur ownership.

## 2) Strong Areas Right Now

- Dedicated `site_schematic` namespace with typed object model.
- Clear extractor-family split by sheet type.
- Explicit legend/abbreviation/outlet parser modules.
- Explicit symbol detection and linker modules.
- Typed site-schematic graph builder with semantic edge types.
- Deterministic legality/postprocess and evidence-ref enforcement in runtime spine.

## 3) Main Architecture Gaps

### A) Authority boundary gap (biggest)

- Site-schematic graph is not yet authoritative downstream boundary.
- Claim packet pipeline remains dominant for output contracts.

### B) Legacy coupling gap

- CAD adapters/passes/extractor remain load-bearing in drawing flow.
- Site-schematic lane is additive rather than fully replacing lane-specific CAD logic.

### C) Provenance and unresolved contract gap

- Internal provenance is rich, but external shared contracts do not yet expose full graph-level unresolved/conflict objects.

### D) Layout robustness gap

- Zoning/classification/symbol grounding still mostly text-heuristic and sensitive to OCR artifacts.

## 4) What Must Happen Before Model Hookup

1. Freeze graph-first contract shape for site-schematic output.
2. Build deterministic mapper from `SiteSchematicBundle/Graph` to shared contract objects.
3. Keep compatibility claims as secondary projection, not primary truth.
4. Add tests that assert graph/provenance/status outputs directly (not only text/claim presence).
5. Reduce CAD duplication by delegating lane-specific logic through site-schematic modules.

## 5) Model Hookup Sequence (Recommended)

1. **PaddleOCR-VL + Docling**:
   - Improve page text/layout/region/table fidelity.
   - Keep deterministic extractors unchanged except for cleaner inputs.
2. **YOLO primitive detector**:
   - Replace text-proxy symbol detection as primary detector.
   - Keep heuristic detector as fallback.
3. **Qwen verifier (bounded)**:
   - Use only for low-confidence classification/link disputes.
   - Require abstain path and deterministic fallbacks.

## 6) Concrete Exit Criteria for “Site-Schematic-First”

- Runtime contracts can be generated directly from site-schematic graph (with full provenance/status/unresolved support).
- CAD lane code for this path reduced to compatibility facades.
- Gold wireless and low-voltage routes pass against structured graph+contract assertions.
- Legacy downstream consumers still work through compatibility projections.
