# OrbitBrief analyst review — find the labeling gaps

You are reviewing a single engagement case (or several) from the
OrbitBrief corpus to find every place the system mislabeled,
forgot, or otherwise mishandled a fact in the source artifacts.
Your output becomes the labeling-fix backlog for two repos:

* **`parser-os`** — extraction layer. Owns atoms, locators, packet
  certification, entity normalization, edge inference, source
  replay. If a fact in the raw artifact didn't land as an atom,
  or landed with the wrong type/authority/locator, the fix lives
  here.
* **`Orbitbrief-Core`** — synthesis layer. Owns domain pack routing
  (`pack_prior`), physical-site clustering (`site_reality`),
  per-domain brains, validator rules, calibrator weights,
  composer aggregation. If atoms were extracted correctly but the
  brain mis-routed them, made up content, or dropped them from the
  brief, the fix lives here.

> Note: **SowSmith is deprecated** (the repo is an empty stub that
> redirects to parser-os). All extraction-layer findings go to
> `parser-os`. Don't tag findings as `sowsmith`.

---

## What to read

Each case folder under `cases/<CASE_ID>/` is self-contained. Read
in this order:

1. `README.md` — orientation + per-case stats.
2. `raw/` — the original source artifacts (PDFs, CSVs, MDs, XLSXs).
   Open them as a PM would open intake.
3. `lineage/raw_vs_extracted.md` — **the killer file**. For each
   source artifact, the raw extracted text preview is shown next
   to every atom parser-os pulled from it, with downstream-survival
   flags (`brain` and `brief` columns).
4. `extraction/atoms.md`, `extraction/packets.md`,
   `extraction/entities_and_edges.md` — full extraction view.
5. `synthesis/pack_prior.md` — domain-routing decision.
6. `synthesis/site_reality.md` — physical-site clustering.
7. `synthesis/brain_outputs/<pack>.md` — what each brain wrote.
8. `brief.md` — the final PM-readable composed brief.
9. `lineage/inspection_report.html` — single-page lineage report
   (open in a browser; works offline).

If the case is from a **substrate-only** sweep (no LLM brains
ran), `brain_outputs/` and `brief.md` will be empty/missing.
Focus on extraction-layer findings in that case.

---

## Finding taxonomy

Every finding falls into one of these categories. Tag yours
accordingly using the `category` field below.

### Extraction-layer findings (target_repo: `parser-os`)

| category | what it means |
|---|---|
| `atom_omitted` | A fact in the raw artifact has no atom. e.g. a 60 KB MD scope brief produced 0 atoms (parser missing for that artifact type), or a key bullet in a PDF page is absent from the atom list. |
| `atom_type_mislabeled` | Atom exists but its `atom_type` is wrong. e.g. a hard exclusion was tagged `scope_item` instead of `exclusion`. |
| `atom_authority_mislabeled` | Wrong `authority_class`. e.g. a customer instruction is tagged `machine_extractor` instead of `customer_current_authored`. |
| `atom_text_garbled` | Text was extracted but is mangled (truncated, OCR-broken, columns merged from a CSV row). |
| `atom_confidence_off` | Confidence is wildly miscalibrated (e.g. 0.9 on an unreadable scan, 0.4 on a clean header). |
| `locator_wrong` | `locator` doesn't actually map back to the source (page number off, row index off, sheet name missing). |
| `packet_family_wrong` | Packet exists but was certified into the wrong family (e.g. a `quantity_conflict` certified as `quantity_claim`). |
| `packet_anchor_wrong` | Packet `anchor_key` doesn't match the entity it should anchor to. |
| `entity_not_merged` | Two entities should have been deduplicated to one. e.g. "Belden Cat6" and "Belden CAT6 CMP" appear as separate entities. |
| `entity_canonical_name_wrong` | Entity's `canonical_name` is bad (truncated, lowercased oddly, missing parent context). |
| `edge_missing` | Two atoms should have been linked (e.g. `same_as`, `contradicts`, `supports`) but no edge exists. |
| `edge_type_wrong` | Edge exists but type is wrong (e.g. tagged `supports` when atoms actually `contradict`). |
| `replay_failed_for_clean_text` | Source replay marked an atom `verified=failed` even though the raw text clearly matches (parser-side fuzzy-match issue). |

### Synthesis-layer findings (target_repo: `Orbitbrief-Core`)

