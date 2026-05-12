# Phase D-next: Phase C universality generalization plan

## Why this is first
The latest pass proved:
- the evaluator misalignment is fixed enough
- the current pair are again protected
- the holdouts are still dominated by **Phase C** failures

This means the next highest-leverage parser-only work is:
- generalized locality provenance
- generalized multi-column note preservation
- generalized global-vs-local note separation
- generalized detail-locality references
- generalized mixed-page locality contracts

## The actual failure pattern we are attacking
Typical Phase C holdout failures:
- `locality_provenance_rate` too low
- `global_vs_local_note_separation_rate` too low
- `detail_locality_reference_rate` too low
- `multi_column_preservation_rate` too low
- silent note-scope conflict counts too high

## Design goals
1. Keep current-pair canonical Phase C gold untouched.
2. Generalize locality contracts across unseen packet structures.
3. Prefer bounded structural logic over sheet-specific overrides.
4. Reuse Phase 1B table regions as locality anchors where possible.
5. Stay parser-only.

## Parser changes to make
### A. Locality-first region contract
Strengthen region objects so locality can be inferred from:
- `page_index`
- `region_id`
- `detail_region_id`
- `subregion_id`
- `pseudo_page_id`
- `column_id` (new if needed)
- `source_table_ids`
- `locality_confidence`

### B. Generalized multi-column discovery
Do not rely on only explicit header hits.
Use:
- x-coordinate clustering of text/layout blocks
- sustained vertical alignment
- gutter detection
- bounded minimum column width
- column persistence across nearby blocks

### C. Global vs local note separation
Promote note blocks to local only when supported by:
- detail-frame overlap
- same pseudo-page or same detail locality
- detail tokens / keyed-note references
- proximity to detail anchors
Keep page-global when locality is weak.
Never silently flatten local into global.

### D. Mixed-page locality contracts
On mixed sheets:
- create `column_local` / `detail_local` / `page_global` scope classes
- preserve locality status explicitly
- emit unresolved scope when ambiguous

### E. Table-aware locality reuse
If a note/schedule/legend region is table-backed:
- inherit locality anchors from the table region
- keep region lineage tied to `source_table_ids`
- do not downgrade structured table blocks into generic note blobs

## Suggested file targets
- `src/orbitbrief_core/parser/site_schematic/zoning/page_zones.py`
- `src/orbitbrief_core/parser/site_schematic/core.py`
- region/locality models if needed in `models.py`
- optional evaluation helpers in `tests/site_schematic/phase_d_universality_eval.py`

## Success criteria
### Immediate
- current-pair canonical Phase C remains perfect
- holdout Phase C pass count >= 5/10
- silent note-scope conflicts drop materially
- multi-column preservation improves materially

### Stretch
- holdout Phase C pass count >= 7/10
- no holdout with total locality collapse on note-heavy or mixed-detail pages
