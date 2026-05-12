
# Phase V2.2 Gap-Closure Kit

This kit targets the exact remaining V2 weaknesses identified in the audited results:

1. hard-page semantics metric is too forgiving
2. grounding-state policy is too conservative to be useful
3. room/device association is basically absent
4. connector / linework-aware grounding is still too weak
5. evaluation does not punish low grounded yield strongly enough

## Current audited state
Strong:
- candidate grouping
- legend dictionary completeness
- provenance
- alignment scaffold

Weak:
- grounded yield
- room/device association
- connector-aware meaning
- packet hard-page enforcement
- evaluation severity on unresolved-heavy packets

## What this kit does
It adds:
- non-empty hard-page requirement logic
- grounded-yield metrics and packet-level gates
- room/device association refinement
- connector-context scoring
- stricter grounding-state thresholds
- harder V2.2 evaluation and per-packet quality reporting

## Intended outcome
Move V2 from:
- “good scaffold”

to:
- “usable semantic grounding layer” for your two domains

while keeping:
- parser text/table layer frozen
- V0/V1 stable
- contradiction lane untouched
