# Phase V2.1 acceptance checklist

## Must preserve
- production_kpi_regression_count = 0
- contradiction_lane_separation_rate = 1.0
- V0/V1 metrics remain within current locked range
- parser text/table/legend coverage unchanged

## V2.1 trust targets
- grounding_state_honesty_rate >= 0.95
- connector_grounding_quality_rate >= 0.9
- packet_hardpage_semantics_rate >= 0.9
- packet_level_v2_failures = 0

## Stop condition
Stop when V2 no longer relies on optimistic ambiguity and is strong enough on hard pages that the next major missing layer is V3:
- raster fallback / segmentation
- richer graphical topology semantics
