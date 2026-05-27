# v46 — Risk Propagation Net (RPN)

Design doc — proposal, not committed code.

## 1. The gap

Parser-os outputs a rich knowledge graph in `envelope.json`. Orbitbrief
flattens 5–10% of it into PM_HANDOFF.json and discards the rest. The
brains run LLMs over slice-views (`retrieval_bundles`), then the handoff
builder picks pre-computed PM-facing fields from the envelope and drops
the rest on the floor.

Measured on the OPTBOT deal (`841ea7e0-...`):

| Surface                       | Envelope            | Handoff       | Loss  |
| ----------------------------- | ------------------- | ------------- | ----- |
| Milestones                    | 63 dated events     | 6 phases      | −57   |
| Sites                         | 58 with readiness   | 18 names      | −40   |
| Contested scope items         | 5 (qty conflicts)   | 0 surfaced    | ALL   |
| Project vitals score (0–100)  | 65 / orange         | not surfaced  | ALL   |
| SOW readiness dimensions      | 8 with descriptions | color only    | −7    |
| Graph edges                   | 678                 | 0             | ALL   |
| Entities (sites/people/etc.)  | 191                 | not as graph  | ALL   |
| Authority-class distribution  | 6 classes × counts  | none          | ALL   |

The envelope already tells you `risk_ownership`, `site_readiness_avg`,
and `contradiction_health` are the top detractors. The handoff doesn't.

## 2. Track A — surface what's already computed (0 LLM cost)

Eight new fields, each is a `handoff.X = envelope.Y` pipe. None require
new LLM calls. Each unlocks a PM-visible behavior:

1. **`handoff.project_vitals`** ← `envelope.project_vitals`
   0–100 score, band, weighted components, top drivers/detractors.
   Drives a header gauge in the UI ("65 / 100 — orange").

2. **`handoff.sow_readiness_dimensions`** ← `envelope.sow_readiness_scorecard.dimensions`
   8 named dimensions each with a score + description. Replaces the
   single status colour with a per-dimension scorecard.

3. **`handoff.contested_scope_items`** ← `envelope.scope_truth.contested`
   Every device whose count differs across documents. Each entry carries
   competing values + authority-ranked claims. PM clicks an item, sees
   "SOW says 3, vendor quote says 15" with atom IDs.

4. **`handoff.site_readiness`** ← `envelope.site_readiness.sites`
   58 sites with per-site readiness scores. UI: site picker sorts by
   risk. Lowest 3 (`least_ready_sites`) get a chip.

5. **`handoff.milestones`** ← `envelope.pm_dashboard.milestones_timeline`
   All 63 dated events with atom-level provenance. Replaces the 6-phase
   summary. Drives a Gantt-shaped view.

6. **`handoff.stakeholder_load`** ← `envelope.stakeholder_load`
   Per-stakeholder load with `risk_count`, `decision_count`, etc. + a
   `bottlenecks` list. PM sees who's drowning vs who's idle.

7. **`handoff.evidence_authority`** ← `envelope.summary.by_authority_class`
   Counts atoms by `contractual_scope` / `meeting_note` / `vendor_quote`
   / etc. Drives a confidence badge per fact ("backed by SOW" vs
   "mentioned in transcript").

8. **`handoff.change_order_timeline`** ← `envelope.change_order_timeline.entries`
   Structured delta + approval signal per entry. Richer than the
   existing `change_order_triggers` (which only counts triggers).

Implementation: a single `handoff_passthrough.py` module that reads
envelope, maps the eight fields, validates shape. Plumbed into
`build_pm_handoff()` so it runs every compile.

## 3. Track B — Risk Propagation Net (RPN)

The envelope is a graph. We are using LLMs to summarize SLICES of it.
We are not using the GRAPH STRUCTURE for inference. The RPN closes that
gap with a small GNN that runs in milliseconds and predicts:

- which atoms are high risk
- which atom pairs contradict (beyond what the parser already flagged)
- which sites are likely to cost-overrun
- which milestones are likely to slip
- which stakeholders are bottlenecks
- which SRL fields will go unanswered
- which scope items are likely to spawn change orders

### 3.1 Inputs (per envelope)

- **Atom nodes (~300/deal):**
  - Text embedding (BGE-M3 384-d, run once at parser time, cached)
  - One-hot authority class (`contractual_scope`, `meeting_note`,
    `vendor_quote`, `transcript`, `email`, `table_extraction`)
  - One-hot atom type (11 classes already in `summary.by_atom_type`)
  - Authority rank (scalar 0–100, already in envelope)
  - Verified flag (boolean, source-replay status)
  - Section-path positional embedding (8-d learned)

- **Entity nodes (~200/deal):**
  - Type one-hot (17 entity_types already in envelope)
  - Canonical-name embedding
  - Aggregate stats (atom count, edge count, authority rank avg)

- **Edges (~700/deal):**
  - Type one-hot (4 edge types — supports, contradicts, mentions, depends_on)
  - Edge weight (already computed by parser)

This is all in the envelope today. **No new parsing required.**

