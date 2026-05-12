
# Phase V2.5 Family-Coverage Fix Kit

This kit is the **zipped fix** for the current V2 failure mode:

- `expected_family_grounded_coverage_rate` too low
- `hardpage_family_grounded_coverage_rate` too low
- `hardpage_requirement_truth_rate` still failing
- all 12 packets failing the hardened V2 gate

## Core diagnosis
The current V2 truth-audit is now honest enough to expose the real issue:

1. family coverage is being measured against a family set that is too broad or not packet-relevant enough
2. hard-page requirement logic is still not derived correctly from actual packet page types
3. grounded-family derivation from local legend text is still too weak
4. hard-page gates are too detached from packet-local legend evidence

## Goal of this fix
Make V2 earn real, packet-local family coverage on the 12-packet corpus by:

- deriving **packet-relevant expected family sets** from actual packet-local evidence
- deriving **hard-page expected family sets** from actual hard pages
- repairing **required hard-page type derivation**
- strengthening **grounded family derivation** from legend/local text/page type
- evaluating coverage against what the packet actually contains, not an overly broad domain superset

## Important note
This kit is intentionally focused on the real current blocker.
It does not start V3.
It does not touch OrbitBrief.
It does not weaken the truth-audit.
