
# Universality Fix Kit vFinal

This is the **vFinal parser-only universality push kit** for the `site_schematic` lane.

It is designed for the exact plateau you reported:
- Holdout Phase A: 7/10
- Holdout Phase B: 7/10
- Holdout Phase C: 5/10
- Holdout Phase D packet pass: 2/10
- production_kpi_regression_count = 0

## Goal
Move the parser from:
- "excellent on the benchmark pair"
to
- "strongly generalized on the 10 holdouts"

without touching OrbitBrief logic or destabilizing production truth paths.

## Core strategy
This kit uses a **two-tier plan**:

### Tier 1 — Deterministic plateau breakers
1. Universal title-block / sheet-archetype profiles
2. Shared column-structure fusion for mixed notes pages
3. Holdout-aware table-family router
4. Conservative integration into A/B/C

### Tier 2 — Bounded layout-native escalation
If Tier 1 still does not hit target:
- enable targeted layout-native observation escalation only for residual long-tail pages
- do NOT replace the parser
- do NOT open a heavy path globally

## Contents
- `implementation_plan_vfinal.md`
- `cursor_prompt_vfinal_universality_push.txt`
- `integration_prompt_vfinal.txt`
- `acceptance_checklist_vfinal.md`
- `target_metrics_vfinal.json`
- `plateau_gap_analysis_vfinal.json`
- `code/...` starter implementation modules
- `tools/run_universality_vfinal.sh`

## Honest note
This kit includes **substantial starter code**, but it still needs integration into your live repo.
The included code is designed to minimize the amount Cursor needs to invent.
