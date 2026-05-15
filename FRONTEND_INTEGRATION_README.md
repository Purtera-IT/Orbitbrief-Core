
# OrbitBrief — Frontend Integration & Capability Reference

> Audience: **frontend / integration engineer** plugging Purpulse UI on top of the OrbitBrief stack.
> Companion docs in this conversation: `QUOTING_PARSER_ORBITBRIEF_MASTER_PLAN.md`, `PURPULSE_AZURE_ARCHITECTURE.md`.
> Order of reading mirrors the runtime flow: **parser-os → Orbitbrief-Core → PM/SA presentation → Azure proxy → SPA.**

---

## 0. The 90-second mental model

```text
   ┌──────────────────────────┐
   │  Customer / vendor files │   PDFs · CSVs · XLSX · MD · DOCX · EML · VTT
   └────────────┬─────────────┘
                │  Blob upload  (Purpulse Function App + Azure Blob)
                ▼
   ┌──────────────────────────┐
   │       parser-os          │   deterministic, no LLM in hot path
   │  (Python, in-monorepo)   │   reads files, emits typed atoms / packets
   └────────────┬─────────────┘
                │  envelope JSON  (orbitbrief.input.v2)
                ▼
   ┌──────────────────────────┐
   │     Orbitbrief-Core      │   uses LLM (Qwen via Ollama on your Mac/GPU)
   │ (Python, GPU host SSH)   │   pack routing → site reality → brains
   └────────────┬─────────────┘    → SOW validator → composer → inspection
                │
                ├─►  91_inspection_report.html        ← engineering audit dashboard
                ├─►  PM_EXECUTIVE_SUMMARY.{md,html}    ← PM landing page (no jargon)
                ├─►  SA_REVIEW_PACKET.{md,html}        ← solution architect packet
                ├─►  PM_HANDOFF.{md,html,json}         ← combined view + JSON for UI
                ├─►  PM_PORTFOLIO_DASHBOARD.{md,html,json}  ← all cases at once
                └─►  PM_QUESTION_QUEUE.csv             ← every customer question
```

The seam between parser-os and Orbitbrief-Core is a typed JSON document called **`orbitbrief.input.v2`**. Treat it as the stable boundary — parser updates and GPU inference upgrades ship independently behind it.

The seam between Orbitbrief-Core and your UI is **`PM_HANDOFF.json`** (per case) and **`PM_PORTFOLIO_DASHBOARD.json`** (across cases). Render those.

---

## Table of contents

