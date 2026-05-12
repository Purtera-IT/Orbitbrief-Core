# Site Schematic Gold Fixtures

This folder contains the canonical Phase 2 gold-route fixtures used to lock the deterministic baseline before external vision models are enabled.

Fixtures:
- `wireless_route_golden.json` — AP-heavy telecom / wireless packet baseline
- `low_voltage_route_golden.json` — low-voltage / hospitality / security / MATV packet baseline
- `site_schematic_golden_baseline_and_repo_gap_audit.md` — narrative spec and gap audit
- `pdfs/100643PLANSD-4.pdf` — wireless/AP-heavy sample packet
- `pdfs/2026-01-19 CONSOLIDATED SET - SOUTHERN POST - T (1) (1) (1).pdf` — low-voltage/hospitality sample packet

These fixtures are consumed by:
- `tests/site_schematic/test_gold_pdf_eval.py`
- `tests/evals/test_site_schematic_gold_scorecard.py`
- `tools/evaluate_site_schematic_gold.py`

The tests and evaluation tool prefer the local `pdfs/` fixtures first, and fall back to `/mnt/data` paths when running in a sandbox that already provides the source PDFs.
