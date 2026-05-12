# Phase V2 integration plan

## Objective
Build universal primitive symbol grounding on top of V0/V1.

## Inputs already available
- parser-complete text/legend/table/note outputs
- packet-local legend tables, outlet definitions, abbreviations, schedules
- V0 page modality decisions
- V1 vector primitives and primitive graph
- structure graph and locality
- topology extract seam

## Core V2 architecture

### Layer 1 — Universal primitive ontology
Represent symbols in packet-independent families:
- ap_wap_marker
- data_outlet_marker
- av_endpoint_marker
- room_scheduler_marker
- cctv_camera_marker
- door_contact_marker
- access_intercom_marker
- telecom_rack_front
- patch_panel_row
- ladder_rack_runway
- riser_endpoint
- conduit_pathway
- pull_or_junction_box
- pathway_support_symbol
- wall_phone_marker
- unknown_symbol_group

### Layer 2 — Candidate symbol grouping
Group V1 primitives into candidate symbol groups using:
- local primitive shape
- bbox
- clustering
- text hints
- sheet type / locality
- optional later raster proposals

### Layer 3 — Legend grounding dictionary
Build packet-local dictionaries from:
- legend entries
- outlet definitions
- abbreviations
- relevant note clauses
- text labels near symbol legend rows

### Layer 4 — Grounding resolver
Resolve each candidate against:
- legend dictionary
- family candidates
- nearby text hints
- sheet type
- locality context
- topology hints

Outputs:
- grounded symbol
- family
- packet-local semantic meaning
- supporting legend rows
- supporting text
- confidence
- status = grounded / ambiguous / unresolved

### Layer 5 — Graph integration
Add candidate and grounded symbol nodes/edges into the page structure graph and packet graph.

## Integration points
### `models.py`
Add:
- candidate symbol group contract
- legend grounding entry contract
- grounded symbol contract
- packet-level V2 summary contract

### `core.py`
Add:
- V2 orchestration after parser + V0/V1
- packet-level V2 diagnostics export

### `structure_graph.py`
Add:
- candidate symbol nodes
- grounded symbol nodes
- candidate->legend edges
- candidate->text association edges
- grounded symbol -> locality / topology hint edges

### `symbols/model_output_adapter.py`
Use as the future unification seam for vector/raster symbol candidates.

### `symbols/linker.py`
Augment or mirror with legend-grounded resolver behavior.

## Validation philosophy
Use the 12-packet corpus and per-packet gold schemas.

For each packet, the gold is not “exact page icon coordinates.”
The gold is:
- which schematic page types should emit candidates
- which packets should have legend grounding dictionaries
- what universal primitive families are expected in that domain
- what associations should be recoverable on those page classes

## Success targets
### Preserve
- parser text/table coverage unchanged
- V0/V1 metrics unchanged
- production regressions = 0
- contradiction lane separation = 1.0

### V2 starter
- candidate_symbol_grouping_rate >= 0.95
- grounded_symbol_provenance_rate = 1.0
- legend_grounding_dictionary_completeness >= 0.95 where legend pages exist
- candidate_to_legend_alignment_rate >= 0.9
- room_device_association_rate >= 0.9 where applicable
- connector_topology_candidate_rate >= 0.85 where applicable
- packet_level_v2_failures <= 2

### After hardening
- packet_level_v2_failures = 0
