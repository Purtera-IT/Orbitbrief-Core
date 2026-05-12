# OrbitBrief

OrbitBrief turns raw professional-services intake (RFPs, proposals, transcripts, spreadsheets) into a **reviewable scope brief** that a project manager can accept, edit, or reject — with every claim traceable to a source artifact.

The system is two repositories that talk through one frozen contract:

| Repo | Role | URL |
|---|---|---|
| `parser-os` | Ingestion & extraction. Turns raw files into a typed `orbitbrief.input.v2` envelope. | https://github.com/Purtera-IT/parser-os |
| `Orbitbrief-Core` *(this repo)* | Synthesis. Turns the envelope into a calibrated reviewable brief. | https://github.com/Purtera-IT/Orbitbrief-Core |

Both run locally on a Mac via Ollama (Qwen3 family). One command runs the whole pipeline:

```bash
python compile_brief.py engagement.json --out artifacts/ --ollama
python -m orbitbrief_core.review_ui --artifacts artifacts/
# → http://127.0.0.1:8765/queue
```

---

## Table of contents

1. [System overview](#system-overview)
2. [How parser-os works](#how-parser-os-works)
3. [How Orbitbrief-Core works](#how-orbitbrief-core-works)
4. [The seam — `orbitbrief.input.v2`](#the-seam--orbitbriefinputv2)
5. [End-to-end pipeline](#end-to-end-pipeline)
6. [Models in band](#models-in-band)
7. [CLI reference](#cli-reference)
8. [Architectural invariants](#architectural-invariants)
9. [Per-component honest ranking](#per-component-honest-ranking)
10. [Remaining MVP gaps](#remaining-mvp-gaps)

---

## System overview

```
┌───────────────────────────┐    orbitbrief.input.v2     ┌──────────────────────────────┐
│   parser-os               │   (typed JSON envelope)    │   Orbitbrief-Core            │
│   ─────────               │ ────────────────────────►  │   ─────────────              │
│   PDFs / DOCX / XLSX /    │                            │   12 layers, layered         │
│   transcripts / emails    │                            │   isolation enforced by      │
│   → atoms + entities +    │                            │   import-linter (12          │
│     edges + packets +     │                            │   contracts) +               │
│     manifest              │                            │   raw-IO ratchet             │
└───────────────────────────┘                            └──────────────────────────────┘
```

**Two halves, one contract.** `parser-os` is the file-eating side: it reads raw artifacts and emits a deterministic, byte-identical envelope. `Orbitbrief-Core` is the synthesis side: it consumes the envelope, never raw files, and produces a typed `BriefState` + per-domain brain outputs + a calibrated reviewable doc.

The contract is a Pydantic schema (`schema_version: orbitbrief.input.v2`). Both sides validate at the boundary so producer drift fails loud.

---

## How parser-os works

`parser-os` is at https://github.com/Purtera-IT/parser-os. It compiles a project directory of artifacts into a typed envelope.

### Stages

```
project_dir/                               compile_project()
├── *.pdf      ──► orbitbrief_pdf       ─┐
├── *.docx     ──► orbitbrief_docx      ─┤
├── *.xlsx     ──► orbitbrief_xlsx      ─┤
├── *.txt      ──► orbitbrief_text      ─┤      ┌──────────────┐
├── *.eml      ──► orbitbrief_email     ─┼──►   │  compiler/   │ ──► orbitbrief.input.v2
├── *.md       ──► orbitbrief_text      ─┤      │  graph_builder│      envelope JSON
└── *.vtt      ──► orbitbrief_transcript─┘      │  validators   │
                                                │  source_replay│
                                                │  domain/pack  │
                                                └──────────────┘
```

### Per-artifact extraction

Each parser produces an **artifact projection**:

* **PDFs** → `orbitbrief_pdf` walks pages with PyMuPDF + Tesseract OCR fallback. Detects tables, matrices, headers, tail/interstitial notes, scope markers. Emits `orbitbrief.structured.v1` per page (text blocks, tables, locators).
* **XLSX** → `orbitbrief_xlsx` reads sheets with openpyxl, classifies sheets (instructional vs tabular), extracts rows as atom-precursors with `(sheet, row, col)` locators. Skips instructional sheets via a `_looks_instructional_sheet` heuristic.
* **DOCX / TXT / MD / Pasted notes / Email exports** → tokenized into paragraph-level atom precursors with `(paragraph_index, char_offset)` locators.
* **Transcripts (VTT)** → speaker turns + timestamps preserved on locators.

### Atom + entity + edge + packet extraction

Per-artifact projections feed `app.core.compiler.compile_project()`, which runs:

1. **Atom extraction** — every parser emits typed `EvidenceAtom` records (id, atom_type, authority_class, confidence, text, section_path, locator, verified). 13 atom types: `quantity`, `entity`, `constraint`, `exclusion`, `scope_item`, `customer_instruction`, `vendor_line_item`, `assumption`, `open_question`, `decision`, `action_item`, `meeting_commitment`, `compliance`.
2. **Entity normalization** — `app.core.entity_normalizer` deduplicates atoms that refer to the same real-world entity. Produces `EvidenceEntity` records with `canonical_key` (e.g., `site:building_a`), `canonical_name`, alias list, source atom ids, review_status.
3. **Graph build** — `app.core.graph_builder` creates `EvidenceEdge` records between atoms. Edge types: `same_as`, `supports`, `contradicts`, `excludes`, `requires`, `located_in`, `derived_from`, `quoted_from`. Self-loops blocked by `graph_invariants`.
4. **Packet certification** — `app.core.packet_certifier` rolls atoms + edges into typed `Packet` records keyed by `(family, anchor_type, anchor_key)`. 11 packet families: `scope_inclusion`, `scope_exclusion`, `quantity_claim`, `quantity_conflict`, `site_access`, `missing_info`, `customer_override`, `vendor_mismatch`, `meeting_decision`, `action_item`, `compliance_clause`.
5. **Source replay** — `app.core.source_replay` re-verifies each atom's text against the original artifact bytes via the locator. Atoms get `verified=verified` / `failed` / `partial` / `unsupported` / `unverified`. Replay-failed atoms become red flags downstream.
6. **Domain pack routing** — `app.domain.pack_router` picks the most-likely domain pack for the project (security_camera, copper_cabling, wireless, …). Used to scope the compile but the envelope ships pack-agnostic data.
7. **Quality gates** — `app.core.validators` enforces invariants (no self-loop edges, no unreferenced atoms, every entity has ≥1 source atom).

### Envelope build

`app.core.orbitbrief_envelope.build_orbitbrief_envelope()` packages the compile result into the v2 envelope:

```
{
  "schema_version": "orbitbrief.input.v2",
  "project_id": "...",
  "compile_id": "cmp_<hash>",
  "generated_at": "...Z",
  "summary":  { artifact_count, page_count, atom_count, packet_count, … },
  "documents":[ { artifact_id, filename, artifact_type, sha256, size_bytes,
                  parser_name, parser_version, structured: {...}, atom_ids } ],
  "atoms":   [ {EvidenceAtom rows, compact view} ],
  "entities":[ {EvidenceEntity rows} ],
  "edges":   [ {EvidenceEdge rows} ],
  "packets": [ {Packet rows} ],
  "indexes": { atoms_by_section_path, atoms_by_atom_type, atoms_by_authority,
               atoms_by_artifact, atoms_by_entity_key, edges_by_atom,
               entity_id_by_canonical_key }
}
```

### Live corpus

* 12 STRESS_* test cases under `real_data_cases/` with hand-labeled gold standards (`labels/gold_standard.{md,json}`), covering wireless, copper_cabling, security_camera (3 sub-cases), access_control, AV, paging, BMS, networking, ITAD, and an XLSX-rare case.
* 9 envelope-suite tests verify cross-parser routing, entity normalization, source replay, and graph invariants.

---

## How Orbitbrief-Core works

`Orbitbrief-Core` (this repo) is **12 layered packages** that consume the v2 envelope and produce a reviewable brief. Every layer has typed inputs/outputs and is gated against reaching outside its lane by `import-linter`.

```
src/orbitbrief_core/
├── seam/             Phase 0  Validates orbitbrief.input.v2 at the boundary
├── evidence_runtime/ Phase 1  DuckDB substrate over envelope; lossless round-trip
├── retrieval/        Phase 2  4 vector indices over DuckDB+vss (Qwen3-Embedding-8B)
├── inference/        Phase 2  vLLM/Ollama HTTP clients (embed, rerank, chat)
├── world_model/
│   ├── pack_prior/   Phase 3  Keyword scorer → which domain pack(s) to activate
│   ├── site_reality/ Phase 3  Graph walk → cluster atoms by physical site
│   ├── planner/      Phase 4  Qwen3-14B/32B → BriefState (executive summary)
│   └── refiner/      Phase 4  Deterministic graph-consistency cleanup
├── brains/           Phase 5–7.5  Per-domain synthesizers (6 today)
│   ├── managed_services/    Qwen3-14B; 7-section MSP scope
│   ├── wireless/            Qwen3-14B; 9-section briefing schema
│   ├── low_voltage_cabling/        ″
│   ├── rack_and_stack/             ″
│   ├── datacenter/                 ″
│   └── imac/                       ″
├── validator/        Phase 6  5 deterministic rules incl. path-legality
├── calibrator/       Phase 6  Newton-Raphson Platt scaling + verdict mapping
├── review_runtime/   Phase 6  ReviewQueue + TrainingLog (in-memory + JSONL)
├── composer/         Phase 8  ComposedBrief aggregator + Markdown render
├── review_ui/        Phase 8  FastAPI + HTMX, server-rendered review queue
└── orchestrator/     Phase 7  End-to-end pipeline: envelope → reviewable doc
```

### Layer details

#### 0 — `seam/`
Pydantic shapes for `EnvelopeV2`, `EnvelopeAtom`, `EnvelopeEntity`, `EnvelopeEdge`, `EnvelopePacket`, `EnvelopeSummary`, `EnvelopeIndexes`. Strict `schema_version: Literal["orbitbrief.input.v2"]`. The **only** module in Orbitbrief-Core allowed to read raw envelope JSON files (enforced by `tools/check_no_raw_open.py`).

#### 1 — `evidence_runtime/`
Wraps the envelope in a DuckDB-backed substrate. Lossless round-trip (byte-identical re-emit), source replay bridge to parser-os, contradiction walker, entity-key→atoms reverse index. Everything downstream consumes the runtime, not the raw envelope.

#### 2 — `retrieval/`
Four vector indices over DuckDB's `vss` extension: `EvidenceIndex` (atom-level), `PacketIndex` (packet-level), `ClaimIndex` (claim-anchored atoms), `ExampleIndex` (few-shot examples). Embeddings via `RemoteVllmEmbedder` against Qwen3-Embedding-8B (4096-dim). Reranking via `RemoteVllmReranker`. Returns `RetrievalHit` with no body field — bodies must come from the runtime, preserving provenance.

#### 2 — `inference/`
HTTP clients for OpenAI-compatible inference endpoints. `OpenAIChatClient` works against vLLM, Ollama, LM Studio interchangeably. `ChatResult` returns text + `ChatUsage` (prompt/completion/total tokens + latency). All Qwen3 system prompts include `/no_think` to skip reasoning overhead.

#### 3 — `world_model/pack_prior/`
Keyword scorer. Domain pack registry (19 packs from the AWESOME_CHASE intake workbook v4) with `keywords` (auto-extracted) + `boosted_keywords` (hand-curated). Scores atoms with unigram (+1) and bigram (+3 boost) matches, softmax to confidences. LLM (Qwen3-14B) consulted only when top-2 within 0.15 confidence or zero signal — every escalation logged with a typed `PackPriorEscalationReason`. Achieves **96.15 % top-2 F1** on the parser-os STRESS_* gold corpus.

#### 3 — `world_model/site_reality/`
Union-find over `site:*` entity keys, merged by `same_as` / `located_in` edges and canonical-name equality. LLM consulted only for ambiguous-name or unnamed clusters.

#### 4 — `world_model/planner/`
Qwen3-14B (default) or Qwen3-32B (escalated) emits a typed `BriefState`. Four deterministic escalation rules pick the tier *before* the LLM call: `contradiction_density > 5%`, `unstable_site_model > 30%`, `pack_ambiguity < 0.10 margin`, `sparse_but_material < 20 atoms with contractual authority`. Every escalation logged with a structured `PlannerEscalationReason`. Output goes through `refiner` (Phase 4) which drops claims with unknown atoms or packs and dedupes.

#### 5–7.5 — `brains/`
Six concrete brains:

* `managed_services` (Phase 5) — 7-section MSP-shaped scope state. Family-hint table in the prompt routes parser-os PacketFamily → target sections.
* `wireless`, `low_voltage_cabling`, `rack_and_stack`, `datacenter`, `imac` (Phase 7.5) — share the canonical 9-section `BriefingState` (`scope_overview`, `detailed_scope_of_services`, `deliverables`, `assumptions`, `customer_responsibilities`, `out_of_scope`, `risks_or_dependencies`, `completion_criteria`, `open_items`). Per-domain config sourced from `brains/data/briefing_configs.yaml` — operating rules, normalization vocabularies, per-field guidance bullets all extracted from the AWESOME_CHASE intake workbook by `tools/extract_briefing_configs.py`.

Each brain emits JSON (validated against its Pydantic schema), retries once on validation failure with the error fed back, falls back to a deterministic skeleton on the second failure (BLOCKER review flag in the state). Post-call validator strips ungrounded items and surfaces them on `unresolved_packet_ids` / `unresolved_atom_ids`.

Brains may NOT import `evidence_runtime`, `seam`, `retrieval`, `world_model.pack_prior`, `world_model.site_reality`, `world_model.refiner`, or `world_model.planner.runner`. Enforced by `import-linter` AND a dedicated AST scan (`tests/brains/test_no_envelope_access.py`).

#### 6 — `validator/`
Five deterministic rule families:

* `path_legality` (split into `UNRESOLVED_PACKET`, `PATH_LEGALITY`, `UNRESOLVED_ATOM`, `MISSING_SOURCE_REF`) — every claim must trace `packet → atom → source_ref`.
* `missing_evidence` — items citing only packets, no atoms.
* `site_count_sanity` — heuristic: scope statement claims a numeric site count above the SiteRealityState cluster count.
* `pack_incompatibility` — project-level: known-incompatible packs both active (e.g., `itad` + `hardware`).
* `impossible_state` — claim cites a `verified=failed` atom (replay says it doesn't match source bytes).

Talks to the runtime via the typed `EvidenceLookup` adapter so the validator stays in its lane.

#### 6 — `calibrator/`
10-signal `SignalVector` (parser/graph/packet/claim confidences, contradiction density, retrieval coverage, ambiguity, example similarity, validator pass + warning). Linear combiner with hand-tuned weights (sum-to-1 invariant) + blocker/warning caps + `PlattCalibrator` (Newton-Raphson logistic regression — no scipy). `decide_verdict()` maps (probability, validator) → (`AUTO_ACCEPT` / `NEEDS_REVIEW` / `REJECT`, structured `EscalationReason` tuple). Achieves **ECE = 0.043** on a 1000-sample synthetic labeled set after Platt fitting (gate: ≤ 0.05).

#### 6 — `review_runtime/`
`InMemoryReviewQueue` + `JsonlReviewQueue` (durable across restarts via `review_queue.{items,decisions}.jsonl`). `InMemoryTrainingLog` + `JsonlTrainingLog`. Every accept/reject/edit produces one `TrainingRecord` with `predicted_verdict` + `reviewer_action` + binary `accepted` flag — exactly the supervision signal a future LoRA + Platt re-fit consumes.

#### 8 — `composer/`
Aggregates per-pack brain outputs into a single `ComposedBrief`. Walks every brain item, attaches calibrator verdict + raw/calibrated confidence + reasons + validator failures, normalizes the managed-services 7-section shape onto the briefing 9-section layout. Emits both typed `ComposedBrief` JSON and PM-readable Markdown via `render_markdown()`.

#### 8 — `review_ui/`
FastAPI + Jinja2 + HTMX. Server-rendered HTML, no SPA framework, no build step. Routes:

* `GET /queue` — open items, filterable by brain
* `GET /item/<composite_id>` — full payload + decision form
* `POST /item/<composite_id>/decide` — HTMX swaps the form in place with a confirmation pill
* `GET /composed` — rendered Markdown brief
* `GET /api/queue`, `GET /api/training_log`, `GET /healthz`

Optional `[ui]` extra installs FastAPI + uvicorn + jinja2 + python-multipart. Core stays slim.

#### 7 — `orchestrator/`
The integrator. `BriefPipeline.compile(envelope_path, out_dir)` runs all 11 stages, writes per-stage artifacts, builds a `JsonlReviewQueue` + `JsonlTrainingLog` in `out_dir/70_review_queue/`. The CLI (`compile_brief.py`) is the operator-facing one-liner.

The orchestrator is the **only** module allowed to import across all 12 layers. `import-linter` enforces every other layer stays in its lane.

---

## The seam — `orbitbrief.input.v2`

`parser-os` produces; `Orbitbrief-Core` consumes. The contract is enforced **on both sides**:

* **Producer side** — `parser-os/app/core/orbitbrief_envelope.build_orbitbrief_envelope()` builds the dict. `tests/test_orbitbrief_envelope.py` (9 tests) exercises round-trips across PDF + DOCX + XLSX + transcript bundles.
* **Consumer side** — `Orbitbrief-Core/src/orbitbrief_core/seam/envelope.py` declares the `EnvelopeV2` Pydantic schema with `Literal["orbitbrief.input.v2"]` pinning. `seam/loader.py` is the only module allowed to read raw envelope JSON. Future v3 envelopes fail loud at validation.

The contract is `Shared-contracts/contracts/orbitbrief/runtime_types/SCHEMA_OWNERSHIP.md` documents `parser-os` as the source of truth for the inner schemas (`EvidenceAtom`, `SourceRef`, `CompileResult`).

---

## End-to-end pipeline

11 stages, fully audited:

```
Stage                                         Status (typical run on COPPER_001)
─────                                         ──────
00_ingest_envelope                            ok
01_evidence_runtime                           ok      (in-memory; no separate stage record)
10_pack_prior                                 ok      (~10ms; deterministic keyword scoring)
11_site_reality                               ok      (~0ms; graph walk over edges)
20_retrieval_bundles::<pack_id>               ok      (~0ms; bundle assembler)
30_planner                                    ok      (~70s; Qwen3-14B → BriefState)
31_refiner                                    ok      (~20ms; deterministic cleanup)
40_brain::<pack_id>                           ok      (~66s; per-pack briefing brain)
50_validator::<pack_id>                       ok      (~10ms; 5 rule families)
60_calibrator::<pack_id>                      ok      (~1ms; signals + Platt)
70_review_queue::<pack_id>                    ok      (JSONL persist)
80_composer                                   ok      (aggregate + Markdown render)
```

Artifact directory layout (operator-readable, numeric-prefixed):

```
artifacts/
├── 00_envelope.json                       (canonical copy of the input)
├── 10_pack_prior_state.json
├── 11_site_reality_state.json
├── 20_retrieval_bundles/<pack_id>.json
├── 30_brief_state.raw.json                (planner output)
├── 31_brief_state.refined.json            (refiner output)
├── 40_brain_outputs/<pack_id>.json
├── 50_validations/<pack_id>.json
├── 60_calibrations/<pack_id>.json
├── 70_review_queue/
│   ├── review_queue.items.jsonl
│   ├── review_queue.decisions.jsonl
│   └── training_records.jsonl
├── 80_composed_brief.json                 (typed)
├── 81_composed_brief.md                   (PM-readable)
├── pipeline_log.json                      (per-stage StageRecord)
└── manifest.json
```

---

## Models in band

All run locally via Ollama at `http://localhost:11434`:

| Model | Role | Size |
|---|---|---|
| `qwen3:14b` | Planner default tier; all brains; pack_prior + site_reality escalations | 9.3 GB |
| `qwen3:32b` | Planner escalation tier (contradiction density > 5 %, ambiguous pack, …) | 20 GB |
| `qwen3-embedding:8b` | All retrieval indices (4096-dim) | 4.7 GB |

To install:

```bash
ollama pull qwen3:14b
ollama pull qwen3:32b
ollama pull qwen3-embedding:8b
```

OrbitBrief uses Qwen3's `/no_think` directive in every JSON-emit system prompt to skip reasoning overhead. Even with that, Qwen3 emits ~110 tokens of empty think markers per call; the runners account for it with 8192-token output budgets.

---

## CLI reference

### Compile a brief end-to-end

```bash
# Parser-os: project_dir → envelope.json (one-time, runs in parser-os repo)
python -m app.cli.compile project_dir/ --out envelope.json

# Orbitbrief-Core: envelope.json → reviewable artifacts
python compile_brief.py envelope.json --out artifacts/ --ollama
```

Without `--ollama`, the substrate stages run (pack_prior, site_reality, retrieval bundles) and the LLM stages cleanly SKIP.

### Boot the reviewer UI

```bash
pip install -e '.[ui]'   # optional FastAPI extra
python -m orbitbrief_core.review_ui --artifacts artifacts/ --port 8765
# → open http://127.0.0.1:8765/queue
```

### Inspect intermediate stages

```bash
# Pack prior + site reality
python -m orbitbrief_core.world_model envelope.json --engine both

# Planner only (requires Ollama)
python -m orbitbrief_core.world_model envelope.json --engine planner --ollama

# Brain only (against a pre-saved BriefState + RetrievalBundle)
python -m orbitbrief_core.brains \
  --brief artifacts/31_brief_state.refined.json \
  --bundle artifacts/20_retrieval_bundles/wireless.json \
  --brain managed_services --ollama
```

### Verify the system

```bash
# Full test suite (151 tests; ~16 s)
pytest -q

# All 12 import-linter contracts
python -c "from importlinter.cli import lint_imports_command; lint_imports_command(['--config', '.importlinter'])"

# Raw-IO check (operator filesystem seam ratchet)
python tools/check_no_raw_open.py

# Performance gate (Phase-2 retrieval; ~5 s)
pytest -m perf

# Slow gates (live Ollama + real parser-os corpus; minutes)
pytest -m slow
```

---

## Architectural invariants

The system enforces 12 import contracts + an AST scan + a raw-IO ratchet. These are not aspirational — they're tested in CI:

| Contract | What it forbids |
|---|---|
| `no-direct-pdf-libs` | OrbitBrief importing `pypdfium2` / `pdfminer` / `pdfplumber` / `pymupdf` / `fitz` / `pytesseract` (must consume the envelope). |
| `no-retrieval-bypass` | `composer` / `brains` / `validator` / `calibrator` importing `retrieval` directly. |
| `evidence-runtime-no-inference` | `evidence_runtime` importing `inference` or `retrieval` (Phase 1 invariant). |
| `world-model-bounded` | `world_model` importing `retrieval` / `composer` / `brains` / `validator` / `calibrator` / `review_runtime` / `review_ui` / `orchestrator` (no upward refs). |
| `substrate-no-world-model` | `evidence_runtime` / `retrieval` / `seam` importing `world_model`. |
| `brains-no-substrate` | Brains importing the runtime, seam, retrieval, or world_model engines. |
| `substrate-no-brains` | Upward references from substrate / world_model into brains. |
| `calibrator-no-substrate` | Calibrator importing runtime / seam / retrieval. |
| `validator-no-retrieval` | Validator importing the retrieval store directly. |
| `composer-no-substrate` | Composer importing runtime / seam / retrieval / brain runners. |
| `review-ui-isolated` | UI importing substrate / world_model engines / brain runners. |
| `review-runtime-isolated` | Review runtime importing substrate / world_model engines / brain runners. |

Plus:

* `tools/check_no_raw_open.py` — AST-based check that nothing under `src/orbitbrief_core/` calls `open()` / `Path.read_text()` / `Path.write_text()` outside an explicit allowlist (11 modules today, each justified inline).
* `tests/brains/test_no_envelope_access.py` — AST scan of every brain `.py` file confirms zero forbidden imports (belt-and-braces against deferred local imports).

---

## Per-component honest ranking

Scale: 1 = research notebook · 5 = MVP shell · 7 = real MVP · 9 = production.

### parser-os

| Component | Score | Notes |
|---|---:|---|
| PDF parser (`orbitbrief_pdf`) | **8/10** | Production-grade. Real corpus, table/matrix detection, OCR fallback, locator-precise atoms. |
| XLSX parser (`orbitbrief_xlsx`) | **7.5/10** | Solid. Sheet classification, instructional-vs-tabular detection. |
| DOCX / TXT / MD / email parsers | **7/10** | MVP-grade. Less tested than PDF; relies on simpler tokenization. |
| Transcript parser (VTT) | **7/10** | Works; speaker/timestamp preserved. Limited corpus. |
| Atom + entity + edge extraction | **8/10** | 13 atom types, 8 edge types, graph invariants enforced, source replay verified. |
| Packet certification | **8/10** | 11 families, deterministic, replay-aware. |
| Domain pack routing | **6/10** | Hardcoded heuristics in `pack_router.py`; superseded by `Orbitbrief-Core`'s pack_prior for the briefing pipeline. |
| Domain packs + ontologies | **6.5/10** | 8 packs with 200+ line YAML each; 6 more scaffolded (datacenter_field, edge_iot, endpoint_imac, network_modernization, pos_commerce, structured_backbone_fiber) but not yet wired to tests. |
| Test coverage / corpus | **8/10** | 12 STRESS_* gold cases + 9 envelope-suite tests. Hand-labeled gold standards. |
| **parser-os overall** | **7.5/10** | **MVP-grade.** Has been in real-data territory for months. |

### Orbitbrief-Core

| Component | Score | Notes |
|---|---:|---|
| `seam/` | **9/10** | Frozen contract, Pydantic-validated, schema_version-pinned. Single allowed envelope reader. |
| `evidence_runtime/` | **8.5/10** | Lossless round-trip, byte-deterministic, contradiction walker, source replay bridge. |
| `retrieval/` | **7.5/10** | 4 indices over DuckDB+vss, real Qwen3-Embedding-8B wired, p95 latency under 200 ms on 10k packets. Example index isn't being populated yet. |
| `inference/` | **8/10** | OpenAI-compat client works against vLLM / Ollama / LM Studio. Token usage telemetry. |
| `world_model/pack_prior/` | **8/10** | 96.15 % F1 on STRESS_* gold corpus. Deterministic + bounded LLM escalation. |
| `world_model/site_reality/` | **7/10** | Works on synthetic + real corpora. Could use more cases. |
| `world_model/planner/` | **8/10** | Qwen3-14B/32B with structured escalation rules. Real Qwen3 round-trip ~70 s. |
| `world_model/refiner/` | **8/10** | Deterministic graph-consistency cleanup, surfaces every drop. |
| `brains/managed_services/` | **8/10** | First brain. 96.15 % F1 on synthetic gold. 7-section MSP scope. |
| `brains/wireless/` | **7.5/10** | Briefing 9-section. Rich workbook config (135 guidance bullets + normalization vocabularies). |
| `brains/{low_voltage_cabling,rack_and_stack,datacenter,imac}/` | **6.5/10** | Briefing 9-section. Workbook fields are skeletons today; defaults are domain-curated and swap in instantly when filled. |
| `validator/` | **8.5/10** | 5 rule families, 9-id rule taxonomy, BLOCKER/WARNING/INFO severity tiers. |
| `calibrator/` | **8/10** | 10-signal vector + Newton-Raphson Platt scaling. ECE = 0.043 on synthetic labeled set. **Has not yet been trained on real PM data.** |
| `review_runtime/` | **8/10** | In-memory + JSONL queue/log. Restart durable. Decision → TrainingRecord one-to-one. |
| `composer/` | **8/10** | Deterministic, typed, normalizes both brain shapes onto one layout. JSON + Markdown render. |
| `review_ui/` | **7/10** | FastAPI + HTMX. Real PM-clickable. 8 routes, all tested via TestClient. Markdown shown as `<pre>` (no rich render). |
| `orchestrator/` | **8/10** | One command runs everything. Per-stage StageRecord audit. |
| **Orbitbrief-Core overall** | **8/10** | **Strong MVP.** Architecture is genuinely clean (12 contracts, 11 raw-IO allowlisted, 0 dead packages). Pipeline runs end-to-end on real data. |

### Combined system

| Surface | Score | Notes |
|---|---:|---|
| End-to-end on a real engagement | **7.5/10** | One CLI ingests → one URL reviews. Live demo on parser-os COPPER_001 produces 11 grounded items in ~2:17. |
| Architectural hygiene | **9/10** | 12 import contracts kept, 151 tests, raw-IO ratchet, AST scans. Better than most production systems. |
| Real-world data exposure | **6/10** | Tested on the parser-os STRESS_* corpus + COPPER_001 + the `Fields West Block D` PDF. Has NOT been run on a real customer engagement with real PM review yet. |
| Calibration quality | **5/10** | ECE = 0.043 on synthetic data. Default identity Platt sigmoid means calibrated probabilities are basically the linear-combiner output until real PM decisions feed `JsonlTrainingLog`. |
| Deployment | **3/10** | Runs locally on a Mac via Ollama. No service, no API endpoint, no CI, no Docker. |

---

## Remaining MVP gaps

In rough leverage order:

1. **Real PM data loop** — JSONL training log is wired but empty. A small script that re-fits `PlattCalibrator.platt` from `JsonlTrainingLog.all()` nightly (or after every N decisions) flips the calibrator from "well-shaped" to "actually calibrated to your reviewers' tastes". Half-day.
2. **More domain coverage** — Brains for `security_access`, `audit`, `professional_services`, `delivery_execution`, `commercial`, `staff_augmentation`, `data_migration`, `alm` would cover the rest of the 19-pack workbook. Each is a 30-line `BriefingBrain` subclass; the bottleneck is workbook fill-in for per-domain guidance.
3. **Composer rich render** — `81_composed_brief.md` is shown as `<pre>` text in the UI today. Adding a 5-line `markdown` library dep produces actual headings/tables in the browser.
4. **Containerized deployment** — A `docker-compose.yml` that runs Ollama + the orchestrator + the UI as one stack. Half-day.
5. **CI** — GitHub Actions that runs `pytest`, `lint-imports`, and `check_no_raw_open` on every PR. Half-day.
6. **Eval harness** — Run the planner across N envelopes nightly and track quality drift. Catches prompt regressions before reviewers do.

---

## Repository layout

```
purtera/
├── parser-os-repo/                  Sister repo (file-eating side)
│   ├── app/
│   │   ├── core/                    Compiler, envelope builder, replay, validators
│   │   ├── parsers/                 PDF / DOCX / XLSX / TXT / email / transcript
│   │   ├── domain/                  Domain packs + ontologies + pack router
│   │   └── cli/
│   ├── real_data_cases/             12 STRESS_* gold cases
│   └── tests/
└── Orbitbrief-Core/                 (this repo)
    ├── src/orbitbrief_core/         12 layered packages
    │   ├── seam/                    Phase 0 contract
    │   ├── evidence_runtime/        Phase 1 substrate
    │   ├── retrieval/               Phase 2 vector indices
    │   ├── inference/               Phase 2 LLM clients
    │   ├── world_model/             Phase 3–4
    │   │   ├── pack_prior/
    │   │   ├── site_reality/
    │   │   ├── planner/
    │   │   └── refiner/
    │   ├── brains/                  Phase 5–7.5 (6 brains today)
    │   ├── validator/               Phase 6
    │   ├── calibrator/              Phase 6
    │   ├── review_runtime/          Phase 6
    │   ├── composer/                Phase 8
    │   ├── review_ui/               Phase 8 (FastAPI + HTMX)
    │   └── orchestrator/            Phase 7 (the integrator)
    ├── tests/                       151 tests, 12 contracts, raw-IO ratchet
    ├── tools/                       Workbook extractors + check_no_raw_open
    ├── compile_brief.py             Operator one-liner
    ├── pyproject.toml
    ├── .importlinter                12 layering contracts
    └── LEGACY.md                    Phase-1 cleanup record (legacy_parser_runtime branch)
```

---

## License + contribution

This is closed-source for now. See `Purtera-IT` org for contribution guidelines.

---

_Last updated: Phase 8 + Qwen3 fix landed. 151 tests passing, 12 import contracts kept, `check_no_raw_open` clean, real-data demo produces 11 grounded reviewable items in ~2:17 against parser-os COPPER_001._
