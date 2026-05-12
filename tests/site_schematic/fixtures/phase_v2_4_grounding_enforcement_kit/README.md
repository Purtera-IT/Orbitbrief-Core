
# Phase V2.4 Grounding Enforcement Kit

This is the **final grounding-enforcement / anti-dodge kit** for V2 on the `site_schematic` lane.

It is built around the four things that still matter most:

1. `expected_family_grounded_coverage_rate`
2. room/device evidence truth
3. connector evidence truth
4. hard-page fail counting truth

The purpose of this kit is not to make the numbers look perfect.
The purpose is to make V2 **actually earn** good numbers.

## What this kit adds
- explicit family-coverage enforcement
- explicit evidence-backed room/device truth
- explicit evidence-backed connector truth
- explicit hard-page fail counting truth
- anti-default / anti-autopass checks
- per-packet and per-hard-page quality reporting
- patch-style diffs and starter modules so Cursor cannot dodge the intended fixes

## Philosophy
A packet may only “pass” V2.4 if:
- required hard pages are truly non-empty when those page families exist
- grounded symbols cover enough of the expected family space
- room/device association booleans are backed by real evidence
- connector grounding booleans are backed by real evidence
- no packet is passing via empty-set or default-true loopholes

## Expected outcome
The result may be less pretty than fake 1.0 metrics.
That is okay.
We want **honest, enforceable grounding quality** for your two domains.
