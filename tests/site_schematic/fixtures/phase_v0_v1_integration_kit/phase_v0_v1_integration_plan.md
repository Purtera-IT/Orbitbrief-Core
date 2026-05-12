# Phase V0/V1 integration plan

## Objective
Build the first graphics-native layer on top of the finished parser.

## V0 — Page modality router
Every page should be classified into:
- `vector_rich`
- `hybrid`
- `raster_heavy`

### Inputs
- PDF text density
- vector path count
- image count
- line-art density
- table/legend presence
- sheet type
- optional title-block / notes-spec clues

### Why
Vector-rich engineering pages should go through vector-native geometry extraction first.
Raster-heavy pages should be reserved for later vision fallback.

### Outputs
Per page:
- `page_modality`
- `page_modality_confidence`
- routing reasons
- diagnostics counts:
  - vector path count
  - image count
  - text density
  - table count
  - line-art density proxy

## V1 — Vector-native geometry extraction

### For vector-rich / hybrid pages
Extract:
- lines
- polylines
- boxes
- circles
- arrows
- callout leaders
- connectors
- room/device marker geometry
- dimension lines where present

### Output
A geometric primitive graph with:
- primitive nodes
- junction nodes
- leader/callout edges
- connector edges
- candidate dimension edges
- provenance / bbox / page index / source mode

## Integration points
### `core.py`
- build V0 routing after observations/universal tables exist
- store modality decisions in diagnostics/model registry
- pass vector-rich/hybrid routing into observation stage

### `observations.py`
- extract PDF-native drawings for vector-rich/hybrid pages
- normalize into vector primitive objects
- attach to per-page observation objects

### `structure_graph.py`
- add vector primitive nodes / edges into the existing page structure graph

### `topology_extract.py`
- consume primitive graph hints conservatively
- do not break current topology semantics
- only add additive V1 hints

### `models.py`
Add first-class contracts for:
- page modality decision
- vector primitives
- vector junctions
- vector primitive graph
- dimension candidates

## Delivery order
1. Add new models
2. Add page modality router module
3. Patch core to compute/store modality
4. Add vector primitive extractor module
5. Patch observations to ingest vector drawings
6. Patch structure graph to host vector primitive nodes/edges
7. Patch topology extract to consume vector primitive hints
8. Add helper tests
9. Add V0/V1 eval harness

## Success criteria
### V0
- current pair hard pages classified plausibly
- holdout pages routed honestly
- no false vector-rich claims on raster-heavy pages

### V1
- vector-rich pages produce primitives with bbox/provenance
- leaders/connectors/dimensions appear where present
- graph/junction structure is auditable
- no production parser regressions