| category | sub-target | what it means |
|---|---|---|
| `pack_routing_wrong` | `world_model/pack_prior` | Wrong pack scored top, or the right secondary pack was missed (raw_score = 0 when it shouldn't be). Provide the keyword(s) that should have hit. |
| `pack_keywords_missing` | `world_model/pack_prior` (`brains/data/briefing_configs.yaml` or `world_model/data/domain_packs.yaml`) | A vocabulary item belongs to a pack but isn't in its `keywords` or `boosted_keywords`. |
| `site_clustering_missed` | `world_model/site_reality` | Two `site:*` entities should have merged into one cluster. Or a real site got dropped. |
| `site_canonical_name_wrong` | `world_model/site_reality` | Cluster picked a bad canonical name. |
| `brain_section_wrong` | `brains/<pack>` | Brain emitted an item in the wrong section (e.g. a `customer_responsibility` placed in `assumptions`). |
| `brain_made_up_content` | `brains/<pack>` | Brain emitted text the source doesn't support (false positive). |
| `brain_missed_content` | `brains/<pack>` | Brain didn't emit anything for a clear scope item that the bundle contained. |
| `brain_specificity_low` | `brains/<pack>` (prompt) | Brain emitted generic boilerplate when the source had real SKUs / quantities / standards. |
| `brain_grounding_thin` | `brains/<pack>` (runner / prompt) | Brain item cites a packet but didn't cite a specific atom even when one was clearly available. |
| `validator_missed_issue` | `validator/` | An item shipped that should have been flagged (e.g. a real `impossible_state` not caught). |
| `validator_false_positive` | `validator/` | A rule fired when it shouldn't have. |
| `calibrator_confidence_off` | `calibrator/` | Calibrated confidence is wildly off from reviewer-perceived confidence. |
| `composer_dropped_real_content` | `composer/` | Composer dropped an item that was valid in the brain output. |

### Schema / data-model findings (target_repo: depends)

| category | sub-target | what it means |
|---|---|---|
| `schema_field_missing` | parser-os or Orbitbrief-Core | An obvious field is missing from the schema (e.g. atoms have no `language` field but multilingual intake exists). |
| `enum_value_missing` | parser-os | An `atom_type` / `authority_class` / `packet_family` enum doesn't have a value for a real real-world category. |

### Workbook / config findings (target_repo: `Orbitbrief-Core`)

| category | sub-target | what it means |
|---|---|---|
| `workbook_normalization_gap` | `brains/data/briefing_configs.yaml` | A controlled vocabulary in the workbook is missing a real-world value (e.g. `cable_categories` doesn't include "Cat 7A"). |
| `workbook_guidance_wrong` | `brains/data/briefing_configs.yaml` | A per-section guidance bullet is misleading or contradicted by real engagements. |

---

## Finding template (use this verbatim)

Output one YAML block per finding. Aim for 10–40 findings per case
you review. Be specific and cite atom_id / packet_id / line numbers.

```yaml
- finding_id: F001
  case_id: COPPER_001_SPRING_LAKE_AUDITORIUM
  category: atom_omitted
  severity: blocker | warning | info
  target_repo: parser-os | Orbitbrief-Core
  target_subpath: app/parsers/text.py
  source_artifact: COPPER_001_SPRING_LAKE_AUDITORIUM_managed_services_package.md
  raw_evidence: |
    "Quote includes 186 Belden Cat6 CMP drops with RJ45 termination
    to IDF patch panels and certification per TIA-568.2-D."
    (line 142, scope_overview section)
  current_behavior: |
    Zero atoms extracted from this MD file (parser_name=none/unknown).
    parser-os has no Markdown atom extractor configured.
  expected_behavior: |
    MD scope-brief files should produce structured atoms similar to
    DOCX/TXT: paragraph-level scope_item / quantity / vendor_line_item
    atoms with section_path locator.
  suggested_fix: |
    Add app/parsers/markdown.py mirroring app/parsers/text_parser.py
    but using a markdown-aware tokenizer (mistune or markdown-it-py)
    that preserves heading-based section_path locators.
  reproducible: yes
  observed_in_other_cases: [COPPER_002_..., LOWVOLT_001_...]
```

### Required fields

* `finding_id` — sequential within your review (F001, F002, …)
* `case_id` — the engagement case name (e.g. `COPPER_001_SPRING_LAKE_AUDITORIUM`)
* `category` — exactly one from the taxonomy above
* `severity`:
  * `blocker` — the finding makes the brief unsafe to publish
    without manual repair
  * `warning` — the finding degrades quality but doesn't break it
  * `info` — nice-to-have polish
* `target_repo` — `parser-os` or `Orbitbrief-Core`
* `target_subpath` — best-guess path inside the repo where the fix
  lives (e.g. `app/parsers/markdown.py`,
  `src/orbitbrief_core/world_model/pack_prior/router.py`,
  `src/orbitbrief_core/brains/data/briefing_configs.yaml`)
* `source_artifact` — filename in `raw/` that contains the evidence
* `raw_evidence` — the exact text/value/section from the raw
  source. Include line/page/row references where available.
* `current_behavior` — what the system actually did. Cite atom_ids,
  packet_ids, brain item ids if relevant.
* `expected_behavior` — what should have happened.
* `suggested_fix` — concrete, actionable. Reference specific
  files/functions where possible.
* `reproducible` — `yes` if the issue would happen on every run,
  `flaky` if it's LLM-stochastic.
* `observed_in_other_cases` — a list of other case_ids where you
  noticed the same pattern (helps prioritize systemic vs one-off).

### Optional fields

* `related_atom_ids` — list of relevant atom_ids
* `related_packet_ids` — list of relevant packet_ids
* `related_entity_keys` — list of relevant entity canonical_keys
* `related_brain_item_ids` — list of brain item ids (e.g. `scope_overview_001`)
* `screenshot_path` — if you took a screenshot of the raw source

---

## Worked example: a good finding

```yaml
- finding_id: F003
  case_id: COPPER_001_SPRING_LAKE_AUDITORIUM
  category: pack_keywords_missing
  severity: warning
  target_repo: Orbitbrief-Core
  target_subpath: src/orbitbrief_core/brains/data/briefing_configs.yaml
  source_artifact: COPPER_001_SPRING_LAKE_AUDITORIUM_noc_soc_onboarding_packet_weirdfmt.pdf
  raw_evidence: |
    PDF page 1, table "OWNER REVIEW Monitoring Intake and Alert Routing":
      Severity | SLA | Route | Channel | Window
      Critical | 15-min response | NOC L2 | PagerDuty | 24x7
      Medium | 4-hour response | NOC L1 | ServiceNow incident | suppress during CAB
  current_behavior: |
    pack_prior assigned msp.raw_score = 95 (rank #2) but msp's
    boosted_keywords list in briefing_configs.yaml does not include
    "PagerDuty", "NOC L1/L2", "CAB" (Change Advisory Board), or
    "ServiceNow". msp's softmax confidence rounded to 0.0000 because
    cabling dominated the engagement, so the msp brain only ran
    because the orchestrator switched to raw-rank picking.
  expected_behavior: |
    msp pack should score higher (~150-200 raw) on this PDF given
    the NOC/SOC operational vocabulary present. Routing should
    surface msp as a strong secondary even when cabling dominates.
  suggested_fix: |
    Add to msp.boosted_keywords in briefing_configs.yaml:
      - pagerduty
      - opsgenie
      - cab            # Change Advisory Board
      - noc_l1
      - noc_l2
      - servicenow
      - jira_service_desk
      - alert_routing
    Re-run pack_prior on COPPER_001 + STRESS_BMS_SPECS to validate.
  reproducible: yes
  observed_in_other_cases: [STRESS_BMS_SPECS, STRESS_NET_MAINT]
  related_atom_ids:
    - atm_0c1516afe60e7f00
    - atm_29d8e1a4156af8b2
  related_packet_ids: []
```

## Worked example: a bad finding (don't write these)

```yaml
- finding_id: F099
  category: brain_missed_content
  severity: warning
  raw_evidence: "The brief feels short."
  current_behavior: "Not enough items."
  expected_behavior: "More items."
  suggested_fix: "Improve the prompt."
```

This is useless because:
* No specific atom_id, packet_id, or raw quote.
* "Not enough" — by what measure?
* "Improve the prompt" — which prompt? What change?
* Not reproducible by another reviewer.

---

## Output structure

Compile your findings into a single `findings.yaml` per case (or
one big file across cases — your call). Then group them at the
end by `target_repo` so the engineering teams can route fast:

```yaml
summary:
  cases_reviewed: [COPPER_001_SPRING_LAKE_AUDITORIUM, STRESS_NATOMAS_WIRELESS, STRESS_NET_MAINT]
  total_findings: 47
  by_severity:
    blocker: 4
    warning: 28
    info: 15
  by_target_repo:
    parser-os: 22
    Orbitbrief-Core: 25
  by_category:
    atom_omitted: 6
    atom_type_mislabeled: 3
    pack_keywords_missing: 8
    brain_missed_content: 7
    brain_specificity_low: 5
    workbook_normalization_gap: 4
    # ...

findings:
  - { finding_id: F001, ... }
  - { finding_id: F002, ... }
  # ...
```

If you prefer JSON, output the same structure as `findings.json` —
both ingest cleanly.

---

## Sanity checks before submitting

1. Every finding has all required fields populated.
2. Every `raw_evidence` block contains a verbatim quote (or precise
   reference: page X, row Y, section Z) from the raw source — not
   a paraphrase.
3. Every `target_subpath` is a real path you can find in the repo.
   Skim the trees if you're unsure:
   * `parser-os/app/{core,parsers,domain}/`
   * `Orbitbrief-Core/src/orbitbrief_core/{evidence_runtime,retrieval,world_model,brains,validator,calibrator,composer,review_runtime,orchestrator}/`
4. `suggested_fix` is concrete — references a file or function,
   not a feeling.
5. `severity` reflects production impact:
   * Would a senior PM publishing this brief get embarrassed by
     this issue? → `blocker`
   * Would a senior PM edit this issue but still ship the doc? →
     `warning`
   * Would a senior PM not notice? → `info`

---

## After you submit

The bundle's `MASTER_LLM_REVIEW_PROMPT.md` is for an LLM running a
*different* pass — high-level system review, not granular
labeling. Your output is the **operator backlog**: each finding
becomes a GitHub issue (or a YAML row that's bulk-imported).

Engineering will:
1. Sort findings by `target_repo` + `severity`.
2. Cluster findings by `category` to spot systemic patterns
   (e.g. 8 `pack_keywords_missing` findings → one workbook update
   PR fixes them all).
3. Prioritize blockers, then high-frequency warnings, then info.
4. Re-run the corpus after each fix and verify the originally-
   flagged behavior changed.

The faster + sharper your labeling-fix list, the faster the
system gets to "publish without manual repair" quality. Be blunt,
specific, and operator-focused.
