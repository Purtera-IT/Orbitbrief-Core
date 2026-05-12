# Universality Patch Kit v2

This kit is the **patch-style integration companion** to the vFinal universality fix kit.

It is meant for the exact repo state you reported:
- latest universality pass plateaued at A=7, B=7, C=5, D=2
- current pair remains protected
- the next parser-only push is:
  1. holdout-aware titleblock/sheet-archetype generalization
  2. column/locality fusion for Phase C
  3. holdout-aware table-family router
  4. optional bounded observation escalation only if still needed

## What this kit includes
- patch-style diffs for the exact repo files you are most likely modifying:
  - `classification/sheet_type.py`
  - `universal_table_spine.py`
  - `zoning/page_zones.py`
  - `core.py`
- add-file diffs for the new helper modules
- merge checklist
- holdout pass/fail worksheet for all 10 holdouts
- a Cursor prompt that tells Cursor how to apply these diffs semantically

## Important note
These diffs are **anchor-based integration diffs**, not guaranteed byte-perfect `git apply` patches.
They are designed for Cursor to:
- open the exact target file
- find the anchor function/import block
- merge in the change semantically

This is the safest way to use them given your repo may have drifted slightly since the packaged pass.
