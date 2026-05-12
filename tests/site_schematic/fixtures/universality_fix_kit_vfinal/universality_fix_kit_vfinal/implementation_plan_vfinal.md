# Universality Fix vFinal — implementation plan

## Current plateau
- Holdout A = 7/10
- Holdout B = 7/10
- Holdout C = 5/10
- Holdout D = 2/10
- Production regressions = 0

## Diagnosis
### Phase A residual blockers
- title-block drift
- sheet-number extraction ambiguity
- family alias drift on unfamiliar packets

### Phase B residual blockers
- table-family under-coverage on unfamiliar legend/schedule/index/spec formats
- too much fallback to `generic_grid`
- insufficient section-aware routing for holdouts

### Phase C primary blockers
- multi-column note preservation on unfamiliar layouts
- locality provenance on mixed pages
- global-vs-local note separation drift
- detail locality reference drift

## Why a new shared structural layer still matters
The prior structure graph pass was integrated conservatively and preserved stability, but did not move counts.
The likely reason is not that the idea is wrong, but that it wasn't connected tightly enough to:
- holdout archetype typing
- column-aware note scoping
- table-family routing
- residual long-tail observation ambiguity

## vFinal architecture
### Layer 1: Holdout-aware deterministic generalization
- `holdout_titleblock_profiles.py`
- `column_structure_fusion.py`
- `table_family_router_holdouts.py`

### Layer 2: Residual-page layout-native escalation (bounded)
- `observation_escalation_policy.py`
- only for pages that remain ambiguous after deterministic signals
- never global by default

## Implementation order

### Pass 1: deterministic plateau breakers
1. Integrate holdout titleblock profiles into `classification/sheet_type.py`
2. Integrate column structure fusion into `zoning/page_zones.py`
3. Integrate table-family router into `universal_table_spine.py`
4. Re-run current pair + holdout universality eval

### Pass 2: targeted layout-native escalation
Only if Pass 1 still leaves:
- A < 9/10
- B < 9/10
- C < 8/10

Enable escalation policy in `core.py` for residual pages only:
- pages with low archetype confidence
- pages with low table-family confidence
- pages with multi-column ambiguity
- pages with unresolved locality conflicts

### Pass 3: packet-by-packet residual cleanup
After the above, patch only archetype-family or page-family residuals.
Do not do packet-specific hacks unless impossible to avoid.

## Success targets

### After Pass 1
- A >= 8/10
- B >= 8/10
- C >= 7/10
- D > 2/10
- production regressions = 0

### After Pass 2
- A >= 9/10
- B >= 9/10
- C >= 8/10
- D >= 5/10
- production regressions = 0

### Final perfection target
- A = 10/10
- B = 10/10
- C = 10/10
- D = 10/10
- production regressions = 0
- contradiction-lane separation = 1.0
- evidence trace completeness >= 0.98
