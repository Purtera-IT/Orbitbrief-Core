# tc_b_seele_es_refresh_dwgs

## Packet label
TC-B Seele ES Refresh DWGs

## Modality
telecom

## Priority order
5

## Why this order
Likely a tiny C-only edge case after the major C gains; a fast cleanup candidate.

## Current failures

- Phase A: none
- Phase B: none
- Phase C: locality_provenance_rate=0.9953 < 1.0

## Dominant likely root cause

One or two note/legend-adjacent objects are getting scoped correctly but still missing a locality id field after fallback routing.

## Packet-pattern hypothesis

Hybrid legend/WAP pages can classify note scope correctly yet fail strict locality completeness if column-local or subregion-local paths do not backfill parent locality ids.

## Best fix

- Backfill missing locality ids from matched column/region/pseudo context after scope decision
- Add a strict completeness pass for scoped note links
- Treat this as provenance completion, not a new zoning rewrite

## Files to inspect first

- `src/orbitbrief_core/parser/site_schematic/zoning/page_zones.py`
- `src/orbitbrief_core/parser/site_schematic/region_bbox_completion.py`

## Success condition

C pass on this packet with no other metric movement.
