Patch scope
- Fix packet-to-claim semantics so the extractor emits real semantic text from packet evidence rows.
- Fix compiled runtime policy alignment so canonical compiled field paths survive postprocess legality.

Files changed by this patch
- src/orbitbrief_core/runtime_spine/compiled_pack_runtime.py
- src/orbitbrief_core/runtime_spine/pipeline.py
- src/orbitbrief_core/runtime_spine/extractors/packet_to_claims.py
- tests/parser/test_compiled_pack_runtime_policy_stage9_1.py
- tests/parser/test_narrative_extractor_stage6_1.py
- tests/parser/test_extractor_hot_path.py
- CURSOR_HANDOFF_PROMPT_STAGE9.md

Verification run
- `python -m pytest -q tests/parser tests/compiler`
- Result in this environment: `219 passed, 1 skipped`

Real compiled-pack smoke result
- `parse_extract_and_postprocess(...)` with the repo's `compiled_artifacts/professional_services_text/v1`
- result summary:
  - `claims_input_count: 8`
  - `claims_emitted_count: 7`
  - `rejected_claims_count: 1`
  - only rejection reason: `duplicate_merged`
- emitted semantic examples:
  - `customer will provide after-hours access`
  - `AP installation at Dallas HQ and Austin branch`
  - `a migration runbook`
  - `permit delay for rooftop work`

Known untouched issue
- `python -m pytest -q tests` still fails during collection on legacy missing runtime_spine modules outside the active parser/compiler lane.
