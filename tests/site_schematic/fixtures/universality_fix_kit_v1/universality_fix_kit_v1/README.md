
# Universality Fix Kit v1

This kit is a **parser-only universality push** package for the `site_schematic` lane.

It is designed for the exact state you reported:
- current pair remains strong / canonical
- holdout pass counts improved materially
- the biggest remaining blocker is **Phase C** generalization
- secondary blockers are **Phase A** sheet-archetype drift and **Phase B** table-kind drift

## What this kit gives you
1. A **full implementation plan** for the next universality pass
2. A **detailed Cursor prompt**
3. An **acceptance checklist**
4. **Final target metrics**
5. A **starter implementation** for the shared structural graph layer:
   - `structure_graph.py`
   - `structure_graph_sheet_hints.py`
   - `structure_graph_table_router.py`
   - `structure_graph_locality.py`
   - tests

## Why this is the right next move
The latest universality pass reached:
- Holdout Phase A: 7/10
- Holdout Phase B: 7/10
- Holdout Phase C: 5/10
- Holdout D: 2/10

That means the parser architecture is working, but full universality still needs:
- shared page-structure reasoning
- generalized note locality and multi-column logic
- generalized archetype drift reduction
- generalized table-kind routing

## Honest note
This kit includes **most of the new code for the structural-graph approach**, but it is not a blind drop-in patch for your repo. It still needs integration into your existing:
- `classification/sheet_type.py`
- `universal_table_spine.py`
- `zoning/page_zones.py`
- `core.py`

That integration work is what the included Cursor prompt is for.

## Recommended order
1. Add the new structural graph modules
2. Integrate Phase C locality first
3. Integrate Phase A sheet-archetype hints
4. Integrate Phase B table-kind routing
5. Re-run full holdout suite
