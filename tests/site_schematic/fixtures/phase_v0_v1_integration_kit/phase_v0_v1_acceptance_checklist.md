# Phase V0/V1 acceptance checklist

## Must preserve
- current-pair canonical parser behavior remains stable
- production_kpi_regression_count = 0
- contradiction_lane_separation_rate = 1.0
- parser text/table/legend coverage remains unchanged

## V0 targets
- modality_honesty_rate >= 0.98
- current-pair hard-page modality consistency = 1.0
- holdout routing completeness = 1.0

## V1 targets
- vector_bbox_presence_rate = 1.0
- primitive_provenance_rate = 1.0
- primitive_graph_construction_rate >= 0.95
- leader_candidate_presence_on_expected_pages >= 0.9
- dimension_candidate_presence_on_expected_pages >= 0.8

## Stop condition
Stop after V0/V1 is integrated and measured.
Next phase after that should be:
- symbol grounding
- raster fallback / segmentation
- graphical topology reasoning
