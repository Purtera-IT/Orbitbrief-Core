# Orbitbrief Core

This package contains the Orbitbrief parser/compiler/runtime stack, including the Phase 2 `site_schematic` lane that is now locked against the wireless/AP-heavy and low-voltage/hospitality gold routes.

## Primary site schematic entrypoints
- `src/orbitbrief_core/parser/site_schematic/`
- `src/orbitbrief_core/parser/adapters/site_schematic_pdf.py`
- `src/orbitbrief_core/parser/adapters/site_schematic_image.py`
- `config/runtime/site_schematic_models.yaml`

## Gold baseline + evaluation
- `tests/site_schematic/fixtures/`
- `tests/site_schematic/test_gold_pdf_eval.py`
- `tests/evals/test_site_schematic_gold_scorecard.py`
- `tools/evaluate_site_schematic_gold.py`
- `docs/site_schematic/phase2_gold_readiness.md`

## Legacy handoff / patch notes
Older patch-era and handoff documents are preserved under:
- `docs/legacy_handoffs/`

## Compatibility policy
`cad_*` and `runtime_spine/extractors/cad_packet_to_claims.py` remain for compatibility while the site schematic lane continues to own the canonical extraction logic for this route family.
