# Embedding-Head Fine-Tune (NOT ACTIVE)

Triplet-loss fine-tune of a small projection head on top of the
frozen `qwen3-embedding:8b` base. Improves retrieval precision +
packet `semantic_link` edge quality.

## What it does

Today, `qwen3-embedding:8b` is used **zero-shot** for:
- `EvidenceIndex` (atom-level retrieval)
- `PacketIndex` (packet-level retrieval)
- `ClaimIndex` (claim-anchored atoms)
- `ExampleIndex` (few-shot examples)
- `semantic_link` edges in packet certification (you saw this on COPPER_002: 13 edges from `tfidf_char_ngram` with score ~0.99)

A learned projection head (~3M params, frozen base) fine-tuned via
triplet loss on `(anchor, positive, negative)` triples mined from
accepted packets gives ~15-25% retrieval precision lift.

### The signal

`JsonlTrainingLog` captures, for each packet shown to a PM:
- `predicted_payload` (the atoms the system claimed are in the packet)
- `reviewer_action` (accepted / rejected / edited)
- `edited_payload` (what the PM left in)

This is the exact signal a triplet-loss head needs.

## Activation gates

1. **200+ accepted packets** in `JsonlTrainingLog` across at least 3 domains
2. **30 days of beta** confirming zero-shot performance is the bottleneck
3. **Eval uplift ≥ 5 pp on R@10** (retrieve top-10 atoms; check overlap with
   PM-accepted atoms)

## Model architecture

```
frozen qwen3-embedding:8b → 4096-dim vector
                          ↓
               trainable Linear(4096, 512)
                          ↓
               trainable Linear(512, 256)
                          ↓
                    L2 normalize → 256-dim
```

Total trainable params: ~3M. Trains in 30 min on a single GPU.
Inference: 0.5ms/atom after the base encoder has run.

## Activation path

```bash
# 1. Build triplets from training log
python -m orbitbrief_core.learning.nn_scaffolds.embedding_head_finetune.training_data_builder \
    --training-log /azure/blob/training_log.jsonl \
    --out ./triplets.jsonl

# 2. Train head (small enough for any GPU)
python tools/train_embedding_head.py \
    --triplets ./triplets.jsonl \
    --out ./models/embedding_head/

# 3. Evaluate against held-out packets
python -m orbitbrief_core.learning.nn_scaffolds.embedding_head_finetune.eval_harness \
    --model ./models/embedding_head/

# 4. Activate: IS_ACTIVE = True; orchestrator routes embeddings through the head
```

## Fallback behavior

Head inference failure → fall back to zero-shot qwen3-embedding output.
Pipeline never blocks.
