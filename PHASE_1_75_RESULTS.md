# Phase 1.75 Backfill — OPTBOT Results

End-to-end measurement of `tools/envelope_backfill_v2.py` on the OPTBOT
Atlanta mock deal (135-atom parser-os v3 envelope).

## Headline numbers

|  | Baseline (parser-os v3 only) | Phase 1.5 (flat entities) | Phase 1.75 v2 (relational) |
|---|---:|---:|---:|
| Total atoms in envelope | 135 | 149 (+14) | 173 (+38) |
| Total atoms in graph | 70 | 84 | 122 |
| Entity types covered | 11 | 12 | **15** |
| Review-queue items | 12 | 32 | 12 |
| **SOW blocker questions** | 2 | 2 | **3** |
| **SOW warning questions** | 4 | 4 | **8** |
| Workstreams surfaced | 7 | 7 | **8** (+ Security Access Control) |

Phase 1.5 (flat entities) optimized for **review-queue width** — more
items, broader pack activation. Phase 1.75 v2 (relational atoms)
optimized for **review-queue depth** — fewer items but each one denser
and tied to structured relationships. The brief surfaces 4 more SOW
issues a PM has to chase.

## What v2 extracted (38 new atoms across 6 lenses)

```
risks (5):           ALL 5 OPTBOT risks (R-01 .. R-05) with multi-key
                     entity_keys [risk:r_XX, stakeholder:owner, site:affected]
                     and structured value (prob/impact/mitigation/cadence)

phases (6):          ALL 6 OPTBOT phases (Phase 0 .. Phase 5) with
                     entity_keys [phase:N, milestone:start, milestone:end]
                     and structured activities list

payment_terms (4):   30%/40%/20%/10% schedule entries linked to milestones
                     [payment_term:Npct_at_X, milestone:X]

approvals (1):       $1.5M CFO threshold linked: [money:1500000,
                     approval_threshold:1500000_cfo, stakeholder:cfo]

rules (7):           7 contract rules (substitution, escort, badge_access,
                     lift_access, hypercare, blackout, change_order)
                     each with trigger/required_action/approver

entities (15):       Refined entity-level backfill (vendors / sites / etc.)
                     after applying the v1 noise filters
```

## New SOW questions surfaced by v2

The Security Access Control workstream was activated by the v2 escort/
badge_access/lift_access rule atoms. The SOW validator expanded that
into 5 clarification items the baseline never surfaced:

- **Door count / door type** (blocker)
- **Access platform / integration**
- **Locking hardware**
- **REX / DPS / door monitoring**
- **Reader model / manufacturer**

Plus the existing 4-warning baseline (electrical / lead times / escort
billing / site_roster).

## Performance characteristics

- **Total wall-clock**: 36 min (132 jobs × 16s/job sequential on
  Mac Studio qwen3:14b via Tailscale)
- **Pre-condition routing**: cut 558 jobs → 132 jobs (76% reduction)
  by skipping atoms whose text doesn't contain the lens's domain signal
- **Retry-with-backoff**: 3 attempts with 5s/15s/45s on transport
  errors — necessary because Mac Studio Ollama refuses concurrent
  requests once parallel client load saturates the relay
- **Parallel=1 recommended**: Mac Studio single-GPU serializes
  generation; parallel client workers cause connection refusals
  without throughput gain. A future H100 host with vLLM continuous
  batching would unlock 3-5 min runs.

## Files reproducible

| File | Path |
|---|---|
| Baseline brief | `/tmp/optbot_brief/PM_HANDOFF.{md,html,json}` |
| Phase-1.5 brief | `/tmp/optbot_brief_v2/PM_HANDOFF.{md,html,json}` |
| Phase-1.75 brief | `/tmp/optbot_brief_v3/PM_HANDOFF.{md,html,json}` |
| Baseline envelope | `/tmp/optbot_run/ob_envelope_v3/orbitbrief.input.json` |
| Phase-1.5 envelope | `/tmp/optbot_enriched_fixed.json` |
| Phase-1.75 envelope | `/tmp/optbot_v2_full.json` |
| Backfill log | `/tmp/optbot_v2_backfill.log` |

## What's still missing (Phase 2.0 work)

The 38 new atoms encode relationships via **multi-key entity_keys** on a
single atom. That works for retrieval anchoring but doesn't produce
first-class graph edges. To unlock the graph_builder's `same_as` /
`requires` / `derived_from` edge types, the backfill should ALSO emit
edges between atoms (e.g. `risk:r_02 --owned_by--> stakeholder:renee_watkins`).

Other remaining weak points identified during this work:

1. **Vendor-from-BOM-Manufacturer-column**: parser-os xlsx_parser emits
   manufacturer names under `part:` instead of `vendor:`. Fixable in
   parser-os.
2. **Site-attribute linkage**: "ATL-HQ | 620 users | 38 rooms" produces
   site atoms but the per-site counts aren't linked. Need a `site_attribute`
   lens.
3. **Per-site quantity rollups**: "ATL-HQ 52, ATL-WEST 27, ATL-AIR 15"
   should produce `quantity_per_site:device:site:N` triples.
4. **Cross-doc reconciliation**: contradicting numbers across docs aren't
   surfaced as `contradicts` packets.
5. **Document-of-origin tagging**: facts have source_refs but no doc-level
   rollup.
6. **Procurement Q&A pairs**: checklist Q&A items are flat scope_items.
7. **Conditional-approval blocker resolution**: "Approved pending X" not
   tracked through to resolution.

These are the Phase 2.0 / 2.5 backlog items.
