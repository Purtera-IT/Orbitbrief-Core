# lv_d_iqaluit_operations_centre

## Packet label
LV-D Iqaluit Operations Centre

## Modality
low_voltage

## Priority order
6

## Why this order
A/C hybrid residual, but likely mostly title-block and bbox completion rather than deep structural failure.

## Current failures

- Phase A: sheet_type_accuracy=0.9872 < 1.0
- Phase B: none
- Phase C: region_bbox_presence_rate=0.9994 < 1.0

## Dominant likely root cause

Security-heavy public-sector title blocks drift slightly, and a single near-miss region lacks bbox completion.

## Packet-pattern hypothesis

Operations-centre packets mix security, communications, and public-sector sheet formatting. The parser is almost correct already, so this is likely one title-family alias plus one bbox completion hole.

## Best fix

- Add security/public-sector titleblock aliases
- Strengthen fallback sheet-family scoring for operations/security terms
- Complete region bbox from child/table anchors when recoverable

## Files to inspect first

- `src/orbitbrief_core/parser/site_schematic/classification/sheet_type.py`
- `src/orbitbrief_core/parser/site_schematic/residual_titleblock_profiles.py`
- `src/orbitbrief_core/parser/site_schematic/zoning/page_zones.py`
- `src/orbitbrief_core/parser/site_schematic/region_bbox_completion.py`

## Success condition

A pass and C pass on this packet.
