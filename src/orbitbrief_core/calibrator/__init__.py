"""Phase-6 calibrator: brain confidence → calibrated probability + verdict.

Pipeline per item:

1. :func:`extract_signals` packs every signal we have about an item
   (parser/graph/packet/claim confidences, contradiction density,
   retrieval coverage, ambiguity, example similarity, validator
   verdict) into a typed :class:`SignalVector`.
2. :class:`CalibrationModel` linearly combines those signals into a
   raw probability, then applies a Platt-scaling sigmoid fitted
   from past PM decisions. Without training data we ship a
   well-calibrated identity sigmoid that the test corpus exercises.
3. :func:`decide_verdict` maps the calibrated probability + the
   validator report to a :class:`Verdict` (``auto_accept``,
   ``needs_review``, ``reject``) plus an
   :class:`EscalationReason`.

The calibrator never mutates the brain state — it returns a list
of :class:`CalibratedItem` records that the orchestrator (or the
review_runtime) acts on.
"""
from __future__ import annotations

from orbitbrief_core.calibrator.calibrator import (
    CalibratedItem,
    Calibrator,
    CalibratorReport,
)
from orbitbrief_core.calibrator.model import (
    CalibrationModel,
    PlattCalibrator,
    SignalWeights,
)
from orbitbrief_core.calibrator.signals import SignalVector, extract_signals
from orbitbrief_core.calibrator.verdict import (
    EscalationReason,
    Verdict,
    decide_verdict,
)

__all__ = [
    "CalibratedItem",
    "CalibrationModel",
    "Calibrator",
    "CalibratorReport",
    "EscalationReason",
    "PlattCalibrator",
    "SignalVector",
    "SignalWeights",
    "Verdict",
    "decide_verdict",
    "extract_signals",
]
