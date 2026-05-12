# Final text-tail acceptance checklist

## Must preserve
- current pair canonical Phase B = perfect
- current pair canonical Phase C = perfect
- production_kpi_regression_count = 0
- contradiction_lane_separation_rate = 1.0
- legend_table_coverage_rate_avg = 1.0
- semantic_lineage_coverage_rate_avg = 1.0

## Final text-tail targets
- remaining text_only_gap pages = 0
- unresolved_text_only_gap_rate_avg <= 0.001
- note_spec_coverage_rate_avg >= 0.998
- parser_ready_for_vision_handoff_rate = 1.0

## Stop condition
Stop only when those 4 residual pages are fixed or when you can prove any remaining issue is actually graphics/mixed and not a parser-text miss.
