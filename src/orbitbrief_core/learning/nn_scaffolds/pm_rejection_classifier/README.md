# PM-Rejection Classifier (NOT ACTIVE)

Pre-brain-output filter that predicts P(PM accepts) per item.

## What it does

Today's flow:
```
brain → ComposedBrief → calibrator → review queue (everything visible to PM)
```

After activation:
```
brain → ComposedBrief → rejection-classifier
                          ├ P < 0.3 → suppress entirely
                          ├ P > 0.85 + validator clean → auto-approve
                          └ 0.3 ≤ P ≤ 0.85 → review queue (sorted by P)
```

This halves review-queue noise in steady state.

## The signal

`JsonlTrainingLog` already captures every PM decision with:
- `predicted_payload` (full atom/section text the brain emitted)
- `predicted_raw_confidence` + `predicted_calibrated_confidence`
- `reviewer_action` ∈ {accepted, rejected, edited, ...}
- `brain` (which domain brain produced it)
- `section` (which of the 9 briefing sections)

300+ rows is enough to start training. ~1000 rows hits diminishing
returns; above that, retrain monthly.

## Activation gates

1. **300+ PM decisions** with non-trivial reject rate (≥ 10% rejected)
2. **30 days of beta** confirming the queue is noisy enough to justify filtering
3. **Eval shows ≥ 5 pp precision lift on rejection** vs the Platt-only baseline
4. **No false-suppression on safety items** — Auto-suppression of any
   item with severity=blocker is BLOCKED; safety net stays on.

## Model architecture

```
input:
  - atom/section text                (≤ 512 tokens)
  - atom_type / section
  - brain                            (one-hot over 14 domain brains)
  - predicted_raw_confidence         (the calibrator's input)
  - signal_vector                    (the 10-feature calibrator input)
  - retrieval_hit_count              (how many similar past items found)
       ↓
distilbert text encoder + concatenate with numeric features
       ↓
MLP head → sigmoid → P(PM accepts)
```

~50M params total. CPU inference at ~10ms/item.

## Activation path

```bash
# 1. Build training data from the training log
python -m orbitbrief_core.learning.nn_scaffolds.pm_rejection_classifier.training_data_builder \
    --training-log /azure/blob/training_log.jsonl \
    --out ./pm_decisions.jsonl

# 2. Train
python tools/train_pm_rejection_classifier.py \
    --decisions ./pm_decisions.jsonl \
    --out ./models/pm_rejection_classifier/

# 3. Eval — must NOT suppress safety items
python -m orbitbrief_core.learning.nn_scaffolds.pm_rejection_classifier.eval_harness \
    --model ./models/pm_rejection_classifier/

# 4. Activate: IS_ACTIVE = True; composer routes through the classifier
```

## Safety rules

* Auto-suppression of blocker-severity items is **never allowed**
* The classifier output is shown in the audit log so PMs can spot
  systematic bias (e.g., "you've been auto-approving HIPAA items
  without review")
* Reviewer can override per-item in the review UI; override decisions
  flow back into the training log for next retrain
