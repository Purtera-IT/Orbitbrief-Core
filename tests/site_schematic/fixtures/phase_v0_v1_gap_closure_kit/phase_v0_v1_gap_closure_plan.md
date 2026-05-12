# Phase V0/V1 gap-closure implementation plan

## Current state
The integrated V0/V1 pass reports:
- modality_honesty_rate = 1.0
- current_pair_hard_page_modality_consistency = 1.0
- holdout_routing_completeness = 1.0
- vector_bbox_presence_rate = 1.0
- primitive_provenance_rate = 1.0
- primitive_graph_construction_rate = 1.0
- leader_candidate_presence_on_expected_pages = 1.0
- dimension_candidate_presence_on_expected_pages = 1.0
- packet_level_modality_failures = 0
- packet_level_primitive_graph_failures = 0

That is very good, but not automatically 10/10, because three trust gaps remain:

### Gap 1 — zero-primitive slip-through
At least one packet can route plausibly yet still yield zero meaningful vector primitives without being flagged.

### Gap 2 — density and dedup are under-audited
Raw primitive counts alone are not trustworthy:
- duplicated primitives
- over-segmentation
- isolated noise
can still hide inside a “successful” graph.

### Gap 3 — leader/dimension metrics are too weak
A page having one leader candidate is not the same as:
- a semantically plausible leader
- a usable dimension candidate

## The fix

### A. Suspicious zero-primitive guard
For each page and packet, if:
- modality is `vector_rich`
- OR modality is `hybrid` with high vector evidence
- AND raw/deduped/validated primitives are effectively zero
then flag:
- page-level suspicious zero-primitive
- packet-level primitive graph fail if repeated

This closes the “silent empty packet” hole.

### B. Primitive dedup / fusion pass
Add a deterministic dedup stage before graph assembly:
- group primitives by kind
- normalize bbox / endpoints
- collapse exact-near-duplicate lines/boxes/polylines
- retain provenance counts
- output:
  - raw primitive count
  - deduped primitive count
  - validated primitive count
  - dedup ratio

This makes primitive density meaningful.

### C. Primitive density audit
Per page and packet, compute:
- raw primitive density
- deduped primitive density
- validated primitive density
- isolated primitive ratio
- sparse graph flag
- overly dense graph flag

This helps detect:
- pages with too little geometry
- pages with too much noisy geometry

### D. Leader/dimension semantic-quality scoring
Replace simple presence metrics with stronger proxy metrics.

For leaders, score whether the candidate:
- is long enough
- has plausible aspect ratio
- terminates near text or a symbol candidate
- is not just a random short line
- optionally has arrowhead/leader geometry hints

For dimensions, score whether the candidate:
- has plausible dimension-line aspect
- is associated with nearby numeric text / measurement text
- has witness-line-like companions or orthogonal short-line support
- is not just any long line

Outputs:
- `leader_semantic_quality_rate`
- `dimension_semantic_quality_rate`

### E. Packet-level quality summaries
Per packet, compute:
- suspicious zero-primitive page count
- primitive density sanity
- dedup effectiveness
- leader semantic quality
- dimension semantic quality
- packet-level V0/V1 pass/fail

## Integration points
### `observations.py`
- attach raw vector primitives
- attach deduped primitives
- attach validated primitives
- attach primitive quality metadata

### `core.py`
- aggregate packet-level page quality rows
- compute suspicious zero-primitive flags
- export packet-level quality summary

### `vector_primitive_graph.py`
- build graph from deduped+validated primitives
- export graph density metrics

### `phase_v0_v1_eval.py`
- replace presence-only metrics with stronger semantic-quality metrics
- add packet-level fail gates

## Success targets
### Preserve
- production_kpi_regression_count = 0
- contradiction_lane_separation_rate = 1.0
- parser text/table coverage unchanged

### Hardened V0/V1 targets
- suspicious_zero_primitive_packet_failures = 0
- suspicious_zero_primitive_page_failures = 0
- primitive_dedup_effectiveness_rate >= 0.9
- primitive_density_sanity_rate >= 0.95
- leader_semantic_quality_rate >= 0.9
- dimension_semantic_quality_rate >= 0.85
- packet_level_primitive_graph_failures = 0

At that point V0/V1 are strong enough to stop polishing and move to V2.
