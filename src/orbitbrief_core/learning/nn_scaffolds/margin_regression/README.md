# Margin / Outcome Regression (NOT ACTIVE)

Small MLP that predicts `(deal_value_est, margin_est, outcome_prob)`
from envelope features. Used at compile time as a sanity check on
PM assumptions and to flag risky deals before SOW lock.

## What it does

Today, `margin_view.deal_total` is only populated when the envelope
has explicit `vendor_line_item` atoms with `quantity × unit_price`.
COPPER_002 shows the gap: `margin_view = {deal_total: 0, confidence: "low"}`
because the case dossier doesn't include a vendor quote.

After activation, the regressor uses every signal in the envelope
to produce a model-based estimate:

* Atom counts by type
* Packet counts by family
* parser_quality score
* Domain pack mix (one-hot)
* Reconciliation flag count + kinds
* Urgency signal counts
* Has_vendor_quote (binary)
* Has_executive_stakeholder (binary)
* Per-domain comparable_deals avg margin (from learning ledger retrieval)

Output: model-based `(deal_value_est, margin_est, outcome_prob)`
shown next to the heuristic `margin_view` in the UI. PM sees both;
diff > 5 pp triggers a "model disagrees with PM" flag.

## Activation gates

1. **50 closed deals** with known final_margin_pct in the learning ledger
2. **30 days of beta** confirming the heuristic margin_view is too
   often `0` to be useful in practice
3. **Eval MAE ≤ 4 pp** on held-out margin predictions (i.e., model
   error < 4 percentage points absolute)
4. **No bias by domain** — per-domain MAE within 2 pp of overall MAE

## Model architecture

```
input: 50-dim feature vector (counts + parser_quality + domain mix + has_X flags + retrieved historical avgs)
       ↓
MLP(50 → 64 → 32 → 3)
       ↓
output:
  - deal_value_est        (log-scale regression)
  - margin_est_pct        (linear regression)
  - outcome_prob_won      (sigmoid)
```

~5M params. CPU inference in microseconds.

## Activation path

```bash
# 1. Build training set from closed deals
python -m orbitbrief_core.learning.nn_scaffolds.margin_regression.training_data_builder \
    --ledger /azure/blob/learning_ledger.jsonl \
    --out ./margin_training.jsonl

# 2. Train
python tools/train_margin_regressor.py \
    --data ./margin_training.jsonl \
    --out ./models/margin_regressor/

# 3. Eval
python -m orbitbrief_core.learning.nn_scaffolds.margin_regression.eval_harness \
    --model ./models/margin_regressor/

# 4. Activate: IS_ACTIVE = True; pm_handoff.pm_intelligence routes
# through the model in build_margin_view() and adds:
#   margin_view.model_based_estimate = {value, margin, outcome_prob, confidence}
```

## Fallback behavior

Model failure → margin_view ships heuristic-only (current behavior).
The model never overrides the heuristic; both are shown side-by-side.
