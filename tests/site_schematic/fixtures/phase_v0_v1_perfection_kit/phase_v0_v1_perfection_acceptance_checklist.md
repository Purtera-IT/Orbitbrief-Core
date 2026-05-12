# Phase V0/V1 perfection acceptance checklist

## Must preserve
- production_kpi_regression_count = 0
- contradiction_lane_separation_rate = 1.0
- parser text/table/legend coverage unchanged

## V0 perfection
- modality_honesty_rate = 1.0
- current_pair_hard_page_modality_consistency = 1.0
- holdout_routing_completeness = 1.0
- packet-level modality failures = 0

## V1 perfection
- vector_bbox_presence_rate = 1.0
- primitive_provenance_rate = 1.0
- primitive_graph_construction_rate = 1.0
- leader_candidate_presence_on_expected_pages >= 0.95
- dimension_candidate_presence_on_expected_pages >= 0.9
- packet-level primitive graph failures = 0

## Stop condition
Stop when the next bottleneck is clearly V2:
- symbol grounding
- raster fallback
- graphical semantics
