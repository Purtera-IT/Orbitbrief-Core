# Atom-Type + Authority-Class Classifier (NOT ACTIVE)

Small joint classifier (~10M params) predicting `atom_type` (13
classes) + `authority_class` (~7 classes) from atom text + section
path + parser name.

## What it does

Today, atom_type comes from per-parser rules:
- markdown parser tags blocks as `scope_item` by default
- orbitbrief_pdf parser uses section-header heuristics
- email parser tags by signature presence
- transcript parser uses turn-based heuristics

This is brittle. COPPER_002 produced 34 `scope_item` atoms and only 2
`customer_instruction` atoms — yet 3 of those scope_items had clearly
customer-directive language. The current rule-based tagger isn't
strong enough to make that distinction.

Same for `authority_class` — COPPER_002 has 33 atoms tagged
`contractual_scope` but a learned classifier would distinguish
within that bucket (vendor_quote vs customer_authored vs scanned).

## Activation gates

1. **5,000 hand-labeled atoms** across all 13 types (label efforts:
   ~40 hours of annotator time; or bootstrap from existing
   parser-tagged atoms + spot-corrections from beta PMs)
2. **30 days of beta** confirming current heuristics misclassify on
   ≥ 5% of atoms (use `pm_decisions.action == "rejected"` on items
   that were rejected primarily because their atom_type was wrong)
3. **Eval uplift ≥ 5 pp on macro-F1** vs the current rule baseline

## Model architecture

```
input: atom.text (≤ 512 tokens) + section_path + parser_name
       ↓
small encoder (distilbert-base or smaller — 30-60M params)
       ↓ pooled embedding
       ├→ Linear(hidden, 13) → atom_type logits
       └→ Linear(hidden, 7)  → authority_class logits

joint loss = atom_type CE + 0.5 * authority_class CE
```

## Activation path

```bash
# 1. Build labeled dataset
python -m orbitbrief_core.learning.nn_scaffolds.atom_type_classifier.training_data_builder \
    --envelopes-dir /azure/blob/quote-artifacts \
    --corrections-file /azure/blob/atom_relabels.jsonl \
    --out ./atom_labels.jsonl

# 2. Train
python tools/train_atom_classifier.py \
    --labels ./atom_labels.jsonl \
    --out ./models/atom_classifier/

# 3. Eval
python -m orbitbrief_core.learning.nn_scaffolds.atom_type_classifier.eval_harness \
    --model ./models/atom_classifier/

# 4. Activate: IS_ACTIVE = True; orchestrator calls classifier
# AFTER per-parser extraction but BEFORE envelope build.
# Parsers still set tentative atom_type; classifier overrides.
```

## Fallback behavior

Classifier inference failure → fall back to parser-supplied
atom_type + authority_class.
