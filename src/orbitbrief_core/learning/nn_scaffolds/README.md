# NN Scaffolds — six neural mechanisms, all DISCONNECTED by default

This directory holds **scaffolded** neural-network improvements to
the pipeline. None are wired into the live system. Each one is
designed for a **specific activation gate** — only flip the switch
when the gate is green AND ~30 days of real-world beta testing has
shown the heuristic baseline is the limiting factor.

The architecture is set up so each one is a **drop-in upgrade**:
the existing deterministic / rule-based code paths stay in place,
and the NN sits behind a single `IS_ACTIVE` flag. Fallback to the
baseline on any failure (model not loaded, endpoint unreachable,
inference error) is automatic.

**LoRA fine-tuning** is the 7th scaffold; lives at
`../lora_scaffold/` for historical reasons (shipped first). Treat
the seven uniformly.

---

## The six scaffolded mechanisms

| # | Module | What it upgrades | Activation gate | Effort | Expected lift |
|---|---|---|---|---|---|
| 1 | `entity_cross_encoder/` | Replace canonical_key matching for coreference | 2-3K labeled entity pairs (bootstrap from `aliases[]`) | 1 week | High — fixes false-positive entities like `stakeholder:fit_score` |
| 2 | `embedding_head_finetune/` | Fine-tune qwen3-embedding projection head for retrieval + packet `semantic_link` | 200+ accepted packets in `JsonlTrainingLog` | 3 days | ~20% retrieval precision lift |
| 3 | `atom_type_classifier/` | Replace per-parser heuristics for atom_type + authority_class | 5K labeled atoms | 1 week | Medium — better generalization across new artifact types |
| 4 | `pm_rejection_classifier/` | Pre-filter brain outputs by P(PM accepts) | 300+ PM decisions in `JsonlTrainingLog` | 4 days | Halves review-queue noise |
| 5 | `gap_rule_generator/` | **Auto-mine new detector rules from PM-added items** — the institutional-learning loop | 100+ `pm_decisions.action == "added"` items | 2-3 weeks | **Very high** — stops needing manual rule authoring |
| 6 | `margin_regression/` | Predict `(deal_value, margin, outcome)` from envelope features | 50 closed deals with known outcomes | 3 days | Medium — risk-flagging before SOW lock |

### Plus, at `../lora_scaffold/`

| 7 | `lora_scaffold/` | Fine-tune Qwen3-14B per domain pack | 500+ deals/domain + 10pp eval uplift + ML-ops readiness | 3 weeks | Marginal vs the 6 above |

---

## Why six small models beat one big LoRA

Cost comparison for typical SMB usage (100 deals/month after beta):

| Mechanism | Setup | Run cost | Operational complexity |
|---|---|---|---|
| #1 entity cross-encoder | 1 week | $0 (CPU) | Low — one model, version it |
| #2 embedding head fine-tune | 3 days | $0 (CPU) | Low |
| #3 atom_type classifier | 1 week | $0 (CPU) | Low |
| #4 PM rejection classifier | 4 days | $0 (CPU) | Low |
| #5 gap rule generator | 2-3 weeks | $0 (offline cron) | Medium — generated rules need verification |
| #6 margin regression | 3 days | $0 (CPU) | Low |
| **All six combined** | **~6 weeks total** | **$0 incremental** | Per-module model versioning |
| LoRA fine-tune (one domain) | **3 weeks** | **~$400/mo VRAM** | High — ML-ops, A/B routing, rollback |

The six small models together typically buy 25-40 pp of lift on
production metrics (entity precision, retrieval precision, gap recall,
review-queue noise reduction). The LoRA might add another 5-10 pp on
top of that, at significant operational expense.

**Build the six small ones first. Skip the LoRA unless you have an
unambiguous signal that prompt engineering has plateaued.**

---

## Activation rules (apply to all six)

For each module, three hard gates must be green:

1. **Data quantity gate** (per-module — see table above)
2. **Beta-period gate** — ≥ 30 days of real customer deals in production
   on the heuristic baseline. This builds the labeled corpus AND
   confirms the heuristic is the limiting factor.
3. **Eval uplift gate** — held-out test set shows the NN beats the
   heuristic baseline by ≥ 5 pp on the module's key metric.

If any gate is missing, **stay on the heuristic**. The architecture
already makes that work.

---

## What stays unchanged when any of these activate

* The envelope schema (orbitbrief.input.v2)
* The PM_HANDOFF.json shape (frozen contract)
* All 12 import-linter contracts
* Determinism guarantees on substrate stages
* The polish stage
* The review queue + JsonlTrainingLog (still capture corrections)
* The calibrator + validator (still run after every brain)

NN models only change the SPECIFIC SCORING / CLASSIFICATION DECISION
inside their lane. They never break the rest of the pipeline.

---

## Common scaffold structure (each module has these files)

```
<module_name>/
├── __init__.py                  # IS_ACTIVE = False sentinel
├── README.md                    # purpose + activation path + sample input/output
├── training_data_builder.py     # stub that raises NotImplementedError
├── eval_harness.py              # stub that raises NotImplementedError
└── config.yaml                  # hyperparameters + activation gates
```

Importing any of these modules does nothing at runtime. The brain
runners, validators, and orchestrator never reach into this directory.
Activation is a single `IS_ACTIVE = True` flip + the corresponding
endpoint wire-up.
