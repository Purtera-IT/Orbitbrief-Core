# LoRA fine-tuning scaffold (NOT ACTIVE)

This directory holds the **scaffolding** for a future LoRA fine-tuning
effort on Qwen3-14B per domain pack. **Nothing here runs in
production.** The brain runners never import these modules; the
orchestrator never reads `lora_config.yaml`.

The scaffold exists so the activation path is clear and small. When
the corpus + the metrics justify it, we flip a config flag and route
brain calls through a vLLM endpoint serving the adapter. No
architectural refactor needed.

## When to activate

Three gates, ALL must be true:

1. **Corpus size** — ≥ 500 closed deals in the target domain pack
   (e.g. ≥ 500 closed `wireless` deals).
2. **Eval uplift** — the eval harness shows ≥ 10 % recall × precision
   improvement vs prompt-only on a held-out test set.
3. **ML-ops readiness** — you have model-version tracking, A/B
   routing, automatic rollback on quality regression, and a daily
   drift monitor.

If any of these is missing, **stay on prompt engineering**. Most
products that ship this kind of system never need LoRA. Prompt
engineering + retrieval + the calibrator covers ~80–90 % of what a
fine-tune would buy you, with a tenth of the operational cost.

## The activation path

When all three gates are green:

1. **Build training pairs**:
   ```bash
   python -m orbitbrief_core.learning.lora_scaffold.training_data_builder \
       --domain wireless --out ./training_pairs/wireless.jsonl --min-pairs 500
   ```
2. **Run LoRA training** (uses `lora_config.yaml` + the training pairs):
   ```bash
   # Use any standard LoRA trainer (axolotl / unsloth / peft+trl)
   # Output: ./adapters/qwen3-14b-wireless-lora/
   ```
3. **Eval against the held-out test set**:
   ```bash
   python -m orbitbrief_core.learning.lora_scaffold.eval_harness \
       --domain wireless --adapter ./adapters/qwen3-14b-wireless-lora
   ```
   If `blocked=True`, do not deploy.
4. **Serve the adapter via vLLM**:
   ```bash
   vllm serve qwen/Qwen3-14B \
       --enable-lora --lora-modules wireless=./adapters/qwen3-14b-wireless-lora \
       --port 8001
   ```
5. **Flip the config flag** in the orchestrator: set
   `lora_scaffold.IS_ACTIVE = True` and add the vLLM endpoint to
   `lora_config.yaml`. The brain runner (`brains/_briefing_runner.py`)
   reads `IS_ACTIVE` at startup and routes through the LoRA endpoint
   instead of Ollama qwen3:14b. **Automatic fallback** to the base
   model on adapter endpoint failure.

## Why not activate now?

Cost comparison for typical SMB usage (10 customers, 100 deals/month):

| Mechanism | Setup cost | Run cost | Quality lift |
|---|---|---|---|
| Better prompts (already doing) | 1 day | $0 | baseline |
| **Retrieval over past deals** (now active) | 2 days | $0 | +5–8 pp recall, "knows past" |
| **Pattern mining** (now active, fires at 50 deals/domain) | 1 day | $0 | +3–5 pp recall, dataset-grounded |
| **Calibrator retraining** (now active, fires at 500 PM decisions) | half-day | $0 | ECE drops from 0.04 to ~0.02 |
| **LoRA fine-tune** (this scaffold) | 3 weeks | $400/mo VRAM | +5–10 pp recall on top of above |

The first four mechanisms together typically buy you 15–20 pp
improvement at zero training cost. LoRA buys an additional 5–10 pp
at significant operational expense. Most SMBs never hit the corpus
size for it to be worth the lift.

**This scaffold is here so that when (if) you DO need it, the
plumbing is already designed and the architecture is clean. Don't
activate until the gates are green.**

## What stays unchanged when LoRA activates

* The atom / entity / edge / packet schema (frozen contract)
* The PM_HANDOFF.json shape (frozen contract)
* The polish stage (still runs after brain output)
* The validator + calibrator (still run after polish)
* The review queue + JsonlTrainingLog (still capture PM corrections)

LoRA only changes the brain's *output style* — not its inputs, not
its downstream consumers, not its quality gates. That's the
architectural property that makes activation cheap.
