# Site Schematic Lane

This folder holds the Phase 2 documentation for the `site_schematic` parser lane.

## Source-of-truth docs
- `phase2_gold_readiness.md` — gold baseline, architecture notes, and repo-gap audit
- `gold_scorecards.sample.json` — sample locked-baseline scorecards for the wireless and low-voltage routes

## Runtime + parser entrypoints
- `config/runtime/site_schematic_models.yaml`
- `config/runtime/extractors/site_schematic/`
- `src/orbitbrief_core/parser/site_schematic/`
- `src/orbitbrief_core/parser/adapters/site_schematic_pdf.py`
- `src/orbitbrief_core/parser/adapters/site_schematic_image.py`

## Gold fixtures + evaluation
- `tests/site_schematic/fixtures/` (including packaged sample PDFs under `fixtures/pdfs/`)
- `tests/site_schematic/gold_eval.py`
- `tests/site_schematic/test_gold_route_contracts.py`
- `tests/site_schematic/test_gold_pdf_eval.py`
- `tests/site_schematic/test_phase2_pdf_smoke.py`
- `tests/evals/test_site_schematic_gold_scorecard.py`
- `tools/evaluate_site_schematic_gold.py`

## Historical notes
Earlier patch/handoff materials live in `docs/legacy_handoffs/`.
