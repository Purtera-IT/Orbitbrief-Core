
# Phase V0/V1 Perfection Kit

This kit is the **hardening + perfection push** for the first graphics layer on the
`site_schematic` lane.

It is meant for the exact state you reported:
- V0/V1 architecture is correct
- fast 12-packet metrics already look very strong
- next goal is to turn that into **locked, packet-by-packet, auditable 10/10 quality**
- parser-only text/legend/table/note coverage is already effectively complete

## What this kit does
It upgrades V0/V1 from:
- a good first graphics foundation

into:
- a strict, packet-level validated graphics base

by adding:
1. modality calibration + honesty guards
2. vector primitive validation
3. primitive graph quality summaries
4. packet-level V0/V1 quality scoring
5. stricter eval criteria and packet-level targets

## Scope
This is still only:
- V0 = page modality router
- V1 = vector-native geometry extraction + primitive graph

It does NOT yet implement:
- symbol grounding
- raster fallback / segmentation
- graphical topology semantics
- VLM arbitration

Those come after V0/V1 are locked.
