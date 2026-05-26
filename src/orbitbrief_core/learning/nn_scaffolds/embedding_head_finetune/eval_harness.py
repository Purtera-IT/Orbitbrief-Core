"""Eval harness for embedding_head_finetune — STUBBED.

When active, measures:

* R@10 (recall in top-10) of accepted-packet atoms vs the PM-accepted
  ground truth, comparing head-tuned vs zero-shot embeddings
* Per-domain breakdown
* Inference latency impact (extra head pass adds ~0.5 ms)
* Distribution shift detection (KL divergence between train and prod
  embeddings)

Blocks deployment if R@10 lift < 5 pp.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalResult:
    r_at_10: float
    baseline_r_at_10: float
    r_at_10_lift_pp: float
    per_domain_r_at_10: dict[str, float]
    inference_latency_added_ms: float
    blocked: bool
    block_reason: str = ""


def evaluate(model_path: str) -> EvalResult:
    raise NotImplementedError(
        "embedding_head_finetune eval harness is scaffolded but not connected."
    )
