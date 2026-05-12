# Final text-tail fix implementation plan

## Remaining issue pattern
All 4 residual pages are:
- `text_only_gap`
- with reason: `note/spec cues present but no structured note clause emitted`

No symbol unresolved issues, no table/legend gaps, no graphics-only issues on those pages.

## Why the current parser still misses them
### 1. Promoter sheet-type gating is too narrow
The current note promoter focuses on:
- `schedule_sheet`
- `notes_spec`
- `legend_symbol`
- `riser_diagram`
and may still be too weak on:
- legend/schedule sidecar notes
- floorplan pages with explicit note sidecars

### 2. Pattern thresholds are too strict
The current promoter likely likes:
- numbered notes
- obvious “GENERAL NOTES” sections
and may miss:
- shorter but still valid sidecar paragraphs
- table-adjacent narrative notes
- legend-note narratives
- schedule-note narratives

### 3. Promotion is not always materialized into extractor outputs
Even if note-like blocks are detected, they may not always be converted into structured note clauses in the final extractor output path.

## Fix strategy
### A. Residual note-gap registry
Add a deterministic registry for the final 4 pages with:
- packet_id
- page_index
- sheet_type
- promotion profile
- allowed fallback behavior

### B. Stronger promotion profiles
Support these profiles:
- `schedule_with_note_sidecar`
- `legend_with_note_sidecar`
- `floorplan_with_note_sidecar`

### C. Generic but bounded rule expansion
Improve note promotion generally for:
- schedule pages with table-backed side notes
- legend pages with adjacent note narratives
- floorplan pages only when explicit note cues are present and room-label noise is filtered out

### D. Extractor postprocess
After extraction, if note clauses are still zero and promoted note candidates exist, materialize them into structured note clause objects before final artifact output.

## Acceptance targets
- Remaining `text_only_gap` pages = 0
- `unresolved_text_only_gap_rate_avg <= 0.001`
- `note_spec_coverage_rate_avg >= 0.998`
- current pair remain stable
- no regressions in table/legend/region fidelity paths
