# Phase 1B Universal Table Spine Kit

This kit is a parser-only implementation package for **Phase 1B: header-aware multi-table splitting + mandatory table-first extractor routing**.

It is intended for the `site_schematic` lane and is explicitly downstream-safe for OrbitBrief: the parser preserves structure first, and any projection/reasoning consumes that structure later.

## Included files

- `phase1b_integration_plan.md`
- `phase1b_cursor_prompt.txt`
- `phase1b_perfect_gold_standard.json`
- `phase1b_acceptance_checklist.md`
- `phase1b_target_pages.md`

## Goal

Fix the reasons Phase 1 was `not_perfect` by:

1. splitting hybrid control/legend/schedule pages into multiple table candidates,
2. classifying those table candidates into the correct semantic table kinds,
3. promoting embedded schedule-like boxes on detail pages into table candidates,
4. forcing table-derived semantic extractors to consume row/cell lineage first.

## Core success criteria

- `required_table_kind_coverage = 1.0`
- `bbox_presence_rate = 1.0`
- `lineage_completeness_rate = 1.0`
- `semantic_row_reference_rate >= 0.95`
- `semantic_cell_reference_rate >= 0.95`
- `unflagged_row_cell_merge_split_count = 0`
