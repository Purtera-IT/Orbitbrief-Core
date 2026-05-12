# Phase V2.4 grounding-enforcement acceptance checklist

## Must preserve
- production_kpi_regression_count = 0
- contradiction_lane_separation_rate = 1.0
- V0/V1 stable
- parser text/table/legend coverage unchanged

## Must hit
- expected_family_grounded_coverage_rate >= 0.75
- hardpage_family_grounded_coverage_rate >= 0.8
- room_device_evidence_truth_rate >= 0.9
- connector_evidence_truth_rate >= 0.9
- hardpage_requirement_truth_rate = 1.0
- hardpage_grounded_symbol_yield_rate >= 0.65
- grounding_state_honesty_rate >= 0.95
- packet_level_v2_failures = 0
- truth_audit_failures_total = 0

## Stop condition
Stop only when V2 is both strong and honest:
- enough family coverage
- enough grounded yield
- evidence-backed room/device truth
- evidence-backed connector truth
- real hard-page enforcement
