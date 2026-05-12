# lv_a_aspen_house_telecom_intercom_risers

## Packet label
LV-A Aspen House telecom + intercom risers

## Modality
low_voltage

## Priority order
3

## Why this order
One B-only failure and likely one of the easier table-family alias fixes.

## Current failures

- Phase A: none
- Phase B: required_table_kind_coverage=0.75 < 1.0
- Phase C: none

## Dominant likely root cause

Hospitality/intercom riser packet uses table families that are semantically obvious to humans but still under-routed by the holdout table-family matcher.

## Packet-pattern hypothesis

Telecom/intercom riser packets often combine drawing-index/spec pages with hospitality-style equipment/riser schedules and intercom terminology that is not captured strongly enough by current table signatures.

## Best fix

- Add hospitality/intercom riser aliases for schedule/spec and drawing-index families
- Strengthen header + row-token routing for intercom / telecom riser schedule tables
- Reduce fallback to generic_grid when 'schedule/spec/index' evidence is already present

## Files to inspect first

- `src/orbitbrief_core/parser/site_schematic/universal_table_spine.py`
- `src/orbitbrief_core/parser/site_schematic/table_kind_aliases_residual.py`

## Success condition

B pass on this packet with current-pair Phase 1B still perfect.
