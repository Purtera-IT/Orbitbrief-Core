# Phase V2.2 acceptance checklist

## Must preserve
- production_kpi_regression_count = 0
- contradiction_lane_separation_rate = 1.0
- V0/V1 stable
- parser text/table/legend coverage unchanged

## Must hit
- grounding_state_honesty_rate >= 0.95
- grounded_symbol_yield_rate >= 0.6
- hardpage_grounded_symbol_yield_rate >= 0.75
- unresolved_symbol_ratio <= 0.4
- room_device_association_rate >= 0.75
- connector_grounding_quality_rate >= 0.9
- expected_family_grounded_coverage_rate >= 0.8
- packet_hardpage_semantics_rate >= 0.9
- packet_level_v2_failures = 0

## Stop condition
Stop when V2 is no longer mostly unresolved and the next major missing layer is V3:
- raster fallback / segmentation
- richer graphical semantics
