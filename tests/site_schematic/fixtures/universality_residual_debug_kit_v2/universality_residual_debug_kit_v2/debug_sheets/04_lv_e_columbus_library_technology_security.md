# lv_e_columbus_library_technology_security

## Packet label
LV-E Columbus Library technology/security

## Modality
low_voltage

## Priority order
4

## Why this order
Another B-only packet that should respond to targeted security/tech table-family aliases.

## Current failures

- Phase A: none
- Phase B: required_table_kind_coverage=0.6667 < 1.0
- Phase C: none

## Dominant likely root cause

Door-control / technology-security rough-in packet uses schedule/legend/spec structures that are underclassified by the current table-kind router.

## Packet-pattern hypothesis

Technology/security drawings often use door-control, patch-panel, IT-room, and rough-in schedule blocks whose headers differ from telecom/hospitality defaults.

## Best fix

- Add door-control / technology-security aliases for schedule/spec and legend-like tables
- Strengthen symbol-legend vs schedule disambiguation on security-heavy packets
- Promote technology/security schedule signatures before generic_grid fallback

## Files to inspect first

- `src/orbitbrief_core/parser/site_schematic/universal_table_spine.py`
- `src/orbitbrief_core/parser/site_schematic/table_kind_aliases_residual.py`

## Success condition

B pass on this packet with current-pair Phase 1B still perfect.
