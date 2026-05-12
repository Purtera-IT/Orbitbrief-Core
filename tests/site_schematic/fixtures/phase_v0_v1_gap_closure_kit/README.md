
# Phase V0/V1 Gap Closure Kit

This kit is the **targeted hardening pass** for the three remaining issues keeping V0/V1 from a true 10/10:

1. one suspicious zero-primitive packet slipping through
2. primitive density / dedup quality not yet audited enough
3. leader/dimension metrics are presence metrics, not semantic quality metrics

It is built as a **surgical follow-up** to the existing V0/V1 integration and perfection passes. It does **not** introduce V2. It closes the last V0/V1 trust gaps so V2 can start on a clean base.

## Design principles
- keep current-pair parser truth path frozen
- keep contradiction-lane separation untouched
- keep V0 vector-first architecture intact
- do not add a heavy raster fallback yet
- add packet-level and page-level sanity guards
- add auditable density/dedup metrics
- replace weak "presence-only" leader/dimension metrics with stronger semantic-quality proxies

## What this kit adds
- suspicious zero-primitive packet/page sanity logic
- primitive dedup/fusion helpers
- primitive density audit helpers
- leader/dimension semantic-quality scorers
- patch-style diffs for the likely repo files
- stricter V0/V1 eval targets
- a Cursor prompt that says do not stop until the three trust gaps are closed or precisely explained

## Why these changes
The archaeology pass showed the right integration points for Phase V live in:
- `core.py`
- `observations.py`
- `models.py`
- `structure_graph.py`
- `topology_extract.py`
- V0/V1 eval harness
and the old stack is a reusable hybrid scaffold, not dead code. That means the best next move is to harden the current vector-first stack at those seams rather than rebuild it. 
