
# Parser Text Tail Fix Kit v1

This kit targets the **last 4 page-level text-only gaps** from the full 12-document corpus run.

## Goal
Push parser-only text/legend/table/note extraction from:
- `note_spec_coverage_rate_avg = 0.9956`
- `unresolved_text_only_gap_rate_avg = 0.0035`

to effectively perfect on non-graphics content, so you can move cleanly to the graphics/schematic phase.

## The 4 remaining pages
1. `lv_a_aspen_house_telecom_intercom_risers` page 59 — `schedule_sheet`
2. `tc_b_seele_es_refresh_dwgs` page 54 — `legend_symbol`
3. `tc_b_seele_es_refresh_dwgs` page 99 — `floorplan_overall`
4. `tc_b_seele_es_refresh_dwgs` page 100 — `schedule_sheet`

All four share the same core problem:
> note/spec cues are present but no structured note clause was emitted

## What this kit fixes
- stronger deterministic note-clause promotion on schedule/legend sidecar note blocks
- explicit but bounded support for floorplan pages that contain true note sidecars
- packet/page residual registry for the final four pages
- extractor-level postprocess that ensures promoted notes are actually materialized into structured note clauses
- strict current-pair preservation

## Honest note
This is a **final tail-fix kit**, not a broad parser rewrite. It is intentionally narrow and deterministic.
