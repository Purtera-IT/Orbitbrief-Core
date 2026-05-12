# ChatGPT Pro Prompt — Fill OrbitBrief domain brains to 10/10

> **Use this verbatim** as a single message to ChatGPT Pro (with at minimum
> the GPT-5/o3 reasoning model). Attach the bundled YAML
> `examples/CURRENT_briefing_configs.yaml` as a reference. Output is a
> drop-in replacement for that file.

---

## What I'm asking you to do

I'm running OrbitBrief — a system that ingests professional-services intake (RFPs, proposals, transcripts, spreadsheets) and produces a reviewable scope brief that a project manager can accept, edit, or reject. The architecture is layered, deterministic, and works end-to-end today; the **gap to 10/10** is the per-domain prompt content that drives the LLM brains.

You are going to fill in **production-grade per-domain configuration** for **5 domains** (wireless, low_voltage_cabling, rack_and_stack, datacenter, imac) so each brain produces SOW-ready scope state that a senior delivery PM at a managed-services firm would consider publishable with light review.

Output: a single YAML file matching the schema of the attached `examples/CURRENT_briefing_configs.yaml`. I drop it in at `src/orbitbrief_core/brains/data/briefing_configs.yaml` and ship.

---

## System context (so you understand what the brain *is*)

For each engagement, my pipeline runs:

1. **parser-os** ingests raw artifacts (PDFs, DOCX, XLSX, transcripts, emails) and emits a typed envelope of atoms / entities / edges / packets.
2. **pack_prior** decides which OrbitBrief domain packs are active (e.g., `wireless` + `low_voltage_cabling`).
3. **planner** (Qwen3-14B) emits a top-level `BriefState` with sites, contradictions, escalation log.
4. **brains** (one per active pack) emit a typed `BriefingState` — a 9-section domain-specific scope. **You are filling in the prompt material that drives these brains.**
5. **validator** + **calibrator** + **review queue** + **composer** + **UI** — downstream of you.

The brain inputs:
* `BriefState` — what the planner decided.
* `RetrievalBundle` — relevant packets the orchestrator pre-bundled, organized by parser-os PacketFamily (`scope_inclusion`, `scope_exclusion`, `customer_override`, `meeting_decision`, `action_item`, `site_access`, `missing_info`, `compliance_clause`, `quantity_claim`, `quantity_conflict`, `vendor_mismatch`).

The brain output (the **canonical 9 sections** — same shape across every domain):
* `scope_overview` — narrative summary
* `detailed_scope_of_services` — executable activities
* `deliverables` — customer-facing tangible outputs
* `assumptions` — atomic + testable assumptions
* `customer_responsibilities` — required customer actions
* `out_of_scope` — explicit exclusions
* `risks_or_dependencies` — risks + dependencies + unknowns
* `completion_criteria` — objective indicators of done
* `open_items` — unresolved items blocking finalization

Every item in every section is grounded — it MUST cite `supporting_packet_ids` from the retrieval bundle.

---

## What "10/10 perfection" means for these prompts

The current YAML has:
* **Wireless** — rich (135 guidance bullets + 4 normalization vocabularies including `survey_type_labels`, `delivery_model_labels`, `common_wireless_terms`). This is the gold standard for what every domain should look like.
* **The other 4** (low_voltage_cabling, rack_and_stack, datacenter, imac) — 26-28 guidance bullets each, mostly generic defaults plus a handful of domain-specific ones. **These are the ones I need you to fill in.**

For each of the **4 understocked domains**, deliver:

### A. `operating_rules` (5–8 booleans)

Per-domain operating principles that constrain LLM behavior. The wireless example:

```yaml
operating_rules:
  do_not_invent_facts: true
  use_assumptions_for_supported_gaps_only: true
  use_open_items_for_missing_or_conflicting_data: true
  remove_irrelevant_language: true
  preserve_structured_detail_over_summary: true
  keep_wording_execution_ready: true
  limit_output_to_nine_post_fields: true
```

Add domain-specific ones where they matter (e.g., for `low_voltage_cabling`: `prefer_certification_standards_over_vendor_brand_names: true`, `quantify_drops_per_room_when_possible: true`).

### B. `normalization` (controlled vocabularies + abbreviation maps)

