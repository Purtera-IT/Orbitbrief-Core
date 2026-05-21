"""Training-data builder — SFT pairs from the learning ledger.

STUBBED. Activated when the corpus has ≥ 500 closed deals in a target
domain. Not wired into the live pipeline.

What this would produce (when active):

* JSONL of ``{"prompt": <brain prompt>, "completion": <accepted output>}``
  pairs derived from real PM-accepted brain outputs.
* Filtered to ``pm_decisions.action == "accepted"`` and to the target
  ``domain`` pack.
* Optionally augmented with negative examples (``action == "rejected"``)
  for RLHF-style training.

Typical sizing:

* Target ≥ 500 SFT pairs per domain pack for a useful LoRA.
* Negative examples are optional but improve specificity.

Output shape (when active)::

    {
      "prompt":     "<system + user content from brain prompt>",
      "completion": "<assistant JSON the PM accepted>",
      "metadata": {
        "case_id":    "...",
        "domain":     "wireless",
        "decided_at": "2026-08-14T...",
        "reviewer":   "..."
      }
    }
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TrainingPairBuildConfig:
    """Build-time knobs. Not used in production."""

    domain: str
    out_path: Path
    include_negatives: bool = False
    min_pairs: int = 500


def build_training_pairs(config: TrainingPairBuildConfig) -> int:
    """Stub. Returns 0 — no pairs are emitted.

    When activated, walks the learning ledger, filters by
    ``config.domain``, joins each closed deal to the brain prompts
    that produced its outputs (need to persist brain prompts +
    responses in the orchestrator for this to work), and writes SFT
    pairs to ``config.out_path``.

    Returns the count of pairs written.
    """
    # Intentionally left disconnected. See lora_scaffold/README.md.
    raise NotImplementedError(
        "LoRA training pipeline is scaffolded but not connected. "
        "See src/orbitbrief_core/learning/lora_scaffold/README.md "
        "for the activation checklist."
    )
