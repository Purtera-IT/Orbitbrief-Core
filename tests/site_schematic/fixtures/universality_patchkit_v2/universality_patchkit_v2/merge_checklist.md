# Merge checklist

## Order
1. Add new helper modules:
   - `holdout_titleblock_profiles.py`
   - `column_structure_fusion.py`
   - `table_family_router_holdouts.py`
   - `observation_escalation_policy.py`
2. Patch `classification/sheet_type.py`
3. Patch `universal_table_spine.py`
4. Patch `zoning/page_zones.py`
5. Patch `core.py` conservatively
6. Add helper tests
7. Re-run current pair canonical eval
8. Re-run full holdout Phase D universality eval

## Guardrails
- Current pair canonical Phase B must remain perfect
- Current pair canonical Phase C must remain perfect
- `production_kpi_regression_count` must remain 0
- `contradiction_lane_separation_rate` must remain 1.0

## Pass goals
### Pass 1
- A >= 8/10
- B >= 8/10
- C >= 7/10

### Pass 2 (if needed)
- A >= 9/10
- B >= 9/10
- C >= 8/10

## What to inspect first if counts do not move
- Phase C: multi-column note preservation, locality provenance, page-global vs local note scope
- Phase A: title-block drift and sheet family aliasing
- Phase B: generic_grid overuse and weak table-family routing

## What not to do
- do not touch OrbitBrief logic
- do not touch contradiction truth paths
- do not open a heavy model path globally
