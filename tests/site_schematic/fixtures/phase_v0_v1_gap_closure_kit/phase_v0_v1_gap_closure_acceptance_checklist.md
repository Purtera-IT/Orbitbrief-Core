# V0/V1 gap-closure acceptance checklist

## Must preserve
- production_kpi_regression_count = 0
- contradiction_lane_separation_rate = 1.0
- parser text/table/legend coverage unchanged

## Must close
- suspicious_zero_primitive_packet_failures = 0
- suspicious_zero_primitive_page_failures = 0
- packet_level_primitive_graph_failures = 0

## Quality targets
- primitive_dedup_effectiveness_rate >= 0.9
- primitive_density_sanity_rate >= 0.95
- leader_semantic_quality_rate >= 0.9
- dimension_semantic_quality_rate >= 0.85

## Stop condition
Stop when V0/V1 no longer have silent empty-page or weak-metric loopholes and the next bottleneck is clearly V2.
