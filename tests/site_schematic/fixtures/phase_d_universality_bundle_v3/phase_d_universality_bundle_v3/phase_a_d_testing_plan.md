# Full Phase A-D testing plan (v3)

## Phase A — Observation + sheet typing + coarse zoning
Goal: prove parser can observe and classify each holdout packet at page/sheet/block level.
Metrics:
- sheet_type_accuracy >= 0.95
- observation_bbox_presence_rate = 1.0
- layout_block_recall >= 0.95
- provider_provenance_rate = 1.0
- title_block_detection_rate >= 0.95

## Phase B — Universal lossless table spine
Goal: preserve table -> row -> cell structure and force semantic lineage.
Metrics:
- required_table_kind_coverage = 1.0
- bbox_presence_rate = 1.0
- lineage_completeness_rate = 1.0
- semantic_row_reference_rate >= 0.95
- semantic_cell_reference_rate >= 0.95
- unflagged_row_cell_merge_split_count = 0

## Phase C — Region fidelity + locality
Goal: preserve mixed-page decomposition and note locality.
Metrics:
- required_region_kind_coverage = 1.0
- region_bbox_presence_rate = 1.0
- region_hierarchy_completeness_rate = 1.0
- locality_provenance_rate = 1.0
- global_vs_local_note_separation_rate >= 0.95
- detail_locality_reference_rate >= 0.95
- multi_column_preservation_rate >= 0.95
- table_region_reuse_rate >= 0.95
- hybrid_page_overflatten_count = 0
- pseudo_page_fragmentation_error_count = 0
- silent_note_scope_conflict_count = 0

## Phase D — Universality / holdout benchmark / contradiction readiness
Goal: prove parser generalizes across the 10 holdout packets and can remain contradiction-lane ready without polluting production paths.
Metrics:
- holdout_packet_pass_rate = 1.0
- cross_family_regression_count = 0
- production_kpi_regression_count = 0
- contradiction_lane_separation_rate = 1.0
- packet_registry_activation_honesty_rate = 1.0
- evidence_trace_completeness_rate >= 0.95

## Registry-level perfection
To call the stack universal for these two packet families:
- all 10 holdout packets must be downloaded and hydrated
- all 10 must pass A/B/C thresholds
- 0 production KPI regressions
- contradiction-rich packets remain isolated from production lanes
