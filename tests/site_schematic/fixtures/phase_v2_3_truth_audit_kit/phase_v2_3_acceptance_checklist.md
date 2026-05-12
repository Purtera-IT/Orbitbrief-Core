# Phase V2.3 truth-audit acceptance checklist

## Must preserve
- production_kpi_regression_count = 0
- contradiction_lane_separation_rate = 1.0
- V0/V1 stable
- parser text/table/legend coverage unchanged

## Truth-repair targets
- empty_required_hardpage_packet_failures = 0
- suspicious_uniform_grounding_packet_failures = 0
- impossible_connector_success_packet_failures = 0
- impossible_room_assoc_packet_failures = 0
- truth_audit_failures_total = 0

## Strong-enough V2 targets
- grounding_state_honesty_rate >= 0.95
- grounded_symbol_yield_rate >= 0.35
- hardpage_grounded_symbol_yield_rate >= 0.5
- room_device_association_rate >= 0.4
- connector_grounding_quality_rate >= 0.6
- packet_hardpage_semantics_rate >= 0.75

## Stop condition
Stop when V2 is evidence-backed and no longer relying on fake-perfect metrics.