1. [parser-os — what it does and what it produces](#1-parser-os--what-it-does-and-what-it-produces)
2. [Orbitbrief-Core — pipeline stages and outputs](#2-orbitbrief-core--pipeline-stages-and-outputs)
3. [The 8 files every run writes per case](#3-the-8-files-every-run-writes-per-case)
4. [PM_HANDOFF.json — the contract you render](#4-pm_handoffjson--the-contract-you-render)
5. [PM_PORTFOLIO_DASHBOARD.json — the cross-case payload](#5-pm_portfolio_dashboardjson--the-cross-case-payload)
6. [91_inspection_report.html — the auditable engineering dashboard](#6-91_inspection_reporthtml--the-auditable-engineering-dashboard)
7. [Operator commands — how runs are triggered](#7-operator-commands--how-runs-are-triggered)
8. [Wiring through the Purpulse Azure Function App](#8-wiring-through-the-purpulse-azure-function-app)
9. [SSH to Mac (Qwen models) from Azure — production transport](#9-ssh-to-mac-qwen-models-from-azure--production-transport)
10. [Local dev — the fastest possible loop](#10-local-dev--the-fastest-possible-loop)
11. [Capabilities matrix — what to surface in UI](#11-capabilities-matrix--what-to-surface-in-ui)
12. [Answers to the master-plan open questions](#12-answers-to-the-master-plan-open-questions)
13. [Glossary](#13-glossary)

---

## 1. parser-os — what it does and what it produces

**Repo:** `parser-os-repo/` (in the same monorepo as the SPA — runs in CPU; no GPU).
**Role:** Deterministic envelope producer. Reads raw customer + vendor files, emits a typed JSON envelope. **No LLM in the hot path.**

### 1.1 What it can read

Production parsers (registered in `app/parsers/registry.py`):

| Parser class | File extensions / signatures | Confidence boost path |
|---|---|---|
| `MarkdownParser` | `.md`, `.markdown` | always 0.96 |
| `XlsxParser` | `.xlsx`, `.csv`; multi-sheet operations workbooks → 0.97 (`xlsx_match:operations_workbook`) | `sniff_operations_workbook_strength` |
| `QuoteParser` | `.xlsx`, `.csv`, `.txt`; cedes `asset_inventory.csv` / `site_list.csv` / `risk_register.csv` etc. to `XlsxParser` | `path_quote_filename_hint`, "part number" tokens |
| `EmailParser` | `.eml`, plus `.txt`/`.md` with `From:` + `Subject:` headers | thread-marker patterns |
| `TranscriptParser` | `.vtt`, `.srt`, `.json` utterance lists, `.txt`/`.md` meeting layouts | "decisions:", "open questions:" markers |
| `DocxParser` | `.docx` | OOXML body + tracked changes |
| `OrbitBriefPdfParser` | `.pdf` (also matches by `%PDF-` magic bytes if mis-extension) | text-rich fast-path; vertical-table extractor for hand-form PDFs |

### 1.2 What it produces — atom types

`AtomType` (enum, `app/core/schemas.py`). Every fact in the source becomes one of:

**Free-text scope shapes**
- `scope_item` · in-scope work bullets that aren't more specific
- `quantity` · numeric counts/units (drops, sites, hours, etc.)
- `exclusion` · explicit out-of-scope / "not included" / NIC
- `customer_instruction` · directives from the customer
- `assumption` · "assume …", "subject to …"
- `open_question` · ambiguity / TBDs / questions
- `constraint` · obligations ("must/shall", access windows, gates)
- `decision` · settled commitments
- `action_item` · owned follow-ups
- `meeting_commitment` · spoken commitments
- `compliance` · references to NFPA / IEEE / ADA / NIST / etc.

**Commercial / BOM shapes**
- `vendor_line_item` · raw BOM/quote lines
- `quote_status` · BOM line commercial status (Pending/Quoted/Awarded)
- `entity` · structured "thing" rows that aren't reduced

**Structured operations rows** (the new heavy hitters)
- `risk` · risk-register rows
- `asset_record` · asset inventory rows
- `support_entitlement` · support tier / SLA matrix rows
- `site_roster` · canonical site list rows
- `lifecycle_status` · EOL / refresh cycle rows
- `form_option_state` · checkbox state (selected=true / selected=false)
- `project_metadata` · workbook readme / dashboard / source-refs rows
- `site_survey_row` · site survey capture rows
- `port_vlan_assignment` · switch-port / patch / VLAN wiring rows
- `circuit_inventory` · WAN circuit rows
- `alert_route` · NOC alert routing matrix rows
- `cutover_validation` · cutover checklist rows
- `conditional_support_boundary` · conditional support-tier prose

The PDF parser additionally types each row with a `value.kind` tag like `field_checklist_row_v2`, `rfi_row`, `runbook_row`, `working_measurement_row`, `port_vlan_assignment`, `workflow_step`, `managed_services_acceptance_checklist_row`, `form_option_state`. These are the structured outputs of the v9/v10 vertical-table extractor.

### 1.3 The envelope (`orbitbrief.input.v2`)

Output schema, top-level keys (`build_orbitbrief_envelope` in `app/core/orbitbrief_envelope.py`):

```jsonc
{
  "schema_version": "orbitbrief.input.v2",
  "project_id":     "COPPER_001_SPRING_LAKE_AUDITORIUM",
  "compile_id":     "<uuid>",
  "generated_at":   "2026-05-15T12:34:56Z",
  "summary":        { /* counts, histograms */ },
  "documents":      [ /* one row per parsed file (artifact) */ ],
  "atoms":          [ /* compact atoms: id, type, text, locator, verified */ ],
  "packets":        [ /* compact packets: id, family, anchor, atom_ids */ ],
  "entities":       [ /* canonical entities: site:*, part_number:*, etc. */ ],
  "edges":          [ /* same_as / supports / contradicts / excludes / requires */ ],
  "indexes":        { /* atoms_by_atom_type, atoms_by_artifact, ... */ }
}
```

> ⚠️ **Key correction vs the master plan:** the top-level key is **`documents`**, not `artifacts`. Per-file payloads (with `artifact_id`, `filename`, `artifact_type`, `structured` projection, `atom_ids`) live under `documents[]`.

### 1.4 What every atom carries

```jsonc
{
  "id": "atm_abc123…",
  "artifact_id": "art_def456…",
  "atom_type": "site_roster",
  "authority_class": "approved_site_roster",   // grounds conflict resolution
  "confidence": 0.94,                          // 0.0 – 1.0
  "text": "Site ID: S01 | Site: Spring Lake High School - Auditorium Wing | Address: …",
  "section_path": ["csv"],
  "locator": { "sheet": "csv", "row": 2, "columns": { "Site ID": "A", … } },
  "verified": "verified"                       // unverified|failed|verified|partial|unsupported
}
```

The `verified` field is what the UI shows as a "source-replay green dot" — `failed` means the parser couldn't confirm the atom by replaying the source bytes.

### 1.5 What you can do with parser-os from a backend

```python
from app.core.compiler import compile_project
from app.core.orbitbrief_envelope import build_orbitbrief_envelope

# Drop a directory of files in. Get the envelope back.
result = compile_project(
    project_dir=Path("/path/to/staged/case/"),
    project_id="COPPER_001_SPRING_LAKE_AUDITORIUM",
    allow_errors=True,                  # keep going on noisy synthetic intake
    allow_unverified_receipts=True,     # don't fail on PDF replay misses
)
envelope = build_orbitbrief_envelope(
    project_dir=Path("/path/to/staged/case/"),
    compile_result=result,
)
```

CLI (Typer) — every subcommand under `python -m app.cli`:

| Command | Purpose | Writes |
|---|---|---|
| `compile` | Compile one case | `<--out>` JSON, optional review folder, optional `.orbitbrief/` envelope |
| `orbitbrief-envelope` | Re-emit envelope from a saved `CompileResult` | `orbitbrief.input.json`, `orbitbrief.input.md` |
| `batch-compile` | Compile a glob of cases | per-project JSON + optional review/envelope |
| `compare` | Compare a compiled run to a gold fixture | stdout report |
| `init` | Scaffold a case dir with `project.yaml` + `artifacts/` | new tree |
| `matrix` | Run gold matrix across cases | matrix JSON + optional Markdown |
| `report` | Full production report bundle | `result.json`, `trace.json`, `REPORT.md`, `reviews/`, ZIP |
| `health` | Liveness probe | "ok" |

---

## 2. Orbitbrief-Core — pipeline stages and outputs

**Repo:** `Orbitbrief-Core/` (separate, intended to live on the GPU host reachable via SSH).
**Role:** Reads the envelope, runs the LLM-backed synthesis pipeline, emits the per-case dashboards your UI consumes.

### 2.1 The pipeline (`src/orbitbrief_core/orchestrator/pipeline.py`)

Every numbered stage writes a JSON file you can parse. Order:

| Stage | Name | Reads | Writes | State produced |
|---|---|---|---|---|
| 00 | `00_ingest_envelope` | input envelope | `00_envelope.json` | DuckDB-backed `EvidenceRuntime` |
| 10 | `10_pack_prior` | runtime + optional LLM | `10_pack_prior_state.json` | `PackPriorState` (which workstreams) |
| 11 | `11_site_reality` | runtime + optional LLM | `11_site_reality_state.json` | `SiteRealityState` (clusters with kind/publishable) |
| 20 | `20_retrieval_bundles::<pack>` | runtime + active packs | `20_retrieval_bundles/<pack>.json` | per-pack `RetrievalBundle` |
| 30 | `30_planner` | runtime + priors + LLM | `30_brief_state.raw.json` | `PlannerResult` |
| 31 | `31_refiner` | planner brief + runtime | `31_brief_state.refined.json` | refined `BriefState` |
| 40 | `40_brain::<pack>` | brief + bundle + LLM | `40_brain_outputs/<pack>.json` | typed brain scope state |
| 50 | `50_validator::<pack>` | brain state | `50_validations/<pack>.json` | `ValidationReport` |
| 60 | `60_calibrator::<pack>` | brain + validation | `60_calibrations/<pack>.json` | `CalibratorReport` |
| 70 | `70_review_queue::<pack>` | calibrator items | `70_review_queue/*.jsonl` | review queue items |
| 80 | `80_composer` | brief + brain states | `80_composed_brief.json`, `81_composed_brief.md` | `ComposedBrief` |
| 90 | `90_inspection` | all of the above | `90_inspection_report.json`, **`91_inspection_report.html`** | inspection report |

Stages 30–80 are **skipped** when no LLM is wired (substrate-only mode). Stage 90 still runs and produces the dashboard.

### 2.2 The 29 domain packs

`world_model/data/domain_packs.yaml`. Pack ids and display names (full list):

```text
alm                            → ALM
audit                          → Audit
commercial                     → Commercial
data_migration                 → Data Migration
datacenter                     → Datacenter
delivery_execution             → Delivery / Execution
hardware                       → Hardware
imac                           → IMAC
itad                           → ITAD
low_voltage_cabling            → Low Voltage Cabling
msp                            → MSP
other                          → Other / Adjacent
professional_services          → Professional Services
rack_and_stack                 → Rack & Stack
security_access                → Security / Access
site_structure                 → Site Structure
staff_augmentation             → Staff Augmentation
telecom                        → Telecom
wireless                       → Wireless                       (anchor-gated)
security_camera                → Security Camera and VMS
paging_mass_notification       → Paging and Mass Notification
fire_safety                    → Fire Safety and Alarm
das                            → Distributed Antenna System
electrical                     → Electrical and Power
audio_visual                   → Audio Visual                   (anchor-gated)
building_management_systems    → Building Management Systems
network_maintenance            → Network Maintenance / Operations
camera_vms_operations          → Camera / VMS Operations
procurement_finance            → Procurement and Finance
```

**Anchor-gated packs** (`required_anchor_regex_any` set): `wireless` requires ≥ 2 distinct AP/WLAN tokens; `audio_visual` requires ≥ 3 distinct AV-equipment tokens. Without these, the pack scores but does NOT receive a brain (prevents wireless/AV brains from firing on cabling-only cases).

### 2.3 Brains registered (`orchestrator/brain_registry.py`)

Eleven brains today (each is a Phase-5 typed scope composer that consumes its retrieval bundle):

```text
msp                          → ManagedServicesBrain
wireless                     → WirelessBrain
low_voltage_cabling          → LowVoltageCablingBrain
rack_and_stack               → RackAndStackBrain
datacenter                   → DatacenterBrain
imac                         → ImacBrain
audio_visual                 → AudioVisualBrain
building_management_systems  → BuildingManagementSystemsBrain
network_maintenance          → NetworkMaintenanceBrain
camera_vms_operations        → CameraVmsOperationsBrain
procurement_finance          → ProcurementFinanceBrain
```

`BRIEFING_PACK_IDS` (frozenset) = the brains that emit a "briefing"-shaped JSON.

### 2.4 SOW completeness validator

`validator/data/sow_completeness_rules.yaml`:
- 6 global checks (customer identity, schedule, commercial structure, exclusions, assumptions, site reality present)
- 168 domain-specific checks across 29 domains
- Notable per-domain counts: `low_voltage_cabling: 21`, `msp: 19`, `wireless: 16`, `network_maintenance: 10`, `security_camera: 10`, `site_structure: 8`, `audio_visual: 5`

Every check has an `id`, severity (`blocker` / `warning` / `info`), `label`, `message`, and a customer-facing `suggested_open_question`. Those become the rows in `PM_QUESTION_QUEUE.csv`.

---

## 3. The 8 files every run writes per case

After every `compile_brief.py` invocation, the case `out_dir` looks like this:

```text
<out_dir>/
├── 00_envelope.json                  # the parser-os envelope (input to Core)
├── 10_pack_prior_state.json          # which workstreams matched
├── 11_site_reality_state.json        # publishable site clusters (with kind + member atoms)
├── 20_retrieval_bundles/<pack>.json  # per-pack evidence bundles for brains
├── 30_brief_state.raw.json           # planner output
├── 31_brief_state.refined.json       # refined brief
├── 40_brain_outputs/<pack>.json      # per-brain typed scope state
├── 50_validations/<pack>.json        # validator output
├── 60_calibrations/<pack>.json       # calibrator verdict
├── 70_review_queue/*.jsonl           # items needing human review
├── 80_composed_brief.json            # final composed brief (engineering)
├── 81_composed_brief.md              # final composed brief (markdown)
├── 90_inspection_report.json         # full lineage payload
├── 91_inspection_report.html         # ★ AUTO-OPENED DASHBOARD (PM section + engineering audit)
├── PM_EXECUTIVE_SUMMARY.md           # ★ PM landing page (markdown)
├── PM_EXECUTIVE_SUMMARY.html         # ★ PM landing page (html)
├── SA_REVIEW_PACKET.md               # ★ Solution Architect packet (markdown)
├── SA_REVIEW_PACKET.html             # ★ Solution Architect packet (html)
├── PM_HANDOFF.md                     # ★ Combined PM+SA view (markdown)
├── PM_HANDOFF.html                   # ★ Combined PM+SA view (html)
├── PM_HANDOFF.json                   # ★ ★ ★ THE ONE YOU RENDER IN UI
├── manifest.json                     # run manifest (timings, active packs)
└── pipeline_log.json                 # per-stage StageRecord history
```

After every **corpus** run (`run_core_substrate_corpus.py` driving multiple cases), the output dir additionally gets:

```text
<corpus_out>/
├── _substrate_summary.json
├── PM_PORTFOLIO_DASHBOARD.md
├── PM_PORTFOLIO_DASHBOARD.html
├── PM_PORTFOLIO_DASHBOARD.json       # all cases at a glance (UI grid)
└── PM_QUESTION_QUEUE.csv             # every blocker + warning across cases
```

The PM and portfolio artifacts are **emitted automatically** by the pipeline / corpus driver. You never run a separate render step.

---

## 4. PM_HANDOFF.json — the contract you render

This is `PMHandoff.to_dict()` (`src/orbitbrief_core/pm_handoff/models.py`). Schema:

```jsonc
{
  "case_id": "COPPER_001_SPRING_LAKE_AUDITORIUM",
  "status":  "red",                          // "red" | "yellow" | "green"
  "status_label": "Not SOW-ready: 2 blocker question(s) remain",
  "one_line_summary": "COPPER_001…: Structured cabling, MSP at Spring Lake High School - Auditorium Wing; 2 blocker / 14 warning SOW questions need PM/SA review.",

  "metrics": {
    "source_files_read":          9,
    "evidence_items_extracted":   2816,
    "pm_visible_evidence_cards":  120,
    "confirmed_physical_sites":   1,
    "sow_blocker_questions":      2,
    "sow_warning_questions":      14,
    "top_workstream":             "Managed services / NOC / SOC"
  },

  "domains": [
    {
      "domain_id":          "low_voltage_cabling",
      "label":              "Structured cabling",
      "selected_by_router": true,
      "active_for_sow":     true,
      "blockers": 1, "warnings": 6, "info": 0
    }
    /* … one per detected workstream … */
  ],

  "sites": [
    {
      "name":                  "Spring Lake High School - Auditorium Wing",
      "kind":                  "physical_site",     // physical_site | building | address | room_or_closet | unknown
      "publishable":           true,
      "member_evidence_count": 1022,
      "artifact_count":        5
    }
  ],

  "gaps": [
    {
      "rule_id":                  "low_voltage_cabling.termination_scheme_missing",
      "domain_id":                "low_voltage_cabling",
      "domain_label":             "Structured cabling",
      "label":                    "Termination scheme (T568A vs T568B)",
      "severity":                 "blocker",        // blocker | warning | info
      "message":                  "Cabling scope does not specify T568A vs T568B…",
      "suggested_open_question":  "Will jacks be terminated to T568A or T568B, and is one scheme used uniformly site-wide?",
      "observed_summary":         "no matching evidence found, 1 confirmed site(s)"
    }
    /* … */
  ],

  "facts_by_category": {
    "Sites & access":          [ /* EvidenceCard[] */ ],
    "Scope & deliverables":    [ ],
    "Asset inventory":         [ ],
    "Port & VLAN":             [ ],
    "Managed-services ops":    [ ],
    "BOM & procurement":       [ ],
    "Risks":                   [ ],
    "Cutover & validation":    [ ],
    "Source inventory":        [ ]
  },

  "source_files": [
    {
      "filename":        "site_list.csv",
      "artifact_type":   "csv",
      "parser_name":     "xlsx",
      "evidence_items":  3
    }
    /* … */
  ],

  "sa_focus": [
    "Cabling: confirm pathway clearance, firestop, labeling format",
    "MSP: confirm SLA credits, on-call rotation",
    /* … */
  ],

  "customer_questions": [ /* same shape as gaps[], filtered to severity in {blocker, warning} */ ]
}
```

Each `EvidenceCard` inside `facts_by_category` has shape:

```jsonc
{
  "title":      "Spring Lake High School - Auditorium Wing",
  "category":   "Sites & access",
  "text":       "Site ID: S01 | Site: Spring Lake High School - Auditorium Wing | Address: 16140 148th Ave, …",
  "source":     { "filename": "site_list.csv", "locator": {"sheet": "csv", "row": 2} },
  "confidence": 0.94,
  "verified":   "verified",
  "internal_id": "atm_abc123…"     // for deep-link to lineage
}
```

**This is everything the PM landing page needs.** No need to read the engineering JSONs unless you're building the audit drilldown.

---

## 5. PM_PORTFOLIO_DASHBOARD.json — the cross-case payload

`tools/build_pm_handoff.py --cases-root <dir>` (or the corpus driver) writes this. Shape:

```jsonc
[
  { /* PMHandoff.to_dict() for case 1 */ },
  { /* PMHandoff.to_dict() for case 2 */ },
  /* … one per case … */
]
```

Render it as a portfolio table:

```text
┌────────────────────────────────────────────┬────────┬───────┬────────────┬──────────┬──────────┐
│ Case                                       │ Status │ Sites │ Workstrms  │ Blockers │ Warnings │
├────────────────────────────────────────────┼────────┼───────┼────────────┼──────────┼──────────┤
│ COPPER_001_SPRING_LAKE_AUDITORIUM          │ 🔴     │   1   │ MSP, Cabl..│    2     │    14    │
│ COPPER_002_WORCESTER_DURKIN_NETWORK_UPGR.. │ 🔴     │   1   │ Wireless,..│    5     │    19    │
│ …                                          │        │       │            │          │          │
└────────────────────────────────────────────┴────────┴───────┴────────────┴──────────┴──────────┘
```

Companion: **`PM_QUESTION_QUEUE.csv`** — one row per blocker/warning across cases. Columns:

```text
case_id, case_status, severity, domain, rule_id, label, customer_question,
owner, due_date, customer_answer, pm_notes, resolved, false_positive, rule_upgrade_requested
```

This is your PM question-tracking export. Drop it straight into a Postgres table and assign owners.

---

## 6. 91_inspection_report.html — the auditable engineering dashboard

Auto-emitted on every `compile_brief.py` run. Self-contained single-page HTML, no JS deps. Section order (top to bottom):

1. **PM final layer — what the PM sees first** ← banner with status, scorecard, sites, workstreams, must-resolve blocker questions, links to the standalone PM_*/SA_* artifacts.
2. **Pipeline funnel** — sources → atoms → packets → bundle → brain → brief, with per-pack splits.
3. **Pack prior — domain routing** — top-N domain scores + matched keywords.
4. **Site reality — physical-site clustering** — confirmed clusters with kind + publishable + member atoms.
5. **Source artifacts — raw vs extracted** — for each parsed file: raw content on the LEFT, parser-os atoms on the RIGHT, decorated with downstream survival flags.
6. **GNN graph — entities + edges** — entity normalization across artifacts; same_as / supports / contradicts / etc.
7. **Packet ledger — survival through the pipeline** — every certified packet with citations and survival path.
8. **Brain outputs** — per-domain emitted items with verdict.
9. **Composed brief summary** — what landed in the final document.
10. **Review queue** — items needing human review.
11. **Pipeline log** — per-stage timing + status.

This is the page you open to **prove what the parser saw vs what the customer file said**. Every PM question links here for evidence.

---

## 7. Operator commands — how runs are triggered

### Single case (raw → all 8+ artifacts)

```bash
export PARSER_OS_ROOT=/path/to/parser-os-repo
PYTHONPATH=src python3 compile_brief.py <case_dir> --out <out_dir> \
  --ollama --ollama-base-url http://gpu-host:11434 --chat-model qwen3:14b
```

Without `--ollama`: substrate-only mode (no brains). Stages 30–80 skip; you still get pack prior, site reality, validator findings, PM handoff.

### Single case from pre-built envelope

```bash
PYTHONPATH=src python3 compile_brief.py /path/to/orbitbrief.input.json --out <out_dir>
```

### Full corpus

```bash
# Parser-os pass
python3 tools/run_corpus_with_timeout.py \
  --raw-cases <raw_root> --out-dir <envelopes_root> \
  --parser-os /path/to/parser-os-repo --per-case-timeout 600 --clean

# Core substrate pass (auto-emits PM_PORTFOLIO_DASHBOARD + PM_QUESTION_QUEUE)
python3 tools/run_core_substrate_corpus.py \
  --envelopes-root <envelopes_root> --out-dir <corpus_out> --clean
```

### Health checks

```bash
python3 -m pytest tests/pm_handoff -q          # PM layer (1 test)
python3 -m pytest tests/world_model -q         # Core world model (75 tests)
python3 tools/orbitbrief_regression_gate.py …  # CI gate against contract YAML
```

---

## 8. Wiring through the Purpulse Azure Function App

Background: `PURPULSE_AZURE_ARCHITECTURE.md` is the canonical infra map. Key facts:
- **One Function App** (`Platform-infra/azure-function-api/`) hosts all PM HTTP traffic via the `proxy` trigger.
- **External URL shape** is `https://<app>.azurewebsites.net/api/proxy/api/<rest-of-path>` (yes, two `/api` segments — intentional).
- **`proxy/index.js`** dispatches in this exact order: deploy-health → auth → technician → entra-invite → **deal artifacts** → PM HubSpot data → **DealKit v3** → **quoting overview** → fallback to `dist/vite.azure-api-plugin.cjs`.
- **Files** live in Blob container **`orbitbrief-artifacts`** by default, path `deals/{dealId}/artifacts/{sha256}/{filename}`.

### 8.1 Recommended endpoints to add to the Function App

These don't exist yet but will live alongside `pm-quoting-overview-routes.js`. Suggested route module: `pm-orbitbrief-routes.js`.

| Method | Path (after `/api/proxy`) | What it does |
|---|---|---|
| `POST` | `/api/quoting/deal/:dealId/orbitbrief/runs` | Trigger a new OrbitBrief run for the deal. Body: `{ "files": [{blobPath, sha256}] }` (optional — defaults to all current deal artifacts). Returns `{ runId, status: "queued" }`. |
| `GET` | `/api/quoting/deal/:dealId/orbitbrief/runs` | List runs for the deal. Each item `{ runId, startedAt, finishedAt, status, pmStatus }`. |
| `GET` | `/api/quoting/deal/:dealId/orbitbrief/runs/:runId` | Run detail = `PM_HANDOFF.json` payload. |
| `GET` | `/api/quoting/deal/:dealId/orbitbrief/runs/:runId/inspection.html` | Streams `91_inspection_report.html`. |
| `GET` | `/api/quoting/deal/:dealId/orbitbrief/runs/:runId/questions.csv` | Streams `PM_QUESTION_QUEUE.csv` filtered to this case. |
| `GET` | `/api/quoting/deal/:dealId/orbitbrief/portfolio` | Aggregated `PM_PORTFOLIO_DASHBOARD.json` filtered to the org. |
| `POST` | `/api/quoting/deal/:dealId/orbitbrief/runs/:runId/feedback` | PM feedback event (see §11). |

### 8.2 Storage layout (Blob)

```text
orbitbrief-artifacts/                                  # default container
├── deals/{dealId}/artifacts-staged/{requestId}/…      # raw uploads (existing)
├── deals/{dealId}/artifacts/{sha256}/…                # final raw files (existing)
└── deals/{dealId}/orbitbrief/{runId}/                 # NEW: per-run output
    ├── envelope.json                                  # 00_envelope.json
    ├── pm_handoff.json                                # for fast UI fetch
    ├── pm_executive_summary.html
    ├── sa_review_packet.html
    ├── pm_handoff.html
    ├── inspection_report.html                         # the dashboard
    └── questions.csv
```

The Postgres `quote_v3.source` field can be set to `"orbitbrief"` when a quote is hydrated from a run. `quote_v3.run_id` (new column) points back to the Blob path.

### 8.3 Capability enforcement

Add to `Platform-infra/azure-function-api/shared/route-capabilities.js`:

```js
"POST /api/quoting/deal/:dealId/orbitbrief/runs":         "pm.orbitbrief.run",
"GET  /api/quoting/deal/:dealId/orbitbrief/runs":         "pm.orbitbrief.read",
"GET  /api/quoting/deal/:dealId/orbitbrief/runs/:runId":  "pm.orbitbrief.read",
"POST /api/quoting/deal/:dealId/orbitbrief/runs/:runId/feedback": "pm.orbitbrief.feedback",
```

Map those capabilities to the appropriate Entra group.

---

## 9. SSH to Mac (Qwen models) from Azure — production transport

**The constraint:** the Qwen 14B / 32B models run on your Mac via Ollama. Azure does NOT have direct LAN access to your Mac. You need a stable tunnel.

### 9.1 The recommended pattern

```text
┌────────────────────────┐         ┌──────────────────────────┐         ┌─────────────────────┐
│ Azure Function App     │  HTTPS  │ Bastion / jump host      │   SSH   │   Mac (GPU host)    │
│ pm-orbitbrief-routes   │────────►│ (small Linux VM in Azure │────────►│   Ollama @ :11434   │
│  (Node.js worker calls │         │  with public IP, fixed)  │ tunnel  │   compile_brief.py  │
│   the Mac via tunnel)  │         │                          │         │   inside this repo  │
└────────────────────────┘         └──────────────────────────┘         └─────────────────────┘
```

The Mac dials OUT to the Bastion (no inbound NAT issues), holding open a reverse tunnel that exposes Ollama + a tiny HTTP runner on the Bastion's loopback. The Function App dials INTO the Bastion over HTTPS via a public DNS name; the Bastion forwards into the tunnel.

### 9.2 Mac side — autossh reverse tunnel

```bash
# /Library/LaunchAgents/com.purtera.ollama-tunnel.plist (LaunchAgent so it survives reboots)
# Or use brew services with autossh:
brew install autossh

autossh -M 0 -N \
  -o "ServerAliveInterval 30" \
  -o "ServerAliveCountMax 3" \
  -o "ExitOnForwardFailure yes" \
  -i ~/.ssh/orbitbrief-bastion \
  -R 11434:127.0.0.1:11434 \              # Ollama API → bastion:11434 (loopback)
  -R 9090:127.0.0.1:9090 \                # Compile runner → bastion:9090 (loopback)
  orbitbrief@bastion.example.azure.com
```

Key facts:
- `-R 11434:127.0.0.1:11434` means "anything that connects to the Bastion's `127.0.0.1:11434` ends up on the Mac's `127.0.0.1:11434`".
- `127.0.0.1` (not `0.0.0.0`) on the Bastion is intentional — only services running ON the Bastion can hit the Mac. Function App workers running ON the Bastion do; the public internet does not.
- `autossh` reconnects on network drops.

### 9.3 Bastion side — tiny Node service for the Function App to call

The Function App posts a "compile this case" request to the Bastion, the Bastion forwards to Ollama (port 11434) and to the compile runner (port 9090) via the loopback tunnel.

```js
// /opt/orbitbrief-bastion/server.js
import http from "http";
import { spawn } from "child_process";

http.createServer(async (req, res) => {
  if (req.url === "/health") {
    return fetch("http://127.0.0.1:11434/api/tags")
      .then(r => res.writeHead(200).end(JSON.stringify({ ollama: r.ok })))
      .catch(() => res.writeHead(503).end());
  }
  if (req.url === "/run" && req.method === "POST") {
    let body = ""; req.on("data", c => body += c);
    req.on("end", () => {
      const { envelopeUrl, dealId, runId } = JSON.parse(body);
      // Spawn into the tunnel: 127.0.0.1:9090 is the Mac's compile runner
      const proc = spawn("curl", ["-fsSL", "-X", "POST",
        "-H", "Content-Type: application/json",
        "-d", JSON.stringify({ envelopeUrl, dealId, runId }),
        "http://127.0.0.1:9090/run"]);
      proc.on("close", code => res.writeHead(code === 0 ? 202 : 502).end());
    });
  }
}).listen(8080, "0.0.0.0");
```

In front of this: nginx with a Let's Encrypt cert + IP allowlist for the Function App outbound IPs (or use Azure Private Link).

### 9.4 Mac side — tiny Python runner that drives `compile_brief.py`

```python
# ~/orbitbrief-runner/runner.py  (run this with `uvicorn runner:app --port 9090`)
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
import subprocess, urllib.request, tempfile, json
from pathlib import Path

app = FastAPI()

class RunRequest(BaseModel):
    envelopeUrl: str
    dealId: str
    runId: str

def _run(envelopeUrl: str, dealId: str, runId: str):
    out = Path(f"/Users/orbitbrief/runs/{dealId}/{runId}")
    out.mkdir(parents=True, exist_ok=True)
    env_path = out / "envelope.json"
    urllib.request.urlretrieve(envelopeUrl, env_path)   # Blob SAS URL
    subprocess.run([
        "python3", "/Users/orbitbrief/Orbitbrief-Core/compile_brief.py",
        str(env_path), "--out", str(out),
        "--ollama", "--ollama-base-url", "http://127.0.0.1:11434",
        "--chat-model", "qwen3:14b",
        "--escalated-model", "qwen3:32b",
        "--quiet", "--quiet-parser",
    ], check=True, env={"PARSER_OS_ROOT": "/Users/orbitbrief/parser-os-repo", **__import__("os").environ})
    # Upload outputs back to Blob (or push to bastion which does it)
    # … blob-upload code here, using a pre-signed write SAS …

@app.post("/run")
def run(req: RunRequest, bg: BackgroundTasks):
    bg.add_task(_run, req.envelopeUrl, req.dealId, req.runId)
    return {"status": "started", "runId": req.runId}
```

### 9.5 Function App side — call the bastion

```js
// Platform-infra/azure-function-api/shared/orbitbrief-runner-client.js
const BASTION_URL = process.env.ORBITBRIEF_BASTION_URL;   // https://bastion.example.com
const BASTION_TOKEN = process.env.ORBITBRIEF_BASTION_TOKEN;

async function triggerOrbitBriefRun({ envelopeUrl, dealId, runId }) {
  const res = await fetch(`${BASTION_URL}/run`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "authorization": `Bearer ${BASTION_TOKEN}`,
    },
    body: JSON.stringify({ envelopeUrl, dealId, runId }),
  });
  if (!res.ok) throw new Error(`bastion ${res.status}`);
}

module.exports = { triggerOrbitBriefRun };
```

### 9.6 Why not call Ollama directly from Azure?

You could (`http://bastion:11434`) but then the Function App handles the long Ollama calls itself (stage 30–60 take 30–120s per pack on Qwen 32B). The Function App has request-time limits and consumption-plan timeouts. Putting the runner ON the Mac means Azure just **kicks off** the run and polls for the artifact in Blob — no long-lived HTTP connections from Azure to your Mac.

### 9.7 Local dev shortcut (no bastion)

When developing the Function App + SPA locally, point `ORBITBRIEF_BASTION_URL` at `http://localhost:9090` (the Mac runner directly), or just call `compile_brief.py` from a Vite dev plugin. Production-only path is the bastion.

---

## 10. Local dev — the fastest possible loop

```bash
# Terminal 1 — Mac, Ollama already running (`ollama serve`)
cd /path/to/Orbitbrief-Core
export PARSER_OS_ROOT=/path/to/parser-os-repo

# Run a single case end-to-end (substrate only, ~15s per case)
PYTHONPATH=src python3 compile_brief.py \
  /path/to/raw_case_dir/ \
  --out /tmp/dev_run/

# Open the dashboard
open /tmp/dev_run/91_inspection_report.html

# Or the PM-only landing page
open /tmp/dev_run/PM_EXECUTIVE_SUMMARY.html
```

For a full corpus + portfolio in one shot:

```bash
# (parser-os pass)
python3 tools/run_corpus_with_timeout.py \
  --raw-cases /path/to/all_cases \
  --out-dir /tmp/envelopes \
  --parser-os $PARSER_OS_ROOT --clean

# (Core substrate + auto portfolio + auto question CSV)
python3 tools/run_core_substrate_corpus.py \
  --envelopes-root /tmp/envelopes \
  --out-dir /tmp/corpus_out --clean

open /tmp/corpus_out/PM_PORTFOLIO_DASHBOARD.html
```

### 10.1 Frontend dev — fetching PM_HANDOFF.json

In Vite dev with the existing `/api/quoting` proxy:

```ts
async function fetchPmHandoff(dealId: string, runId: string): Promise<PMHandoff> {
  const url = `/api/quoting/deal/${dealId}/orbitbrief/runs/${runId}`;
  const r = await fetch(url, { headers: { accept: "application/json" } });
  if (!r.ok) throw new Error(`handoff ${r.status}`);
  return r.json();
}
```

Type stubs you can paste straight in:

```ts
export type PmStatus = "red" | "yellow" | "green";
export type GapSeverity = "blocker" | "warning" | "info";
export type SiteKind = "physical_site" | "building" | "address" | "room_or_closet" | "unknown";
export type VerifiedState = "verified" | "partial" | "unverified" | "failed" | "unsupported";

export interface PMHandoff {
  case_id: string;
  status: PmStatus;
  status_label: string;
  one_line_summary: string;
  metrics: {
    source_files_read: number;
    evidence_items_extracted: number;
    pm_visible_evidence_cards: number;
    confirmed_physical_sites: number;
    sow_blocker_questions: number;
    sow_warning_questions: number;
    top_workstream: string;
  };
  domains: {
    domain_id: string;
    label: string;
    selected_by_router: boolean;
    active_for_sow: boolean;
    blockers: number;
    warnings: number;
    info: number;
  }[];
  sites: {
    name: string;
    kind: SiteKind;
    publishable: boolean;
    member_evidence_count: number;
    artifact_count: number;
  }[];
  gaps: GapCard[];
  facts_by_category: Record<string, EvidenceCard[]>;
  source_files: {
    filename: string;
    artifact_type: string;
    parser_name: string;
    evidence_items: number;
  }[];
  sa_focus: string[];
  customer_questions: GapCard[];      // subset of gaps[] with severity in {blocker, warning}
}

export interface GapCard {
  rule_id: string;
  domain_id: string;
  domain_label: string;
  label: string;
  severity: GapSeverity;
  message: string;
  suggested_open_question: string;
  observed_summary: string;
}

export interface EvidenceCard {
  title: string;
  category: string;
  text: string;
  source: { filename: string; locator: Record<string, unknown> };
  confidence: number | null;
  verified: VerifiedState;
  internal_id: string;
}
```

---

## 11. Capabilities matrix — what to surface in UI

Mapping of OrbitBrief outputs → suggested UI surface:

| Source | UI surface | Notes |
|---|---|---|
| `PM_HANDOFF.json` → `status`, `status_label` | Big colored banner on the deal page | 🔴/🟡/🟢 with one-line summary |
| `PM_HANDOFF.json` → `metrics` | Scorecard tiles | 6 numbers: files / evidence / sites / blockers / warnings / top workstream |
| `PM_HANDOFF.json` → `sites` | "Confirmed sites" panel | One row per cluster, with kind + evidence count |
| `PM_HANDOFF.json` → `domains` | "Detected workstreams" table | Routed? + SOW-active? + blockers/warnings |
| `PM_HANDOFF.json` → `gaps` (severity=blocker) | "Must resolve before SOW" red panel | Each row → "Send to customer" / "Assign to SA" / "Mark answered" buttons |
| `PM_HANDOFF.json` → `gaps` (severity=warning) | "Open clarifications" yellow panel | Same actions |
| `PM_HANDOFF.json` → `facts_by_category` | "Evidence" drawer (right rail) | Tabbed by category with source citation |
| `PM_HANDOFF.json` → `sa_focus` | SA-only sub-tab | Hidden behind a role flag |
| `91_inspection_report.html` | "Open audit dashboard" external link | Iframe or new tab |
| `PM_QUESTION_QUEUE.csv` | "Export questions" button | Download or paste into HubSpot |
| `PM_PORTFOLIO_DASHBOARD.json` | Org-level PM landing page | Pipeline view across all open deals |

### 11.1 PM action buttons → feedback events

Every PM click should write a feedback event back to Postgres:

```jsonc
// POST /api/quoting/deal/:dealId/orbitbrief/runs/:runId/feedback
{
  "case_id":     "COPPER_001_SPRING_LAKE_AUDITORIUM",
  "item_type":   "sow_gap",
  "rule_id":     "low_voltage_cabling.termination_scheme_missing",
  "decision":    "ask_customer",        // ask_customer | assign_sa | mark_answered |
                                        // false_positive | already_in_source | add_new_rule | ignore_for_project
  "assigned_to": "solution_architect",
  "comment":     "District standard appears to be T568B; confirming with facilities."
}
```

Suggested table:

```sql
CREATE TABLE pm_feedback_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  deal_id UUID NOT NULL,
  run_id  UUID NOT NULL,
  case_id TEXT NOT NULL,
  item_type TEXT NOT NULL,
  rule_id TEXT,
  decision TEXT NOT NULL,
  assigned_to TEXT,
  user_email TEXT,
  comment TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
```

When `decision IN ('false_positive', 'add_new_rule', 'already_in_source')`, push a row into `rulebook_review_queue` so the engineering team can absorb the feedback into `sow_completeness_rules.yaml`.

---

## 12. Answers to the master-plan open questions

Lifted directly from `QUOTING_PARSER_ORBITBRIEF_MASTER_PLAN.md` §9:

> **1. Should OrbitBrief runs be synchronous or async? Max runtime per deal?**

**Async.** Substrate-only (no LLM) is ~10–15 s per case; full LLM runs are 1–8 min on Qwen 14B and 5–30 min on Qwen 32B depending on case size. UI flow: PM clicks "Run OrbitBrief" → Function App returns `{ runId, status: "queued" }` immediately → SPA polls `GET …/runs/:runId` (or subscribes via SignalR if you wire it) → renders `PM_HANDOFF.json` when status is `done`. Hard cap: **15 minutes per case**; longer = cancel and notify.

> **2. Who is allowed to trigger parser-os / OrbitBrief?**

Add capability `pm.orbitbrief.run` to `route-capabilities.js`. Map it to the same Entra group as `pm.quote.write`. SAs and PMs only; viewers see results but can't trigger.

> **3. Target Azure runtime for parser-os?**

**Container Apps job** (or self-hosted GitHub Actions runner). Reasons: parser-os needs Python + native dependencies (PyMuPDF, openpyxl) + decent CPU + temp disk for big PDFs. Function App consumption plan won't reliably finish a 70-page rack-elevation PDF inside the request window. Container Apps gives per-job billing + no cold start penalty if you keep min replicas at 0 with prewarm.

> **4. Envelope retention?**

- Encryption at rest on Blob (default with Azure Storage).
- TTL: keep envelopes 90 days in `orbitbrief-artifacts` for audit; archive to Blob `Cool` tier after 30, delete at 90 unless `quote_v3.archived_at` is set.
- **Production envelopes can live on the GPU Mac temporarily** (≤ 24h) for diagnosis but should never be the only copy.

> **5. test slot — quoting integration tests against test DB + scrubbed fixtures?**

Yes. `tests/managed_services_sow_artifact_pack/COPPER_00*` are intentionally synthetic and PII-free; ship them as the test-slot fixture set. Run nightly via the existing release workflow, fail the gate on any new RED case that wasn't RED yesterday.

---

## 13. Glossary

| Term | Definition |
|---|---|
| **atom** | Smallest typed unit of evidence emitted by parser-os (one cell, one bullet, one PDF row). PMs never see this word in their UI. |
| **packet** | A certified group of atoms (e.g. a `scope_exclusion` packet groups all the atoms that prove an exclusion). PMs never see this word either. |
| **pack** | A workstream (cabling, MSP, wireless, etc.). 29 packs total; 11 have brains. |
| **brain** | A Phase-5 LLM composer that turns one pack's evidence into a typed scope state. |
| **packet** vs **packet (the boss-bundle one)** | Don't confuse. The PM-facing "packet" is `SA_REVIEW_PACKET.html` (a document). The internal "packet" is the engineering grouping. |
| **brief** | The composed final scope document (`81_composed_brief.md`). |
| **envelope** | The parser-os → Core seam JSON (`orbitbrief.input.v2`). |
| **publishable site** | A site cluster with `kind=physical_site` (or building/address) and member atoms. The PM UI only shows publishable sites. |
| **PM handoff** | The whole package of PM-facing artifacts emitted at the end of a run. The contract you render is `PM_HANDOFF.json`. |
| **anchor gate** | The v9 rule that says a pack only gets a brain if the corpus has N distinct equipment-specific tokens. Prevents wireless/AV brains from firing on cabling-only cases. |
| **SOW gap / SOW question** | A blocker/warning produced by the SOW completeness validator. PMs send these to customers. |
| **bastion** | The small Linux VM in Azure that holds the SSH reverse tunnel from the Mac so the Function App can reach Ollama. |

---

## 14. Azure footguns — what your cloud + frontend engineer must know

> **TL;DR:** the Azure layer cannot touch OrbitBrief's actual output quality (all extraction / synthesis runs on the Mac). But it can absolutely degrade *user experience* if you don't respect the constraints below.

### 14.1 What Azure cannot break

The atom extraction, packet certification, site reality clustering, SOW validation, brain composition, and PM handoff rendering all execute on the Mac. Azure is just **transport** (Function App routes), **storage** (Blob), and **identity** (Entra). The `PM_HANDOFF.json` that lands in Blob is byte-identical to the one written on disk on the Mac.

### 14.2 What Azure WILL break if you let it

| Risk | Why it matters | The non-negotiable rule |
|---|---|---|
| **Function App 230s HTTP timeout** | Substrate-only runs are 10–15s but full LLM runs are 5–30 min. A synchronous call dies mid-brain → partial output. | The async pattern in §9 is mandatory. SPA polls. Function App just kicks off + serves Blob. |
| **`dist/vite.azure-api-plugin.cjs` fallback** (`PURPULSE_AZURE_ARCHITECTURE.md` §3.2) | Routes can silently land in the bundled fallback instead of the native handler. Pure footgun for the engineer maintaining the proxy. | Doesn't touch OrbitBrief output quality. Just document which route lives where; grep `purpulse-frontend` builds before claiming "handler missing." |
| **Two `/api` segments in URLs** | `/api/proxy/api/data/...` looks wrong; people "fix" it and break the SPA. | Already documented in `PURPULSE_AZURE_ARCHITECTURE.md` §2 — leave it. |
| **autossh tunnel drops** | Mac becomes unreachable, Function App queues back up. Pure availability issue. | LaunchAgent that auto-restarts autossh on `ServerAliveCountMax 3`. SPA renders an "OrbitBrief is degraded" health banner from `GET /health` on the bastion. |
| **Cold starts on consumption plan** | First request after 20 min idle takes 5–30s. PM thinks it hung. | Either (a) timer trigger that hits `/api/proxy/api/deploy-health` every 5 min, (b) move to App Service Plan (~$50/mo), or (c) live with it on pilot. |
| **Container Apps job for parser-os** | If you put parser-os inside the Function App, big PDFs (70-page rack drawings) blow the request window. | Use Container Apps jobs (or self-hosted GHA runner). Function App must never run parser-os in-process. |
| **Blob write race** | If the Mac runner crashes mid-upload, Blob has a partial run. UI shows half a dashboard. | Atomic uploads: write to `…runs/{runId}.tmp/`, then `mv` to `…runs/{runId}/`. Status flips to `done` only after the rename. |
| **`/api/proxy/api/...` double prefix** | The proxy strips a leading `/api/proxy` and rewrites `/data/...` → `/api/data/...` (`PURPULSE_AZURE_ARCHITECTURE.md` §3.1). | Don't `URL.canonicalize` the path on the SPA — let the proxy do it. |
| **HubSpot manual-docs sync is async** (`PURPULSE_AZURE_ARCHITECTURE.md` §5.4) | If your OrbitBrief route relies on HubSpot-side documents, they may be hours behind. | Don't trigger OrbitBrief from a HubSpot push; trigger from a deal-artifact upload event. |
| **Deal Kit v3 "blob" naming collision** | "blob" in `DEALKIT_V3_STORAGE_ADR.md` means **JSON** in `opportunities.quote_data->deal_kit_v3`. **Not** Azure Blob. | Use `quote_v3.source = 'orbitbrief'` + `quote_v3.run_id` to link a hydrated quote to its OrbitBrief run; the binary outputs live in the **`orbitbrief-artifacts`** container, **not** in `opportunities.quote_data`. |

### 14.3 The actual sketchy part — the bastion

The bastion + autossh reverse tunnel from the Mac is the **weakest link** in the whole architecture. Not because it's slow — it's plenty fast — but because:

- autossh has known reconnect bugs on macOS network changes (Wi-Fi switch, sleep-wake)
- the bastion is a single point of failure (single Linux VM)
- the Mac is on a residential / office ISP with no SLA

**For pilot + first 5–10 real customer cases:** fine. Ship as-is.

**Within 6 months of paying customers**, pick one of these to retire the bastion:

1. **Tailscale** instead of autossh — same model, way better resilience. `tailscale up` on Mac, install on the bastion (or skip the bastion entirely and put Tailscale on the Function App's VNet integration target). Drops 80% of §9 complexity.
2. **Move Ollama to an Azure NC-series VM** (GPU). ~$1.20/hr for an `NC4as_T4_v3` running `qwen3:14b`; ~$3.50/hr for an `NC24ads_A100_v4` running `qwen3:32b`. Same model, same code, hosted in Azure. Drops the bastion entirely.
3. **Use a managed inference endpoint** for Qwen 32B (Azure ML serverless, Together.ai, Fireworks, etc.). Keep Mac for dev only. The `OpenAIChatClient` interface in `inference/client.py` already accepts arbitrary `base_url + api_key` — no code changes needed.

### 14.4 What "ok enough" actually means

| Phase | Verdict | Reason |
|---|---|---|
| **Demo to PM team** | Ship as-is | Nothing in Azure layer degrades what the PM sees on `PM_EXECUTIVE_SUMMARY.html` — same file your code wrote on the Mac. |
| **First 5–10 paying customers** | Ship as-is + monitor autossh | Plus a "OrbitBrief degraded" health banner so demos don't die on a tunnel reconnect. |
| **100+ concurrent runs** | Replace autossh with Tailscale **or** move models to Azure | Single-bastion architecture won't survive real concurrency. |

### 14.5 First-month gotchas (bookmark these)

These are guaranteed to happen. None affect output quality; all affect demos.

1. **autossh dies during a live PM demo.**
   - Mitigation: `caffeinate -i -d` while OrbitBrief is in active demo mode + LaunchDaemon restarts autossh on exit.
   - Backup: have a `?fallback=local` query param in the SPA that bypasses Azure and hits a local Vite dev plugin during the demo.

2. **First Function App request after lunch takes 28 seconds.**
   - Mitigation: 5-minute Azure Functions timer trigger that hits `/api/proxy/api/deploy-health`.

3. **A 70-page PDF takes 11 minutes to compile.**
   - Mitigation: SPA shows real progress (Stage 10 of 90 / Stage 40 of 90 [3/8 brains]…), not a spinner. Surface `pipeline_log.json` rows in real time via SSE or polling `GET /runs/:runId/log`.

4. **A new domain pack ships and the SPA doesn't know its display label.**
   - Mitigation: never hardcode `domain_id → display_name` in the SPA. Always render `domains[].label` from `PM_HANDOFF.json`. The Core ships the canonical label.

5. **A PM clicks "Run OrbitBrief" twice.**
   - Mitigation: idempotency key. The Function App should derive `runId` from `sha256(envelope_sha256 + chat_model + escalated_model + sow_rules_version)`. Second click returns the same `runId`. No duplicate Mac runs.

6. **The Mac runs out of disk because no one cleans `/Users/orbitbrief/runs/`.**
   - Mitigation: `find /Users/orbitbrief/runs/ -mtime +14 -delete` in a daily LaunchDaemon. Blob is the truth; the local copy is throwaway.

7. **An engineer "fixes" the double `/api/proxy/api` URL.**
   - Mitigation: `PURPULSE_AZURE_ARCHITECTURE.md` §2 already documents this. Quote it in any code review touching `purpulse-frontend/src/lib/data-backend/config.ts`.

### 14.6 What the cloud engineer ships first

Concrete checklist for the cloud engineer's first sprint:

- [ ] **Container Apps job** named `orbitbrief-parser` running parser-os against Blob `deals/{dealId}/artifacts/...`. Triggered by Service Bus message from `pm-orbitbrief-routes.js`. Writes the envelope back to `deals/{dealId}/orbitbrief/{runId}/envelope.json`.
- [ ] **Bastion VM** (`Standard_B1s`, ~$10/mo) in `eastus2` with public DNS `orbitbrief-bastion.<your-domain>`. nginx + Let's Encrypt + Function App outbound IP allowlist (or Azure Private Link if available).
- [ ] **autossh LaunchDaemon** on the Mac (§9.2). Test by `kill -9` the autossh process; it should respawn within 5s.
- [ ] **Mac runner FastAPI service** (§9.4) at `127.0.0.1:9090` with `~/Library/LaunchAgents/com.purtera.orbitbrief-runner.plist` autostart.
- [ ] **Bastion Node service** (§9.3) at `127.0.0.1:8080` with systemd unit `orbitbrief-bastion.service`. nginx reverse-proxies `https://bastion/run` → `127.0.0.1:8080/run`.
- [ ] **Function App route** `pm-orbitbrief-routes.js` registered in `proxy/index.js` AFTER `pm-deal-artifacts-routes` and BEFORE `pm-dealkit-v3-routes`.
- [ ] **App settings** added to all three slots:
  - `ORBITBRIEF_BASTION_URL=https://orbitbrief-bastion.<your-domain>`
  - `ORBITBRIEF_BASTION_TOKEN=<from-keyvault>`
  - `ORBITBRIEF_RUNNER_TIMEOUT_MS=900000` (15 min)
- [ ] **Capability mapping** in `route-capabilities.js` per §8.3.
- [ ] **Smoke test in CI**: `curl https://<function-app>.azurewebsites.net/api/proxy/api/quoting/deal/<known-fixture-deal-id>/orbitbrief/health` returns `{ "ollama": true, "runner": "up" }`.
- [ ] **Pre-warm timer trigger** that hits `/api/proxy/api/deploy-health` every 5 minutes during business hours (cron: `0 */5 13-23 * * 1-5` UTC).
- [ ] **Daily Mac cleanup LaunchDaemon** that removes runs older than 14 days from `/Users/orbitbrief/runs/`.

### 14.7 What the frontend engineer ships first

- [ ] **Type stubs** from §10.1 dropped into `purpulse-frontend/src/types/orbitbrief.ts`.
- [ ] **`useOrbitBriefRun(dealId, runId)` hook** that polls `GET /api/quoting/deal/:dealId/orbitbrief/runs/:runId` every 3s while `status !== 'done' && status !== 'failed'`.
- [ ] **`<OrbitBriefStatusBanner status status_label />`** — renders the 🔴/🟡/🟢 banner at the top of the deal page.
- [ ] **`<OrbitBriefScorecard metrics />`** — 6 tiles from §11.
- [ ] **`<OrbitBriefSites sites />`** — confirmed-sites table with kind + evidence count.
- [ ] **`<OrbitBriefWorkstreams domains />`** — routed/active table.
- [ ] **`<OrbitBriefBlockers gaps />`** — must-resolve red panel with action buttons (Send to customer / Assign to SA / Mark answered).
- [ ] **`<OrbitBriefEvidenceDrawer facts_by_category />`** — right-rail tabbed by category with source citation.
- [ ] **`<OrbitBriefAuditLink runId />`** — opens `91_inspection_report.html` in a new tab via `GET /api/quoting/deal/:dealId/orbitbrief/runs/:runId/inspection.html`.
- [ ] **`POST /feedback`** plumbing for every action button per §11.1.
- [ ] **Portfolio view** (`<PMPortfolioGrid />`) consuming `GET /api/quoting/orbitbrief/portfolio` (= `PM_PORTFOLIO_DASHBOARD.json`). One row per case.
- [ ] **Question-queue export** button: `<a download href="/api/quoting/orbitbrief/questions.csv?org={orgId}">`.
- [ ] **Degraded-mode banner** that shows when `GET /api/proxy/api/quoting/orbitbrief/health` returns `{ runner: "down" }`. Tells the PM "OrbitBrief is currently unavailable; run results will be queued."

---

## Document history

- **2026-05-15** — Initial frontend-integration README; describes parser-os atom + parser inventory, Orbitbrief-Core 12 pipeline stages, the 8 per-case + 4 portfolio artifacts, `PM_HANDOFF.json` schema, suggested Function App routes, the bastion-tunnel Mac SSH transport, and answers to master-plan open questions.
- **2026-05-15 (later)** — Added §14: Azure footguns + cloud-engineer-first-sprint checklist + frontend-engineer-first-sprint checklist + first-month-gotcha list.
