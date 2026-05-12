# Phase 1B Target Pages

These are the anchor hard pages for the first parser-only lossless-table pass.

## Wireless packet

### Page 1 — `TC001 TELECOMM SYMBOL LIST`
Why it matters:
- hybrid control page, not one table
- includes abbreviations
- includes drawing list
- includes outlet type descriptions
- includes telecom symbol sections
- includes notes sections

Required kinds to recover separately:
- `drawing_index`
- `symbol_legend`
- `outlet_definition`
- `generic_grid` or `abbreviation_matrix`

## Southern Post packet

### Page 1 — `T000 PROJECT REQUIREMENTS NOTES & SPECS`
Why it matters:
- multi-column notes/spec page
- contains drawing index table listing T000–T906
- should preserve table structure without flattening notes columns

Required kinds:
- `drawing_index`
- any schedule/spec table candidates found by structure

### Page 2 — `T001 SYMBOLS & LEGENDS`
Why it matters:
- dense multi-table legend page
- includes Responsibility Matrix
- includes Structured Cabling Symbol Legend
- includes Intrusion Detection Symbol Legend
- includes Access Control and Intercom Symbol Legend
- includes CCTV Symbol Legend

Required kinds:
- `symbol_legend`
- `generic_grid`
- `responsibility_matrix` (or preserved as `generic_grid` if the ontology does not yet split it)

### Page 3 — `T002 SCHEDULES & MISCELLANEOUS`
Why it matters:
- spec/schedule style table page
- used to validate component/spec row preservation

Required kinds:
- `component_spec`
- `schedule`

### T900 equipment-room mixed layout page
Why it matters:
- embedded schedule-like boxes inside a mixed detail/equipment context

Required kinds:
- `embedded_detail_schedule`

### T905 security installation details
Why it matters:
- detail page with small embedded schedules/boxes
- stress test for embedded table promotion

Required kinds:
- embedded table detection where structurally present
