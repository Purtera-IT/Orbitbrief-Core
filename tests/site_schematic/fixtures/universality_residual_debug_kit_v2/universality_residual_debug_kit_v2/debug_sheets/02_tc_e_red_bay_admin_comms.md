# tc_e_red_bay_admin_comms

## Packet label
TC-E Red Bay High School Admin communications

## Modality
telecom

## Priority order
2

## Why this order
Same fix family as TC-D and likely a second fast A+C lift.

## Current failures

- Phase A: sheet_type_accuracy=0.8333 < 1.0, title_block_detection_rate=0.8333 < 0.95
- Phase B: none
- Phase C: region_bbox_presence_rate=0.991 < 1.0

## Dominant likely root cause

Admin-building communications sheets have slightly different titleblock/footer labeling and sparse mixed plan regions missing bbox completion.

## Packet-pattern hypothesis

Administrative school packets often share sheet-family language with telecom/security but use nonstandard footer/title rail structure. Sparse regions on plan/detail sheets are close to valid and likely need deterministic bbox completion only.

## Best fix

- Reuse the school/admin titleblock profile family from TC-D with minor alias additions
- Strengthen footer/title-rail extraction
- Complete missing region bboxes from child/detail/table anchors

## Files to inspect first

- `src/orbitbrief_core/parser/site_schematic/classification/sheet_type.py`
- `src/orbitbrief_core/parser/site_schematic/residual_titleblock_profiles.py`
- `src/orbitbrief_core/parser/site_schematic/zoning/page_zones.py`
- `src/orbitbrief_core/parser/site_schematic/region_bbox_completion.py`

## Success condition

A pass and C pass on this packet with no current-pair regression.
