# Universality Next Steps Kit

This kit is a **planning/integration pack** for the next parser-only universality push on the
`site_schematic` lane.

## Current state
Your latest universality generalization pass improved:
- Holdout Phase A: 2 -> 4 passes
- Holdout Phase B: 3 -> 5 passes
- Holdout Phase C: 0 -> 1 passes
- Production-pair KPI regression count: 2 -> 0

That means:
- evaluator alignment is fixed enough
- the current pair are protected again
- universality is still blocked mainly by **Phase C**:
  - locality provenance
  - multi-column note preservation
  - global-vs-local note separation
  - detail locality references

Secondary blockers remain:
- Phase A sheet/archetype drift on unfamiliar title blocks / sheet labels
- Phase B table-kind under-coverage and semantic lineage routing on unfamiliar layouts

## Best next move
Do **not** jump to OrbitBrief work or giant end-to-end model rewrites.
The best next move is:

1. **Phase D-next / Phase C universality generalization**
2. **Phase D-next / Phase A residual sheet-archetype generalization**
3. **Phase D-next / Phase B residual table-kind routing generalization**
4. Re-run all 10 holdouts
5. Decide whether stronger model upgrades are actually needed

## What "perfect" means
### Immediate next-pass target
- production current-pair stays perfect / unchanged
- holdout Phase A pass count >= 6/10
- holdout Phase B pass count >= 7/10
- holdout Phase C pass count >= 5/10
- production_kpi_regression_count = 0
- contradiction_lane_separation_rate = 1.0
- evidence_trace_completeness_rate >= 0.95

### Final universality target
- current pair remain perfect
- holdout Phase A pass count = 10/10
- holdout Phase B pass count = 10/10
- holdout Phase C pass count = 10/10
- holdout packet pass rate >= 0.9, then 1.0
- no truth-path contamination
- no fake contradiction inflation

## Contents
- `phase_d2_phasec_generalization_plan.md`
- `phase_d2_cursor_prompt_phasec_generalization.txt`
- `phase_d3_cursor_prompt_phasea_sheet_archetypes.txt`
- `phase_d4_cursor_prompt_phaseb_table_routing.txt`
- `universality_gold_targets.json`
- `universality_acceptance_checklist.md`
- `integration_prompt_master.txt`

Use the **Phase C prompt first**.
