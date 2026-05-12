# Phase C Acceptance Checklist

## Must stay true from Phase 1B
- [ ] Universal table contract still present
- [ ] Table-derived semantics still carry lineage fields
- [ ] Phase 1B hard-page table gold remains green or unchanged

## Phase C hard requirements
- [ ] Required region kinds found on all hard pages
- [ ] Multi-column notes preserved on T000
- [ ] No giant legend blob on T001
- [ ] TC001 preserves separate abbreviations, drawing index, symbol legend, outlet definition, and notes regions
- [ ] T700 guestroom tiles become local pseudo-pages / detail regions
- [ ] T900 mixed equipment/rack/riser content is not flattened
- [ ] T901 riser body remains distinct from callouts/insets
- [ ] T905 embedded schedule stays local to the detail sheet
- [ ] T906 installation details preserve local detail grouping
- [ ] Global vs local notes separated correctly
- [ ] Region hierarchy objects all have bbox + provenance
- [ ] No silent note-scope conflicts
- [ ] No hybrid page overflattening
- [ ] No pseudo-page fragmentation errors

## Regression safety
- [ ] `test_universal_table_contract.py` green
- [ ] `test_mixed_detail_decomposition.py` green
- [ ] `test_subregion_dispatch.py` green
- [ ] `test_note_scope_resolution.py` green
- [ ] `test_graph_subregion_edges.py` green
- [ ] `test_observation_policy_hardening.py` green
- [ ] `test_model_assisted_observations.py` green
- [ ] `test_phase2_pdf_smoke.py` green
- [ ] `test_gold_pdf_eval.py` green
