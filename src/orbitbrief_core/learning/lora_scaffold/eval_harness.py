"""Eval harness for LoRA candidates — STUBBED, not connected.

What this would do when activated:

1. Load a held-out test set of ~50 closed deals per domain (NEVER
   used in training).
2. Compile each through the candidate LoRA-served brain.
3. Compare brain outputs against the PM-accepted ground truth in
   the learning ledger.
4. Report:
   * % of PM-accepted items the LoRA also produced (recall)
   * % of LoRA-produced items the PM would have accepted (precision)
   * Net margin-projection delta (LoRA vs prompt-only)
5. Block deployment if either:
   * Recall < (prompt-only baseline - 5 pp)
   * Precision < 0.70
   * The margin delta is worse than prompt-only

Activation requires the LoRA to beat the prompt by ≥ 10 % on
recall × precision. If it doesn't, the prompt is fine — don't ship.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalResult:
    """Output shape (when active)."""

    domain: str
    n_test_deals: int
    recall_pm_accepted: float                        # 0.0 - 1.0
    precision_pm_acceptable: float                   # 0.0 - 1.0
    margin_delta_pp: float                           # LoRA - prompt-only baseline
    blocked: bool                                    # true → don't ship
    block_reason: str = ""


def evaluate(domain: str, adapter_path: str) -> EvalResult:
    """Stub. Not connected. See lora_scaffold/README.md."""
    raise NotImplementedError(
        "LoRA eval harness is scaffolded but not connected. "
        "See src/orbitbrief_core/learning/lora_scaffold/README.md."
    )
