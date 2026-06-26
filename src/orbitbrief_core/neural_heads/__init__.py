"""Neural heads — teacher-generated, evidence-grounded brief sections.

These layer onto the PM handoff AFTER the v46 risk_net tracks, mirroring that
pattern (``apply_X(handoff, envelope)``). Each head fills a PM_HANDOFF field with
a deal-specific, grounded section instead of the legacy template/rule output.

PRODUCTION SAFETY: the whole module is gated behind ``ORBITBRIEF_NEURAL_HEADS``.
When the flag is unset (default), :func:`apply_neural_heads` is a NO-OP and the
brief is byte-for-byte identical to today. Every head also no-ops gracefully on a
missing chat client or any internal error — a head can never block or break a
compile.

Enable with ``ORBITBRIEF_NEURAL_HEADS=1`` (and a wired chat client).
"""
from __future__ import annotations

import os
from typing import Any

from orbitbrief_core.neural_heads.exec_summary import apply_exec_summary
from orbitbrief_core.neural_heads.gap import apply_gap
from orbitbrief_core.neural_heads.risk import apply_risk
from orbitbrief_core.neural_heads.commercial import apply_commercial

__all__ = ["apply_neural_heads", "apply_exec_summary", "apply_gap", "apply_risk",
           "apply_commercial", "neural_heads_enabled"]


def neural_heads_enabled() -> bool:
    return os.environ.get("ORBITBRIEF_NEURAL_HEADS", "").strip().lower() in {"1", "true", "yes", "on"}


def apply_neural_heads(handoff: Any, envelope: dict | None, *, chat_client: Any = None) -> Any:
    """Run the enabled neural heads over ``handoff``. No-op unless the feature
    flag is on. Never raises — any head failure leaves that section untouched."""
    if not neural_heads_enabled():
        return handoff
    if not isinstance(envelope, dict):
        return handoff
    # each head is individually wrapped; a failure in one never affects the rest
    for head in (apply_exec_summary, apply_gap, apply_risk, apply_commercial):
        try:
            handoff = head(handoff, envelope, chat_client=chat_client)
        except Exception:
            pass
    return handoff
