
# Phase V2.3 Truth-Audit Kit

This kit is the **explicit anti-fake-success / truth-repair pass** for the V2 symbol-grounding layer.

It exists because the previous pass produced suspiciously perfect V2.2 metrics:
- every candidate became grounded
- unresolved went to zero
- room/device association became 1.0
- connector quality became 1.0
- some packets still had empty `required_page_types` while `hardpage_rate = 1.0`

That pattern is not believable for real packet-local schematic semantics.

## What this kit does
It gives Cursor everything needed to repair that:
1. **truth-audit helpers**
2. **evidence-backed booleans**
3. **hard-page requirement enforcement**
4. **anti-default evaluation gates**
5. **sample-row audits so fake success cannot hide**

## Main idea
Do not let V2 "pass" unless:
- hard-page requirements are truly non-empty when those sheet families exist
- `grounded`, `ambiguous`, and `unresolved` are all used honestly
- room/device association and connector grounding flags are computed from actual evidence
- packet-level rows expose raw evidence scores
- no packet can auto-pass with uniform success defaults

## Outcome expected
After this pass, the numbers may become **less perfect**, but they should become **trustworthy**.
That is what we want.
