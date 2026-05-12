
# Parser Text Perfection Kit v1

This kit is the **last parser-only text/legend/note cleanup pass** before moving to graphics.

It is based on the actual corpus extraction results you reported:
- visible_text_coverage_estimate_avg = 0.9891
- note_spec_coverage_rate_avg = 0.9715
- unresolved_text_only_gap_rate_avg = 0.0215
- parser_ready_for_vision_handoff_rate = 1.0

The parser is already strong enough that the next major bottleneck is graphics/schematics.
But before moving to graphics, this pass aims to eliminate the **small remaining non-graphics text gaps** so you can honestly say the parser is effectively perfect for:
- notes/specs
- legends
- tables
- schedules
- abbreviations
- outlet definitions
- text labels
- provenance

## What is actually still broken
From the corpus artifacts, the remaining parser-only text issues are concentrated in two places:

1. **Structured note-clause under-emission**
   Pages with note/spec cues still sometimes emit zero structured note clauses.
   Most common on:
   - `schedule_sheet`
   - `notes_spec`
   - some `legend_symbol`
   - some `riser_diagram`

2. **Locality-scope closure**
   Many pages already produce note clauses and scoped links, but some detail-local note links remain unresolved instead of closing to:
   - `detail_local`
   - `subregion_local`
   - `pseudo_page_local`
   - `column_local`

The goal of this kit is to kill those last issues without touching:
- OrbitBrief
- contradiction truth paths
- graphics/schematic interpretation

## Desired end state
After this pass:
- text-only gap rate should be effectively 0
- locality-scope gap rate should be effectively 0
- note/spec coverage should approach 1.0
- the remaining major misses should truly be graphics-only

Then you move to the graphics/schematics phase.
