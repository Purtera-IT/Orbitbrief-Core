# Phase V2.5 acceptance checklist

## Must preserve
- production_kpi_regression_count = 0
- contradiction_lane_separation_rate = 1.0
- V0/V1 stable
- parser text/table/legend coverage unchanged

## Must hit
- expected_family_grounded_coverage_rate >= 0.75
- hardpage_family_grounded_coverage_rate >= 0.8
- hardpage_requirement_truth_rate = 1.0
- hardpage_grounded_symbol_yield_rate >= 0.65
- packet_level_v2_failures = 0
- truth_audit_failures_total = 0

## Stop condition
Stop when V2 is no longer failing because of unrealistic family targets or empty hard-page truth holes.
