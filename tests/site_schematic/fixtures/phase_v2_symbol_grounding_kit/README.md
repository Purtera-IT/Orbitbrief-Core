
# Phase V2 Symbol Grounding Kit

This kit packages the **full implementation plan, starter code, gold schemas, and validation scaffolding**
for Phase V2 of the `site_schematic` lane:

## V2 Scope
- universal primitive symbol grounding
- legend-grounded packet-local symbol semantics
- candidate symbol grouping on schematic pages
- graph/topology hint outputs from grounded symbols
- 12-packet validation across the current pair and all holdouts

## Why V2 is the right next phase
The parser-only non-graphics layer is effectively complete enough to hand off to graphics, and the V0/V1 graphics base is now stable enough to trust:
- modality routing
- vector-native primitive extraction
- primitive graph construction
- packet-level V0/V1 quality gates

The next bottleneck is not raw vector extraction anymore.
It is:
- what the candidate symbol groups mean on each packet
- how local legends map those groups into packet-specific meanings
- how to validate that mapping across all 12 PDFs

## What this kit contains
- implementation plan
- Cursor prompt
- integration prompt
- acceptance checklist
- eval matrix
- target metrics JSON
- master V2 gold schema
- registry seed for all 12 packets
- per-packet gold schemas derived from the 12-document corpus inventories
- starter code modules
- helper tests
- patch-style diffs for likely integration points

## Design principle
Do NOT use a fixed packet-global icon dictionary.
Use:
- universal primitive families
- packet-local legend dictionaries
- local note / outlet / schedule semantics
- V1 primitive graph
to resolve grounded symbol meaning per packet.
