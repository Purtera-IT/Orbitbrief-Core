# Entity Cross-Encoder (NOT ACTIVE)

Cross-encoder for entity coreference. Replaces / augments the
canonical_key matcher in `app/core/entity_resolution.py`.

## What it does

Given two entity candidates, predicts P(they are the same real-world
entity). The current heuristic system uses canonical_key shape +
alias rules; this learns the same-or-not decision from labeled pairs.

### The problem this solves

Real envelope from COPPER_002 produced an entity `stakeholder:fit_score`
— the parser noticed "Fit Score: 9.5/10" as a "stakeholder" because
of a regex match. The current rule-based resolver has no way to know
this is a meta-rating, not a person. A learned cross-encoder over
~3K labeled `(text_a, text_b, same)` examples handles cases like:

- `Cisco Catalyst 9166D1-B` ↔ `C9166D1` ↔ `9166`
- `ATL-HQ` ↔ `Atlanta HQ` ↔ `Atlanta Headquarters` ↔ `atl hq`
- `Renee Watkins` ↔ `R. Watkins` ↔ `Ms. Watkins`
- `Fit Score` is NOT a real entity → suppress

## Activation gates

ALL must be true:

1. **2-3K labeled pairs** — can bootstrap from existing `entities[].aliases`
   in past envelopes. Each `aliases` list of length N produces N*(N-1)/2
   positive pairs. Negatives = random non-overlapping entity pairs from
   the same corpus.
2. **30 days of beta** — confirms current resolver's failure modes are
   real, not corner cases.
3. **Eval uplift ≥ 5 pp** — held-out test set of 500 hand-labeled pairs
   shows cross-encoder beats canonical_key heuristic by ≥ 5 pp on F1.

## Model recommendation

`cross-encoder/ms-marco-MiniLM-L-6-v2` fine-tuned (~22M params).
Inference at 5-10ms/pair on CPU. Run only on top-K candidates from
the canonical_key shortlist — never on the full Cartesian product.

## Activation path

```bash
# 1. Build training pairs from past envelopes
python -m orbitbrief_core.learning.nn_scaffolds.entity_cross_encoder.training_data_builder \
    --envelopes-dir /azure/blob/quote-artifacts \
    --out ./training_pairs/entity_pairs.jsonl

# 2. Train (uses config.yaml hyperparameters)
python tools/train_entity_cross_encoder.py \
    --pairs ./training_pairs/entity_pairs.jsonl \
    --out ./models/entity_cross_encoder/

# 3. Evaluate against held-out
python -m orbitbrief_core.learning.nn_scaffolds.entity_cross_encoder.eval_harness \
    --model ./models/entity_cross_encoder/ \
    --test ./test_pairs/entity_pairs_held_out.jsonl

# 4. Activate
# Edit nn_scaffolds/entity_cross_encoder/__init__.py: IS_ACTIVE = True
# Set the inference endpoint in config.yaml
# entity_resolution.py reads IS_ACTIVE at startup and routes through the model
```

## Fallback behavior (when active)

Model inference failure → fall back to canonical_key matcher with a
warning logged. The pipeline never blocks on the model.
