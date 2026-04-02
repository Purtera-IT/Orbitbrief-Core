# OrbitBrief full parser/compiler flow patch

Patched files:
- `src/orbitbrief_core/runtime_spine/__init__.py`
- `src/orbitbrief_core/runtime_spine/file_utils.py`

Why:
- prevent eager imports of missing legacy `runtime_spine` modules from breaking pytest collection
- provide a valid `synthetic_minimal_pdf(...)` used by tests and parser smoke paths

Validation run:
- `pytest -q tests/compiler tests/parser` -> `126 passed, 1 skipped`
- full real bundle compiler build -> `READY_FOR_PARSERS: YES`
- end-to-end parser smoke paths succeeded for txt, email, pdf_text, pdf_ocr
