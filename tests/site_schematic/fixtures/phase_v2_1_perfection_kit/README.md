
# Phase V2.1 Perfection Kit

This kit is the **next push to perfection** for the V2 symbol-grounding layer on the
`site_schematic` lane.

It is designed for the exact V2 state you reported:
- candidate grouping / legend dictionary / provenance are already strong
- packet-level V2 failures are 0
- but the main remaining trust gaps are:
  1. unresolved vs ambiguous discipline
  2. connector / linework-aware grounding
  3. harder packet-level symbol semantics gates

## What this kit is for
This kit turns the current V2 from:
- strong grounding scaffold

into:
- stricter, more honest, more universal packet-local symbol semantics

by adding:

1. **Grounding-state policy**
   - restores honest abstention
   - separates `grounded`, `ambiguous`, and `unresolved`
   - prevents over-resolution

2. **Connector / linework-aware grounding refinement**
   - lets linework attachment, leader evidence, and connector continuity influence meaning
   - improves riser/rack/pathway/equipment detail grounding

3. **Legend text association**
   - strengthens mapping from packet-local legend text and note text into semantic aliases
   - helps with unseen glyph styles across packets

4. **Packet-level hard-page semantics gates**
   - forces V2 to prove itself on the hardest sheet families:
     - control/legend
     - riser
     - equipment/rack
     - installation/detail
     - plan page with symbol/linework interaction

## Scope
This is still V2.
It does **not** introduce:
- full raster fallback
- segmentation-heavy raster symbol parsing
- VLM arbitration as a primary path
- full topology semantics finalization

Those are later.

## Why this is the right move
The code archaeology pass found the graphics/parser seams are concentrated in the exact places this kit patches:
- `core.py`
- `models.py`
- `structure_graph.py`
- `symbols/linker.py`
- symbol/model adapter seams
- eval harnesses

So this is the correct hardening move before V3.
