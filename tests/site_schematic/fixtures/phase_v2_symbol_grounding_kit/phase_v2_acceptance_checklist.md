# Phase V2 acceptance checklist

## Must preserve
- parser text/table/legend coverage unchanged
- V0/V1 metrics unchanged
- production_kpi_regression_count = 0
- contradiction_lane_separation_rate = 1.0

## V2 starter targets
- candidate_symbol_grouping_rate >= 0.95
- grounded_symbol_provenance_rate = 1.0
- legend_grounding_dictionary_completeness >= 0.95 where applicable
- candidate_to_legend_alignment_rate >= 0.9
- room_device_association_rate >= 0.9 where applicable
- connector_topology_candidate_rate >= 0.85 where applicable
- packet_level_v2_failures <= 2

## Stop condition
Stop when V2 is integrated and measured across all 12 packets.
Next phase after that should be:
- raster fallback / segmentation
- stronger symbol detector training
- graphical topology semantics
