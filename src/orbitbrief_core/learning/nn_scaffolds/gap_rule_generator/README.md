# Gap-Rule Auto-Generator (NOT ACTIVE)

The system stops needing manual `sow_missingness.yaml` authoring.
Auto-mines new gap detector rules from items PMs hand-added across
past deals. This is the institutional-learning crown jewel.

## The vision

Today: when the system misses a gap (PM has to hand-add a missing
scope item), a human edits `sow_missingness.yaml` to add a new
detector rule. Tedious, slow, and never scales beyond a few packs.

After activation: every PM-added item flows into the learning
ledger as `pm_decisions.action == "added"`. With 100+ added items
across domains, the generator:

1. **Clusters** added items by embedding similarity (qwen3-embedding
   then DBSCAN at distance 0.3)
2. **Identifies the missing signal** for each cluster — what wasn't
   in the envelope when the PM had to add it (e.g., "envelopes
   without any atom mentioning conduit / raceway / pathway")
3. **Synthesizes a candidate detector rule** in `sow_missingness.yaml`
   shape: `(rule_id, domain_id, missing_pattern, suggested_question)`
4. **Verifies** by running the candidate rule against ALL historical
   envelopes:
   - Precision: of the deals where the rule would have fired, what
     fraction did the PM actually need to hand-add this kind of item?
   - Recall: of the deals where the PM hand-added this kind of item,
     what fraction does the rule catch?
5. **Proposes** to a human reviewer if precision > 0.7 AND recall > 0.6;
   PM accepts → rule lands in `sow_missingness.yaml` automatically.

## Activation gates

1. **100+ PM-added items** across all closed deals
2. **At least 5 items per cluster** for any cluster to be considered a candidate pattern
3. **30 days of beta** confirming the manual-rule-authoring bottleneck is real
4. **Human-in-the-loop verification** — auto-proposed rules require
   manual approval before going live (no auto-merge to YAML)

## Why this is the highest-leverage NN play

| Mechanism | Improves | Cost |
|---|---|---|
| Entity cross-encoder | Coreference precision (5-10% lift) | 1 week, 2-3K labels |
| Embedding head | Retrieval precision (~20% lift) | 3 days, 200 packets |
| Atom-type classifier | Per-atom labeling (5% F1 lift) | 1 week, 5K labels |
| PM-rejection classifier | Cuts queue noise in half | 4 days, 300 decisions |
| **Gap rule generator** | **Eliminates manual rule authoring entirely** | **2-3 weeks, 100+ added items** |
| Margin regression | Flags risky deals | 3 days, 50 deals |
| LoRA fine-tune | Marginal brain quality lift | 3 weeks + ML-ops |

The gap rule generator is the one that lets the corpus genuinely
*grow the rule set itself*. After 6 months in production with 100+
deals, the system should be detecting gaps that no human ever wrote
a rule for — that's the "neural net that learns from past projects"
property you originally asked about, in the architecturally clean
form.

## Pipeline architecture (when active)

```
.orbitbrief_learning_ledger.jsonl
       ↓
[1] filter pm_decisions.action == "added"
       ↓
[2] embed each added item via qwen3-embedding:8b
       ↓
[3] DBSCAN cluster (eps=0.3, min_samples=5)
       ↓
[4] for each cluster:
      - identify "missing signal" via envelope contrastive search
      - synthesize detector rule template
      - run against historical envelopes (precision + recall)
       ↓
[5] propose rules with precision > 0.7 AND recall > 0.6 to a human
       ↓
[6] human reviews / edits / accepts → rule lands in sow_missingness.yaml
```

## Activation path

```bash
# 1. Run miner against the ledger (offline, no impact on live pipeline)
python -m orbitbrief_core.learning.nn_scaffolds.gap_rule_generator.training_data_builder \
    --ledger /azure/blob/learning_ledger.jsonl \
    --envelopes-dir /azure/blob/quote-artifacts \
    --out ./gap_rule_candidates.jsonl

# 2. Validate candidate rules against historical envelopes
python -m orbitbrief_core.learning.nn_scaffolds.gap_rule_generator.eval_harness \
    --candidates ./gap_rule_candidates.jsonl \
    --envelopes-dir /azure/blob/quote-artifacts \
    --out ./gap_rule_evals.jsonl

# 3. Human review of proposed rules (web UI or PR review)
#    Approved rules append to sow_missingness.yaml.

# 4. The live pipeline reads sow_missingness.yaml on next compile.
#    No code change. No model deployment. Just a YAML config diff.
```

Note: `IS_ACTIVE` here is more of a "this analysis path has been
green-lit" flag than a runtime switch. The actual gap detection
always runs from `sow_missingness.yaml`. The generator's job is to
propose additions to that file.