Wireless ships:
* `survey_type_labels` — exhaustive list of accepted survey type strings
* `delivery_model_labels` — `[onsite, remote, hybrid, unspecified]`
* `common_wireless_terms` — `{AP: access point, WLAN: wireless local area network, RF: radio frequency, ...}`

For each new domain, ship the **3–6 most important** controlled vocabularies. Examples:

* **low_voltage_cabling**:
  * `cable_categories` — `[Cat5e, Cat6, Cat6a, OM3, OM4, OM5, OS2, ...]`
  * `termination_types` — `[RJ45 jack, patch panel, fiber LC, fiber SC, fiber MTP/MPO, ...]`
  * `pathway_types` — `[J-hook, conduit, cable tray, raceway, plenum, riser, ...]`
  * `certification_standards` — `[TIA-568.2-D, TIA-568.3-D, BICSI ITSIMM, ANSI/TIA-606-C labeling, ...]`
  * `common_low_voltage_terms` — `{IDF: intermediate distribution frame, MDF: main distribution frame, DMARC: demarcation point, UTP: unshielded twisted pair, STP: shielded twisted pair, MUTOA: multi-user telecommunications outlet assembly, ...}`

* **rack_and_stack**:
  * `cabinet_types`, `power_phases`, `pdu_classes`, `cable_management_styles`, `labeling_standards`
  * `common_rack_terms` — `{RU: rack unit, U: rack unit, PDU: power distribution unit, OOB: out-of-band, KVM: keyboard-video-mouse, ...}`

* **datacenter**:
  * `power_classes` — `[120V/20A, 208V/20A, 208V/30A, 480V/...]`
  * `cooling_types` — `[CRAC, in-row, rear-door heat exchanger, immersion]`
  * `tier_levels` — `[Tier I, Tier II, Tier III, Tier IV]` (Uptime Institute)
  * `decommission_states` — `[powered-off in-place, de-racked, ITAD-staged, returned-to-vendor]`
  * `common_dc_terms`

* **imac**:
  * `imac_actions` — `[install, move, add, change, refresh, swap, decommission]`
  * `device_classes` — `[laptop, desktop, monitor, dock, peripheral, smartphone, tablet]`
  * `image_template_types` — `[Autopilot, SCCM TS, Intune Win32, Jamf Composer, ...]`
  * `disposition_paths` — `[user-keep, ITAD, return-to-leasing, internal-pool]`
  * `common_imac_terms` — `{IMAC: install/move/add/change, RMA: return merchandise authorization, ...}`

### C. `fields[<section>]` — **per-section guidance bullets**

This is the deepest fill. For each of the 9 sections, deliver **6–12 bullets** that:

1. Are **action-oriented** (start with verbs: "List", "Differentiate", "Call out", "Use", "Avoid").
2. Are **domain-specific** — not generic. Bad: "List the deliverables." Good: "Differentiate as-built drawings (PDF), labeling export (CSV), test result certificates (Fluke or Versiv-format PDF), and installation photos."
3. Reference the **normalization vocabularies** from section B where relevant.
4. Anticipate the **common LLM mistakes** for that section in that domain. Examples to guard against:
   * For `out_of_scope` in `low_voltage_cabling`: "Don't list 'fiber pulls' as exclusion if they're already in scope under a different subdomain — check the BriefState first."
   * For `assumptions` in `datacenter`: "Don't assume power is available beyond what the customer stated — escalate to open_items if power class is unspecified."

Use the wireless `fields` block as the reference style. Wireless guidance for `detailed_scope_of_services` includes things like:
> * "Differentiate passive, predictive, AP on a stick, spectrum, and post-validation activities"
> * "Include planning, survey, analysis, validation, design, remediation review, and reporting tasks only if supported by source material"

That's the bar.

### D. `subdomain_notes` (4–8 short bullets)

Mirror the format already in the YAML — these come from my intake workbook's 01_INDEX sheet. Examples already shipped:

```yaml
subdomain_notes:
  - what is assumed existing vs new, test/cert expectations, by-others boundaries
  - AP drops re-use, certification, label / closet mapping
  - new AP count, pathways, ceiling/height, patch panel termination
```

Augment with domain-specific subdomain notes you think are missing. These appear as `subdomain_notes` in the prompt under `domain.subdomain_notes`.

### E. (Bonus, if you have token budget) `gold_examples`

