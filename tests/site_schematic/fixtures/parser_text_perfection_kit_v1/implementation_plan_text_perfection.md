# Parser Text Perfection implementation plan

## Current state
The parser is already parser-ready-for-vision on all 12 documents, but there are still small residual text-side gaps.

### Actual remaining issue pattern
- 33 pages: `multiple detail-local scoped note links remain unresolved`
- 21 pages: `note/spec cues present but no structured note clause emitted`
- 6 pages: mixed text + graphics residual

### Dominant sheet types with non-graphics issues
- `schedule_sheet`: biggest combined text/locality gap surface
- `notes_spec`: locality closure issues
- `riser_diagram`: some note/locality misses
- `legend_symbol`: a few lingering note/spec misses
- `installation_detail`: small locality tail

## Goal
Make the parser effectively perfect for non-graphics extraction by fixing:
1. note clause under-emission
2. unresolved locality closures
3. weak note/spec capture on schedule/legend/riser pages

## The fixes

### Fix 1 — Structured note-clause promotion
If a page/region has clear note/spec cues but emitted zero structured note clauses, promote those cues into note clauses deterministically.

Target pages:
- `schedule_sheet`
- `notes_spec`
- `legend_symbol`
- `riser_diagram`
- `floorplan_overall` only for explicit note blocks, not random labels

This should prefer:
- explicit numbered notes
- sectioned note paragraphs
- single-column and multi-column note blocks
- footer/sidecar notes that are clearly note-like

### Fix 2 — Locality scope closure pass
After `resolve_note_scope()`, run a deterministic closure pass that upgrades unresolved detail-like notes when evidence is already strong:
- same `detail_region_id`
- or same `subregion_id`
- or same `pseudo_page_id`
- and same `column_id` when applicable
- and note/detail cue agreement

If evidence is still weak:
- leave unresolved
- never guess

### Fix 3 — Global-note preservation guard
Do not let locality closure accidentally downgrade true global notes.
Strong global note cues like:
- `general note`
- `keyed note`
- `project requirements`
- `general infrastructure installation notes`
- `drawing index`
should remain page-global unless explicit local evidence overrides them.

### Fix 4 — Bbox/provenance completion for note carriers
If a note-bearing region or scoped note object is missing locality ids or bbox/provenance that can be deterministically derived, complete them.

## Integration points
Likely target files:
- `src/orbitbrief_core/parser/site_schematic/core.py`
- `src/orbitbrief_core/parser/site_schematic/zoning/page_zones.py`
- `src/orbitbrief_core/parser/site_schematic/extractors/notes_spec_extractor.py`
- `src/orbitbrief_core/parser/site_schematic/extractors/schedule_sheet_extractor.py`
- possibly `legend_sheet_extractor.py`
- tests under `tests/site_schematic/`

## Perfect target
- `visible_text_coverage_estimate_avg >= 0.995`
- `note_spec_coverage_rate_avg >= 0.995`
- `unresolved_text_only_gap_rate_avg <= 0.002`
- `legend_table_coverage_rate_avg = 1.0`
- `semantic_lineage_coverage_rate_avg = 1.0`
- `parser_ready_for_vision_handoff_rate = 1.0`

At that point, the only meaningful next bottleneck should be graphics/schematics.
