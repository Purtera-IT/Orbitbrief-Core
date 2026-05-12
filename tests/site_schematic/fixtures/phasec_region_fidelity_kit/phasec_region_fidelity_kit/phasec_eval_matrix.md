# Phase C Hard Eval Matrix

## Core eval dimensions
1. Region kind coverage
2. Region bbox presence
3. Hierarchy completeness
4. Global vs local note separation
5. Multi-column preservation
6. Pseudo-page fragmentation
7. Table-region reuse from Phase 1B
8. Detail-locality reference integrity

## Suggested focused tests
- `tests/site_schematic/test_phasec_region_fidelity.py`
- `tests/site_schematic/phasec_region_fidelity_eval.py`

## Page-specific expectations
- `TC001`: hybrid control sheet split into semantic blocks
- `T000`: multi-column notes + drawing index
- `T001`: multiple separate legend matrices
- `T700`: many tiled pseudo-pages/detail frames
- `T900`: mixed equipment/rack/riser/embedded schedules
- `T901`: riser body + local callouts
- `T905`: detail frames + embedded schedule
- `T906`: installation detail locality