Add a new optional top-level block per domain, **`gold_examples`**, that gives the brain 1–2 fully-worked example items per section. Format:

```yaml
gold_examples:
  scope_overview:
    - statement: "MDM rollout for ~220 corporate laptops across HQ and 3 satellite sites, onsite delivery, completed within 8-week wave plan."
      evidence_pattern: "scope_inclusion packet describing MDM tooling + quantity_claim packet with device count + meeting_decision packet with target completion"
      pitfalls: "Don't include BYOD devices unless explicitly mentioned; don't infer satellite site count from sub-RFP boilerplate."
  detailed_scope_of_services:
    - statement: "Enrollment of 220 endpoints into Microsoft Intune via Autopilot, with conditional access policies pre-staged."
      evidence_pattern: "scope_inclusion packet on Intune + customer_override on Autopilot tenant + compliance_clause on conditional access"
      pitfalls: "Avoid listing tooling-vendor activities unless the source confirms (e.g., don't presume Jamf is in scope just because it's mentioned in passing)."
  # ... per section
```

These flow into the brain prompt as `gold_examples` and act like few-shot reasoning anchors. Don't worry about implementing — I'll wire it; you just produce it.

---

## Output format requirements

Output **one single YAML file** with this exact top-level structure:

```yaml
_doc: <updated provenance line>
version: v5  # bump from v4
canonical_fields:
  - scope_overview
  - detailed_scope_of_services
  - deliverables
  - assumptions
  - customer_responsibilities
  - out_of_scope
  - risks_or_dependencies
  - completion_criteria
  - open_items
domains:
  wireless:
    display_name: Wireless
    operating_rules: { ... }      # leave existing wireless content intact, optionally enrich
    normalization: { ... }        # leave existing wireless content intact
    fields:                       # leave existing wireless content intact, optionally polish
      scope_overview: [ ... ]
      ...
    artifact_labels: [ ... ]      # keep
    schemas_extracted: 19         # keep
    subdomain_notes: [ ... ]      # keep
    gold_examples: { ... }        # NEW (your contribution if you choose to ship it)
  low_voltage_cabling:
    display_name: Low Voltage Cabling
    operating_rules: { ... }      # FILL IN
    normalization: { ... }        # FILL IN — 3-6 vocabularies
    fields:                       # FILL IN — 6-12 bullets per section
      scope_overview: [ ... ]
      detailed_scope_of_services: [ ... ]
      deliverables: [ ... ]
      assumptions: [ ... ]
      customer_responsibilities: [ ... ]
      out_of_scope: [ ... ]
      risks_or_dependencies: [ ... ]
      completion_criteria: [ ... ]
      open_items: [ ... ]
    artifact_labels: [ ... ]      # keep existing
    schemas_extracted: 28         # keep
    subdomain_notes: [ ... ]      # FILL IN — 4-8 bullets
    gold_examples: { ... }        # NEW
  rack_and_stack: { same shape }
  datacenter: { same shape }
  imac: { same shape }
```

### Hard constraints

* **Valid YAML** — quoting consistent, no tabs, ≤120-char lines preferred.
* **No empty bullets, no placeholders** — every list item must be a real, useful, actionable string.
* **No prose explanations** — pure YAML. If you must comment, use `#` line comments.
* **Don't break what's there** — wireless content is rich and battle-tested; only enrich, never strip.
* **Each guidance bullet ≤ 200 chars** — they go into a structured prompt, not a long-form doc.

---

## Calibration anchor — what "production-grade" means

Imagine the senior delivery PM at a 250-person managed-services firm reading the brain's output for a new $250k engagement. They should say:

> "This brief looks like a Senior PM with 5 years in this domain wrote it. I'd accept 80 % of it as-is, edit ~15 % for tone, and send 5 % back for clarification."

That's the bar. **Not** "this is a fine LLM-generated stub." 10/10 is **"this is exactly what a senior PM would write before any LLM existed."**

For pricing context: a hand-written SOW from a senior delivery PM at this firm would cost $2k-$5k of internal time. The brain should produce ~80 % of that quality automatically.

---

## Domain-specific anchors (read before you fill)

