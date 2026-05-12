# Phase V2.1 perfection plan

## Current state
V2 first pass is strong:
- candidate grouping exists
- legend grounding dictionary is complete
- provenance is complete
- packet-level failures are 0

But it is not yet fully trustworthy because:

### Gap 1 — unresolved vs ambiguous discipline
`unresolved_symbol_total = 0` with `ambiguous_symbol_total = 120` suggests the system may be converting weak cases into ambiguity too aggressively instead of preserving stronger fail-closed abstention.

### Gap 2 — connector / linework-aware meaning
Connector-focused packets still show weaker connector density / connector-quality behavior.
This means symbol meaning is not yet strongly enough conditioned on:
- connector continuity
- leader attachment
- riser path role
- rack/runway/pathway relation
- equipment-detail linework context

### Gap 3 — packet-level hard-page semantics
The V2 evaluation is still strongest on:
- candidate grouping
- legend alignment
- room/device association

It needs harder gates on the most meaningful page types per packet:
- one control/legend page
- one riser page
- one equipment/rack page
- one installation/detail page
- one plan page with real symbol/linework interaction

## Goal
Push V2 toward “universally honest and graph-ready” across the 12-packet corpus.

## The fixes

### A. Grounding-state policy
Add explicit deterministic policy for:
- `grounded`
- `ambiguous`
- `unresolved`
- `candidate_requires_review`

Do not force weak symbol matches into `ambiguous` when they should stay `unresolved`.

Rules should consider:
- legend match strength
- connector evidence
- room/device association
- sheet-type compatibility
- page-type compatibility
- note/label support

### B. Connector / linework-aware refinement
Add additive refinement where linework/connector evidence can strengthen or weaken grounding:
- riser endpoint candidates attached to riser continuity
- rack/pathway/runway candidates attached to connector clusters
- device markers attached to leader lines or room/device anchors
- detail callouts with local leader attachment

### C. Legend text association
Strengthen local legend mapping by:
- normalizing legend text
- aliasing note text + legend text jointly
- allowing packet-local semantics to override global weak priors
- supporting unseen glyph styles via legend-local text semantics

### D. Packet hard-page gates
For every packet, require V2 to produce trustworthy output on at least:
- one control/legend page if present
- one riser page if present
- one equipment/rack page if present
- one installation/detail page if present
- one plan page with symbol/linework interaction if present

## Integration points
### `models.py`
Add:
- grounding state policy results
- connector evidence contracts
- hard-page V2 summary contracts

### `core.py`
Add:
- packet-level hard-page selection
- V2 packet-level hard-page summary
- diagnostics export

### `semantic_mapper.py`
Add:
- text normalization / aliasing helpers
- legend + note text fusion

### `grounding_resolver.py`
Add:
- state policy
- connector-aware scoring
- unresolved vs ambiguous logic

### `structure_graph.py`
Add:
- connector/leader adjacency exposure where available
- graph-ready candidate associations

### `phase_v2_eval.py`
Add:
- hard-page packet gates
- state-honesty metrics
- connector-grounding quality metrics

## Success targets
### Preserve
- current pair parser and V0/V1 stability
- production regressions = 0
- contradiction lane separation = 1.0

### V2.1 targets
- grounding_state_honesty_rate >= 0.95
- ambiguous_symbol_total materially reduced or rebalanced by honest unresolved counts
- unresolved_symbol_total > 0 only when justified, not forced to 0
- connector_grounding_quality_rate >= 0.9
- packet_hardpage_semantics_rate >= 0.9
- packet_level_v2_failures = 0
