# tc_d_appalachian_gym_comms

## Packet label
TC-D Appalachian School New Gym communications

## Modality
telecom

## Priority order
1

## Why this order
Fixing this packet likely lifts both Phase A and Phase C at once.

## Current failures

- Phase A: sheet_type_accuracy=0.75 < 1.0, title_block_detection_rate=0.75 < 0.95
- Phase B: none
- Phase C: region_bbox_presence_rate=0.9863 < 1.0

## Dominant likely root cause

School-style communications title/footer rail is drifting from current titleblock profiles, and one or more sparse regions are emitted without bbox completion.

## Packet-pattern hypothesis

Simpler school communications sheets often put the strongest sheet label in footer/title rails instead of the canonical title block. Mixed plan/detail pages can leave sparse regions with no bbox when child geometry is weak.

## Best fix

- Add school/admin communications titleblock profile and footer-title fallback scoring
- Prefer footer rail / title rail tokens when canonical titleblock evidence is weak
- Run bbox completion from child/detail/table anchors for sparse regions

## Files to inspect first

- `src/orbitbrief_core/parser/site_schematic/classification/sheet_type.py`
- `src/orbitbrief_core/parser/site_schematic/residual_titleblock_profiles.py`
- `src/orbitbrief_core/parser/site_schematic/zoning/page_zones.py`
- `src/orbitbrief_core/parser/site_schematic/region_bbox_completion.py`

## Success condition

A pass and C pass on this packet with no current-pair regression.
