You are continuing the OrbitBrief parser/runtime hardening work.

Current state to preserve:
- The packet-to-claim extractor now uses packet evidence span text instead of placeholder bodies like `risk:anchor=... supports=...`.
- The runtime postprocess policy now treats the compiled pack as the source of truth for allowed field paths, so canonical compiled targets like `assumptions[]`, `scope_included[]`, `deliverables_required[]`, and `risks_or_dependencies[]` are accepted.
- The parser/compiler active test surface passes with `219 passed, 1 skipped` for `tests/parser tests/compiler`.
- The broader legacy `tests/` suite still has collection errors for old missing runtime_spine modules (`contracts`, `config`, `ingestors`, `heads`, `mapping`, old parser paths). Do not mix that migration into this patch unless explicitly asked.

What changed in this patch:
1. `src/orbitbrief_core/runtime_spine/pipeline.py`
   - enriches extractor packet payloads with `evidence_rows` built from `DocumentParse.evidence_spans`
   - prefers compiled projection targets for postprocess legality instead of sparse extractor-registry field hints
2. `src/orbitbrief_core/runtime_spine/compiled_pack_runtime.py`
   - computes claim-family projection targets from compiled artifacts
   - exposes helpers to resolve projection targets and canonicalize requested field paths
3. `src/orbitbrief_core/runtime_spine/extractors/packet_to_claims.py`
   - chooses semantic source spans from packet evidence
   - cleans family-specific lead-ins like `Assumption is ...`, `Risk is ...`, `Deliverable is ...`
   - supports packet family override from anchor family hints on `family_conflict`
   - can emit a companion claim from the clustered packet when the assigned family and anchor family disagree
4. Regression tests added/updated:
   - `tests/parser/test_compiled_pack_runtime_policy_stage9_1.py`
   - `tests/parser/test_narrative_extractor_stage6_1.py`
   - `tests/parser/test_extractor_hot_path.py`

Verified commands:
- `python -m pytest -q tests/parser tests/compiler`
- expected result in this environment: `219 passed, 1 skipped`
- `python -m pytest -q tests`
- still fails during collection because of old legacy module imports outside the active parser/compiler lane

Immediate next steps I would take:
1. Upgrade `packet_to_claims.py` from semantic strings to structured family payload extraction
   - examples:
     - `scope_included[]` -> `{task_name, location, quantity, unit, workstream, notes}`
     - `deliverables_required[]` -> `{deliverable_name, format, timing, acceptance_basis}`
     - `risks[]` -> `{description, impact, mitigation, owner}` when evidence supports it
2. Move family override logic earlier into packet diagnostics or packetizer scoring so fewer packets arrive mislabeled
3. Add a small golden eval corpus for transcript/note/email/pdf_text/pdf_ocr and score:
   - accepted claim count
   - illegal field path count
   - placeholder body count (should remain zero on enriched packet payloads)
   - semantic value exact/contains match
4. Hook Qwen only at bounded seams:
   - packet-to-claim extraction for hard families after deterministic extraction
   - graph scorer assists (`same_topic`, `support`, `packet_seed`)
   - not as a whole-document extractor

Guardrails:
- Keep evidence refs mandatory.
- Keep compiled pack runtime policy as the legality source of truth.
- Do not reintroduce sparse registry field paths as the effective allow-list when compiled pack targets exist.
- Do not let extractor reopen the full document; operate on packet evidence only.
