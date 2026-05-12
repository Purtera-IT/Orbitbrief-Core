# Parser text perfection acceptance checklist

## Must preserve
- current pair canonical Phase B = perfect
- current pair canonical Phase C = perfect
- production_kpi_regression_count = 0
- contradiction_lane_separation_rate = 1.0

## Text perfection targets
- visible_text_coverage_estimate_avg >= 0.995
- note_spec_coverage_rate_avg >= 0.995
- unresolved_text_only_gap_rate_avg <= 0.002
- legend_table_coverage_rate_avg = 1.0
- semantic_lineage_coverage_rate_avg = 1.0
- parser_ready_for_vision_handoff_rate = 1.0

## Stop condition
Only stop when:
- remaining parser-side gaps are effectively graphics-only
or
- you can prove the exact last parser-only blockers honestly
