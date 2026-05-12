# lv_b_300_progress_communications

## Packet label
LV-B 300 Progress communications

## Modality
low_voltage

## Priority order
7

## Why this order
Likely the hardest remaining B residual because coverage is only 0.5; save for after the easier B wins.

## Current failures

- Phase A: none
- Phase B: required_table_kind_coverage=0.5 < 1.0
- Phase C: none

## Dominant likely root cause

Mixed communications/security packet likely contains the most unfamiliar table-family signatures and therefore falls back to generic_grid too often.

## Packet-pattern hypothesis

Public-safety / station communications packets often mix security node access, communications room details, and rough-in/spec tables in ways that look table-like but do not match current signature families strongly enough.

## Best fix

- After fixing the easier B packets, inspect this packet’s exact missed table kinds
- Add targeted table aliases for public-safety comms/security schedule families
- Strengthen section-header + row-token fusion before generic_grid fallback

## Files to inspect first

- `src/orbitbrief_core/parser/site_schematic/universal_table_spine.py`
- `src/orbitbrief_core/parser/site_schematic/table_kind_aliases_residual.py`
- `possibly extractor routing if a specific semantic family still bypasses the table spine`

## Success condition

B pass on this packet after the easier B residuals are already fixed.
