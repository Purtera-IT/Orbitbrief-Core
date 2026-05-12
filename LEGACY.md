# Legacy parser / runtime_spine / compiler

As of Phase 1 (Evidence Runtime), the following subtrees were removed
from `main`:

* `src/orbitbrief_core/parser/` — inline parser stack that predated
  the `parser-os` ↔ OrbitBrief seam.
* `src/orbitbrief_core/runtime_spine/` — old runtime façade.
* `src/orbitbrief_core/compiler/` — old domain-pack compiler.
* `tests/{parser,compiler,site_schematic,evals}/` and the orphan
  top-level test files that depended on them.

They are preserved verbatim on the [`legacy_parser_runtime`](https://github.com/Purtera-IT/Orbitbrief-Core/tree/legacy_parser_runtime)
branch. Use that branch if you need to consult the historical
implementation, but do **not** re-introduce these modules to `main` —
their replacement is `orbitbrief_core.evidence_runtime` consuming the
`orbitbrief.input.v2` envelope from `parser-os`.

## Why removed

The Phase-0 contract said OrbitBrief never reads raw input files; the
legacy subtrees did exactly that, against `pdfplumber`/`fitz`/
`pytesseract`. Phase 1 builds the typed substrate that replaces them.
Keeping both around invited drift.

## What replaces them

| Legacy concern | Replacement |
|---|---|
| Reading PDFs / DOCX / XLSX / transcripts / emails | `parser-os` (the producer) |
| Loading + validating the envelope | `orbitbrief_core.seam` (Phase 1A) |
| Atom / entity / packet storage + queries | `orbitbrief_core.evidence_runtime` (Phase 1) |
| Provenance replay | `evidence_runtime.replay_source` → `parser_os.app.core.source_replay` |
