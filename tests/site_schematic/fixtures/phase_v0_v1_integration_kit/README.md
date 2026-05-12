
# Phase V0/V1 Integration Kit

This kit packages the **planning, starter code, patch-style diffs, benchmark registry, and gold-schema scaffolding**
for the next graphics phase of the `site_schematic` lane.

## Why now
The parser-only text/legend/table/note phase is effectively complete enough to hand off to graphics.
The next bottleneck is:
- page modality routing
- vector-native geometry extraction
- geometric primitive graph building
- vector-first symbolic/topological interpretation

## Built from the archaeology results
This kit is grounded in the completed vision-code archaeology pass, which found:
- 80 relevant files across 7 clusters
- 41 immediately reusable files
- 19 reusable-with-refactor
- 19 reference-only
- 1 dangerous legacy reuse item
- best Phase V integration points in:
  - `site_schematic/core.py`
  - `site_schematic/observations.py`
  - `site_schematic/models.py`
  - `site_schematic/structure_graph.py`
  - `site_schematic/topology_extract.py`
  - `site_schematic/symbols/model_output_adapter.py`

## What this kit contains
- `phase_v0_v1_integration_plan.md`
- `phase_v0_v1_cursor_prompt.txt`
- `phase_v0_v1_integration_prompt.txt`
- `phase_v0_v1_acceptance_checklist.md`
- `phase_v0_v1_target_metrics.json`
- `phase_v0_v1_gold_schema_master.json`
- `phase_v0_v1_eval_matrix.md`
- `phase_v0_v1_registry_seed.json`
- `gold_packet_schemas/` for the 12 corpus packets
- starter code modules for:
  - page modality routing
  - vector primitive extraction
  - vector primitive graph
  - vector measurement scaffolding
- helper tests
- patch-style diffs for:
  - `core.py`
  - `observations.py`
  - `structure_graph.py`
  - `topology_extract.py`
  - `models.py`

## Scope
This is Phase V0/V1 only:
- V0 = page modality router
- V1 = vector-native geometry extraction

It does NOT yet implement:
- full raster vision fallback
- final symbol grounding
- final linework topology reasoning
- full VLM verifier loop

Those come after the V0/V1 base is in place.
