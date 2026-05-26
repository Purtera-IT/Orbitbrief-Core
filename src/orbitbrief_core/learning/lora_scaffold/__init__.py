"""LoRA fine-tuning scaffold — STUBBED, NOT CONNECTED TO THE LIVE PIPELINE.

See ``README.md`` in this directory for the full why / when / how.

Quick summary:

* This directory exists so a future "fine-tune a domain-specific
  Qwen3 LoRA per domain pack" effort has a place to land cleanly.
* Nothing here runs in production. The brain runners never call into
  these modules. Importing this package does nothing at runtime.
* Activation requires:
    1. ≥ 500 closed deals in the relevant domain
    2. Eval harness shows ≥ 10 % uplift vs prompt-only
    3. ML-ops infrastructure (model versioning, A/B routing, rollback)
* If those three aren't all true, stay on prompt engineering. Most
  products never need this layer.

If/when you activate this:

* :mod:`training_data_builder` produces SFT pairs from the learning ledger
* :mod:`eval_harness` runs held-out evals against a candidate adapter
* ``lora_config.yaml`` configures the actual LoRA training run
* The brain runner imports nothing from here; activation is a config
  flip in ``brains/_briefing_runner.py`` to route through a vLLM
  endpoint serving the adapter
"""
from __future__ import annotations

__all__ = [
    "IS_ACTIVE",
]

# Sentinel that downstream code can read. Always False until activation.
IS_ACTIVE: bool = False