### low_voltage_cabling
Industry: structured cabling, fiber, IDF/MDF buildouts, ICRA work in healthcare. Standards: TIA-568, BICSI ITSIMM, ANSI/TIA-606-C labeling, NEC plenum requirements. Common deliverables: as-built drawings, label exports, certification test results (Fluke / Versiv format). Common pitfalls: existing-vs-new ambiguity, pathway availability assumptions, riser/penetration permits.

### rack_and_stack
Industry: datacenter / colo cabinet build-out, in-rack patching, dressing, decommission. Standards: cabinet density limits, weight/power per RU. Common deliverables: rack elevations, patch matrix, labeling export, photo set per cabinet. Common pitfalls: device weight per RU for floor loading, power whip availability, OOB access.

### datacenter
Industry: full datacenter services — rack/stack + power + RU constraints + decommission. Tier levels (Uptime Institute), cooling classes (CRAC, in-row, RDHX), power classes (208V/30A vs 480V/3-phase). Common pitfalls: facility access windows, escort policies, tier-level cooling assumptions.

### imac
Industry: install / move / add / change for endpoint hardware (laptops, desktops, monitors, peripherals). Tools: SCCM, Intune/Autopilot, Jamf, KACE. Common deliverables: device-to-user map, asset tag updates, image deployment logs. Common pitfalls: legacy asset disposition path, user availability windows, BYOD vs corporate-owned scope ambiguity.

---

## How I'll use your output

1. Save your YAML as `briefing_configs.yaml`.
2. Drop it at `src/orbitbrief_core/brains/data/briefing_configs.yaml`.
3. Run `pytest tests/brains -q` — the existing 15 tests cover schema invariants and per-brain happy paths; your YAML must pass all of them.
4. Re-run the live demo: `python compile_brief.py engagement.json --out artifacts/ --ollama`.
5. Open the reviewer UI: `python -m orbitbrief_core.review_ui --artifacts artifacts/`.
6. PM eyeballs the brief. If it reads like a senior PM wrote it, we ship.

---

## A short worked example so you see the bar

For `low_voltage_cabling`, the **`detailed_scope_of_services`** section's guidance bullets should look like:

```yaml
detailed_scope_of_services:
  - "Differentiate copper drops (UTP/STP, Cat5e/Cat6/Cat6a) from fiber runs (OM3/OM4/OS2)"
  - "Call out DMARC extension scope separately from MDF/IDF homerun work"
  - "List per-IDF homerun count, fiber strand count, and connector type (LC/SC/MTP)"
  - "Include termination scope: jack termination, patch panel termination, fiber connector termination"
  - "State pathway type per run (J-hook, conduit, cable tray, raceway, plenum, riser)"
  - "Specify certification standard up-front: TIA-568.2-D for copper, TIA-568.3-D for fiber, BICSI ITSIMM for as-builts"
  - "Differentiate net-new install from existing-cable reuse, with re-certification scope flagged separately"
  - "Avoid listing pathway construction (J-hook installation, conduit pulls) unless explicitly in scope — usually by-others"
  - "If labeling is in scope, name the standard (ANSI/TIA-606-C) and label format (e.g., IDF-Room-Jack)"
  - "Call out ICRA / barrier requirements separately if healthcare or regulated environment"
```

Compare to the current placeholder:

```yaml
detailed_scope_of_services:
  - "Concrete activities the engagement performs"
  - "Differentiate copper drops, fiber runs, DMARC extension, IDF homerun"
  - "Call out testing / certification standards (BICSI, TIA-568)"
  - "One bullet per executable activity, no nested prose"
  - "Use execution-ready statements that a PM can sequence"
```

The first version is what a Senior Cabling PM would actually write. The second is generic. **Aim for the first across all 4 domains × 9 sections.**

---

## Token budget guidance

Each domain config will be ~80–150 lines of YAML when fully filled. 4 domains × 100 lines + the existing wireless block + headers = the output should land around 1,000–1,500 lines of YAML.

If you hit your output token cap, do them one at a time across messages — `low_voltage_cabling` first, then `rack_and_stack`, then `datacenter`, then `imac`. I'll concatenate.

---

## Final note

You are filling in the **highest-leverage** content surface in the entire system. Everything downstream — validator, calibrator, composer, reviewer UI — works today; the bottleneck on output quality is exactly the prompt material you're producing. **Don't be conservative. Write what you'd want a senior delivery PM to read.**

Output the YAML now.