### 3.2 Architecture

A 3-layer message-passing GNN with heterogeneous edge types:

```
Layer 1: atom <-> atom  (within-doc, via edges)
  - Edge-type-aware attention (separate W per edge type)
  - Output: contextualised atom embedding (384-d → 256-d)

Layer 2: atom <-> entity  (via atoms_by_entity_key index)
  - Cross-type attention: atoms aggregated into entities,
    entities broadcast back to atoms
  - Output: entity embedding + atom-with-entity-context

Layer 3: entity <-> entity  (via parser-extracted entity edges)
  - Site nodes pool atoms tagged with site_slug
  - Stakeholder nodes pool atoms they authored or own
  - Milestone nodes pool atoms whose iso falls in their window
```

Size: ~2M params. Trains on a single GPU in minutes. Inference 50ms
per envelope on CPU.

### 3.3 Output heads (multi-task)

```python
heads = {
    "atom_risk":            Linear(256, 1),   # sigmoid → P(risk)
    "atom_pair_contradict": Bilinear(256, 256, 1),
    "site_cost_overrun":    Linear(256, 1),
    "milestone_slip_days":  Linear(256, 1),   # regression
    "stakeholder_bottleneck": Linear(256, 1),
    "srl_field_gap":        Linear(256, len(SRL_CATEGORIES)),
    "change_order_prob":    Linear(256, 1),   # per scope-item entity
}
```

Each head has its own loss; weighted sum during training.

### 3.4 Training signal

Cold-start (weak supervision from a few completed deals):

- `atom_risk` ← did this atom's text appear in the final SOW's
  `risks_section` or in a gap card a PM accepted?
- `atom_pair_contradict` ← does
  `envelope.pm_dashboard.cross_doc_contradictions` flag this pair?
  (Bootstrap labels — parser's already running this).
- `site_cost_overrun` ← on past closed deals, did
  `actual_cost(site) / quoted_cost(site) > 1.05`?
- `milestone_slip_days` ← `actual_date − committed_date` on closed deals.
- `stakeholder_bottleneck` ← did this person miss > 2 commitments?
- `srl_field_gap` ← which SRL fields were `missing` at SOW signing?
- `change_order_prob` ← did this scope item later spawn a change order?

Active learning (warm phase): PM thumbs-up/down on each predicted risk
in the UI → label collected → nightly fine-tune. Distillation from the
planner brain: have the brain emit per-atom rationales, train the GNN
head to predict the rationale's salient features.

### 3.5 Integration with brains

The RPN runs **before** the brains. Brain prompts get a `risk_scores`
field per packet:

```json
{
  "bundle": { "packets": [...] },
  "risk_scores": {
    "atm_5792...": { "atom_risk": 0.91, "drives": ["cost_overrun(site:atl_air)"] },
    ...
  }
}
```

The brain now KNOWS which atoms to weight in its scope generation. The
LLM no longer needs to discover risk patterns from scratch each call.

### 3.6 Why a GNN, not a bigger LLM

- **Cost:** 50ms / envelope on CPU vs 2–3 min / brain call on a 14B LLM.
- **Calibrated probabilities:** sigmoid output ∈ [0,1], not text we
  have to JSON-parse and validate.
- **Trainable on PM behavior:** a thumbs-up changes the model. An LLM
  needs prompt engineering.
- **Graph-native:** the envelope IS a graph. Linear-attention LLMs
  flatten it. A GNN consumes it.
- **Composable:** new task? Add a head, distill from an LLM, ship.

### 3.7 Phasing

**v46.0** — Track A only. Ship the 8 passthroughs. Zero ML risk.

**v46.1** — Stub RPN with weak-supervised heads trained on synthetic
labels from past compile outputs (no PM in the loop). Output: a
`handoff.risk_signals` block with `atom_risk_top_25`,
`site_cost_overrun_top_5`, `milestone_slip_top_10`.

**v46.2** — Wire RPN output into brain prompts. Measure brain output
quality with vs without `risk_scores` (A/B on saved envelopes).

**v46.3** — UI: thumbs on each predicted risk → label → nightly
fine-tune. Per-account models after 100 labels.

**v46.4** — Distillation from the planner brain (have it emit per-atom
rationales → train an interpretable head).

## 4. What this does NOT do

- Doesn't replace the LLM brains. Brains still author SOW prose.
- Doesn't replace the SOW validator. Validator still owns rule checks.
- Doesn't change the parser. Parser still does atoms/entities/edges.
- Doesn't require new annotations from PMs at cold-start. Weak
  supervision from closed-deal outcomes is enough to begin.

## 5. Open questions

- Embedding model choice for atom text — BGE-M3 vs the chat model's
  own embedding endpoint vs a smaller dedicated model.
- Whether to keep entity-level pooling separate from atom-level or
  collapse to one GAT layer. Probably keep separate — gives us a
  natural place to insert site/stakeholder/milestone heads.
- How aggressively to weight bootstrap labels vs PM labels — PM
  signal is high-quality but sparse; weak supervision is noisy but
  plentiful.
