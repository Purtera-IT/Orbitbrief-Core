# Universality fix implementation plan

## Objective
Move from:
- A: 7/10
- B: 7/10
- C: 5/10
- D: 2/10

toward:
- A: 9+/10
- B: 9+/10
- C: 8+/10
- D: materially above 2/10

without regressing the current pair.

## Why a shared structural graph
Right now, A/B/C still act too independently:
- sheet typing sees headers/titles
- table routing sees grid/table candidates
- locality sees notes/details/pseudo-pages

The universal fix is to unify:
- section headers
- columns
- tables
- detail frames
- pseudo-pages
- note scopes
into one shared page-structure representation.

Then:
- Phase A reads sheet/header/section evidence from that graph
- Phase B reads table/section relations from that graph
- Phase C reads locality/column/detail relationships from that graph

## Proposed files to integrate
### New modules
- `code/src/orbitbrief_core/parser/site_schematic/structure_graph.py`
- `code/src/orbitbrief_core/parser/site_schematic/structure_graph_sheet_hints.py`
- `code/src/orbitbrief_core/parser/site_schematic/structure_graph_table_router.py`
- `code/src/orbitbrief_core/parser/site_schematic/structure_graph_locality.py`

### Existing modules to patch
- `src/orbitbrief_core/parser/site_schematic/core.py`
- `src/orbitbrief_core/parser/site_schematic/classification/sheet_type.py`
- `src/orbitbrief_core/parser/site_schematic/universal_table_spine.py`
- `src/orbitbrief_core/parser/site_schematic/zoning/page_zones.py`

## Integration order

### Step 1 — build the structure graph in `core.py`
Build once per page after observations and universal tables exist.
Inputs:
- page observations / layout blocks
- universal tables
- coarse regions
- detail regions / subregions / pseudo-pages if available

Output:
- `page_structure_graph`
- attach to bundle diagnostics and optionally page metadata

### Step 2 — Phase C first
Use the structure graph for:
- column inference
- note locality classification
- page-global vs detail-local vs column-local routing
- mixed-page locality decisions

This is the highest-leverage change because Phase C is still the main blocker.

### Step 3 — Phase A
Use structure-graph section/header evidence to:
- rerank sheet-id candidates
- score archetype families
- reduce title-block drift

### Step 4 — Phase B
Use structure graph to:
- map section headers to table families
- split multi-table pages more cleanly
- reduce `generic_grid` overuse
- improve unfamiliar schedule/index/spec routing

## Acceptance logic
- Current pair canonical lanes remain perfect
- Holdout A >= 9/10
- Holdout B >= 9/10
- Holdout C >= 8/10
- production regression count remains 0
- contradiction lane separation remains 1.0
- evidence trace completeness >= 0.95

## Stop condition
If after this pass:
- Phase C stays below 8/10
- or A/B stall badly

then stronger layout-native observation/model upgrades are justified.
