# Phase 2 Gold-Ready Release Notes

This repo snapshot locks the deterministic `site_schematic` baseline against two packaged gold routes:
- wireless / AP-heavy telecom packet
- low-voltage / hospitality / security / MATV packet

## What was added
- Packaged gold fixtures under `tests/site_schematic/fixtures/`
- Packaged sample PDFs under `tests/site_schematic/fixtures/pdfs/`
- Gold evaluation helpers in `tests/site_schematic/gold_eval.py`
- Regression tests for page typing, zoning, structured extraction, graph expectations, and gold scorecards
- Evaluation CLI at `tools/evaluate_site_schematic_gold.py`
- Site-schematic docs consolidated under `docs/site_schematic/`
- Legacy patch/handoff docs moved under `docs/legacy_handoffs/`

## What is now locked
- Stable page typing and region zoning for both gold packets
- Legend, abbreviation, outlet, note/rule, and drawing-index extraction
- Symbol linking for AP/WN and related route-critical semantics
- Grounded graph outputs and legality/status tagging

## Compatibility note
Legacy `cad_*` paths remain in the repo for compatibility and staged cutover. They should be treated as shims around the canonical `site_schematic` lane until the broader runtime cutover is complete.

## Next step
Hook in external models incrementally and measure lift against the packaged gold scorecards:
1. PaddleOCR-VL / Docling
2. YOLO primitive symbol detector
3. Qwen bounded verifier
