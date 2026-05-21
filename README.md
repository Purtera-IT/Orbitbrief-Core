# Orbitbrief-Core

OrbitBrief-Core turns the `orbitbrief.input.v2` envelope produced by
[parser-os](https://github.com/Purtera-IT/parser-os) into a calibrated,
reviewable PM brief — plus a SOW draft and an RFP draft, all grounded
to source artifacts.

```
envelope.json  →  brains + intelligence  →  PM_HANDOFF.json
                                          →  SOW_DRAFT.md
                                          →  RFP_DRAFT.md
                                          →  /queue (FastAPI review UI)
```

End-to-end architecture across both repos: [SYSTEM_README.md](SYSTEM_README.md).
Field-by-field UI catalog: [parser-os/OUTPUTS_FOR_UI.md](../parser-os-repo/OUTPUTS_FOR_UI.md).
Azure deployment plan: [parser-os/INTEGRATION_GUIDE.md](../parser-os-repo/INTEGRATION_GUIDE.md).

---

## Quickstart

Requires Python 3.12+ and Ollama running locally (or remote via
`OLLAMA_BASE_URL`).

```bash
pip install -e ".[ui]"
ollama pull qwen3:14b
ollama pull qwen3-embedding:8b

# From an envelope (parser-os already ran)
python compile_brief.py /path/to/envelope.json --out artifacts/ --ollama

# From a raw case directory (auto-invokes parser-os first)
export PARSER_OS_ROOT=/abs/path/to/parser-os-repo
python compile_brief.py /path/to/case_dir --out artifacts/ --ollama

# One-shot "never skip the LLM" handoff
./pm_handoff.sh /path/to/case_dir /path/to/out_dir

# Boot the review UI
python -m orbitbrief_core.review_ui --artifacts artifacts/ --port 8765
# → http://127.0.0.1:8765/queue
```

Without `--ollama`, substrate stages run and the LLM stages cleanly
SKIP — useful for unit smoke tests.

---

## Layers

```
src/orbitbrief_core/
├── seam/              Phase 0  Pydantic schema for orbitbrief.input.v2
├── evidence_runtime/  Phase 1  DuckDB substrate over the envelope
├── retrieval/         Phase 2  4 vector indices (Qwen3-Embedding-8B)
├── inference/         Phase 2  OpenAI-compatible HTTP client (Ollama/vLLM/LM Studio)
├── world_model/       Phase 3-4
│   ├── pack_prior/    Keyword scorer → which domain pack(s) activate
│   ├── site_reality/  Graph walk → cluster atoms by physical site
│   ├── planner/       Qwen3-14B/32B → BriefState
│   └── refiner/       Deterministic graph-consistency cleanup
├── brains/            Phase 5-7.5  Per-domain synthesizers (15 brains today)
├── validator/         Phase 6  5 deterministic rule families
├── calibrator/        Phase 6  10-signal vector + Platt scaling
├── review_runtime/    Phase 6  ReviewQueue + TrainingLog (JSONL durable)
├── composer/          Phase 8  ComposedBrief + Markdown render
├── pm_handoff/        Phase 9  PM brief, SOW draft, RFP draft, intelligence
├── review_ui/         Phase 8  FastAPI + HTMX queue
└── orchestrator/      Phase 7  End-to-end pipeline
```

### Brains (15 today)

`audio_visual`, `audit`, `building_management_systems`,
`camera_vms_operations`, `datacenter` (planned), `electrical`, `imac`,
`low_voltage_cabling`, `managed_services`, `network_maintenance`,
`procurement_finance`, `professional_services`, `rack_and_stack`,
`wireless`.

Each emits a typed Pydantic state; the post-call validator strips
ungrounded items. Workbook-driven per-domain config lives in
[brains/data/briefing_configs.yaml](src/orbitbrief_core/brains/data/briefing_configs.yaml).

### PM Handoff (Phase 9)

`pm_handoff/` is the consumer-facing layer. It produces a single
`PM_HANDOFF.json` payload (59 top-level fields) plus the rendered SOW
and RFP drafts. Major modules:

| Module | Responsibility |
|---|---|
| `builder.py` | Wires every field into the `PMHandoff` dataclass |
| `models.py` | `PMHandoff`, `GapCard`, `EvidenceCard`, etc. |
| `pm_intelligence.py` | Margin view, critical path, lead-time flags, parser quality score, run telemetry, drift snapshot, urgency signals, customer-answer slots |
| `reconciliation.py` | Money / date / quantity reconciliation + action item dedup |
| `sow_draft.py` | Renders SOW_DRAFT.md |
| `rfp_draft.py` | Renders RFP_DRAFT.md |
| `render_markdown.py` | PM-readable PM_HANDOFF.md |
| `render_html.py` | Optional HTML dashboard |

Field catalog with concrete example values:
[parser-os/OUTPUTS_FOR_UI.md](../parser-os-repo/OUTPUTS_FOR_UI.md).

---

## Architectural invariants

12 import-linter contracts + an AST scan + a raw-IO ratchet — tested
in CI. The seam is the only module allowed to read raw envelope JSON;
brains may not reach into the substrate; the orchestrator is the only
module allowed to import across layers.

| Contract | Forbids |
|---|---|
| `no-direct-pdf-libs` | Importing `pypdfium2` / `pdfminer` / `pdfplumber` / `pymupdf` / `fitz` / `pytesseract` in Orbitbrief-Core |
| `no-retrieval-bypass` | `composer` / `brains` / `validator` / `calibrator` importing `retrieval` |
| `evidence-runtime-no-inference` | `evidence_runtime` importing `inference` or `retrieval` |
| `world-model-bounded` | `world_model` importing upward (`composer`, `brains`, etc.) |
| `substrate-no-world-model` | `evidence_runtime` / `retrieval` / `seam` importing `world_model` |
| `brains-no-substrate` | Brains importing the runtime, seam, retrieval, or world model engines |
| `substrate-no-brains` | Upward references from substrate into brains |
| `calibrator-no-substrate` | Calibrator importing runtime / seam / retrieval |
| `validator-no-retrieval` | Validator importing the retrieval store directly |
| `composer-no-substrate` | Composer importing runtime / seam / retrieval / brain runners |
| `review-ui-isolated` | UI importing substrate / world-model engines / brain runners |
| `review-runtime-isolated` | Review runtime importing substrate / world-model engines / brain runners |

Run them:

```bash
python -c "from importlinter.cli import lint_imports_command; \
  lint_imports_command(['--config', '.importlinter'])"
python tools/check_no_raw_open.py
pytest -q
```

---

## CLI reference

```bash
# Full pipeline from envelope
python compile_brief.py envelope.json --out artifacts/ --ollama

# Full pipeline from a case dir (auto-invokes parser-os)
python compile_brief.py case_dir/ --out artifacts/ --ollama --quiet-parser

# Batch a corpus
python compile_corpus.py corpus_root/ --out results_dir/ --ollama

# Never-skip-LLM hardened script (errors loud if Ollama is down)
./pm_handoff.sh case_dir/ [out_dir/]

# Review UI
python -m orbitbrief_core.review_ui --artifacts artifacts/ --port 8765

# Intermediate stages (debugging)
python -m orbitbrief_core.world_model envelope.json --engine pack_prior
python -m orbitbrief_core.world_model envelope.json --engine planner --ollama
python -m orbitbrief_core.brains \
  --brief artifacts/31_brief_state.refined.json \
  --bundle artifacts/20_retrieval_bundles/wireless.json \
  --brain managed_services --ollama
```

---

## Pipeline output layout

```
artifacts/
├── 00_envelope.json                 (canonical copy of input)
├── 10_pack_prior_state.json
├── 11_site_reality_state.json
├── 20_retrieval_bundles/<pack>.json
├── 30_brief_state.raw.json
├── 31_brief_state.refined.json
├── 40_brain_outputs/<pack>.json
├── 50_validations/<pack>.json
├── 60_calibrations/<pack>.json
├── 70_review_queue/
│   ├── review_queue.items.jsonl
│   ├── review_queue.decisions.jsonl
│   └── training_records.jsonl
├── 80_composed_brief.json
├── 81_composed_brief.md
├── 90_pm_handoff/
│   ├── PM_HANDOFF.json              (59-field consumer payload)
│   ├── PM_HANDOFF.md
│   ├── SOW_DRAFT.md
│   └── RFP_DRAFT.md
├── pipeline_log.json
└── manifest.json
```

Per-field UI catalog with example values lives in
[parser-os/OUTPUTS_FOR_UI.md](../parser-os-repo/OUTPUTS_FOR_UI.md).

---

## Models

All run locally via Ollama at `http://localhost:11434` (or remote via
`OLLAMA_BASE_URL`).

| Model | Role | Size |
|---|---|---|
| `qwen3:14b` | Planner default tier; all brains; escalation tiebreaks | 9.3 GB |
| `qwen3:32b` | Planner escalation tier (contradiction density > 5 %, ambiguous pack, …) | 20 GB |
| `qwen3-embedding:8b` | All retrieval indices (4096-dim) | 4.7 GB |

```bash
ollama pull qwen3:14b
ollama pull qwen3:32b
ollama pull qwen3-embedding:8b
```

Every JSON-emit system prompt includes Qwen3's `/no_think` directive
to skip reasoning overhead; runners budget 8192 output tokens to
absorb leftover think markers.

---

## Repo layout

```
Orbitbrief-Core/
├── src/orbitbrief_core/    # 13 layered packages (see "Layers")
├── tests/                  # full test suite
├── tools/                  # workbook extractors + check_no_raw_open + corpus runners
├── config/runtime/         # extractor + parser runtime config
├── docs/                   # analyst prompts + site_schematic docs (separate sub-system)
├── compile_brief.py        # operator one-liner
├── compile_corpus.py       # batch operator one-liner
├── pm_handoff.sh           # never-skip-LLM hardened operator script
├── pyproject.toml
├── .importlinter           # 12 contracts
├── LEGACY.md               # Phase-1 cleanup record
└── README.md               # this file
```

---

## License + contribution

Closed-source. See `Purtera-IT` org for contribution policy.
