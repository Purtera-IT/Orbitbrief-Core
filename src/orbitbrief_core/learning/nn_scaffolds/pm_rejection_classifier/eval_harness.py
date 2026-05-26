"""Eval harness for pm_rejection_classifier — STUBBED.

Critical safety checks (blocks deployment if ANY fail):

1. **False-suppression rate < 2%** — no more than 2% of PM-would-accept
   items get auto-suppressed (P < 0.3).
2. **Blocker-severity items NEVER auto-suppressed**.
3. **Compliance / regulatory items NEVER auto-suppressed** (HIPAA, PCI,
   SOC, NDA, etc. — checked against compliance_callouts).
4. **AUC vs Platt-only baseline lift ≥ 5 pp**.
5. **Calibration ECE ≤ 0.08** in the threshold-cutting buckets.

Also tracks:

* Suppression rate (how many items get filtered)
* Auto-approval rate
* Per-domain-brain false-suppression rate (so a poorly-modeled brain
  doesn't get its outputs censored)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalResult:
    auc: float
    baseline_auc: float
    auc_lift_pp: float
    false_suppression_rate: float
    blocker_suppression_count: int                   # MUST be 0
    compliance_suppression_count: int                # MUST be 0
    ece: float
    per_brain_suppression: dict[str, float]
    blocked: bool
    block_reason: str = ""


def evaluate(model_path: str, test_jsonl: str) -> EvalResult:
    raise NotImplementedError(
        "pm_rejection_classifier eval harness is scaffolded but not connected."
    )
