"""Phase-6 review runtime: PM-facing queue + decision log.

Three concerns:

* **Queue** — a typed, append-only list of :class:`ReviewItem`
  records. The orchestrator enqueues every CalibratedItem whose
  verdict is ``needs_review`` or ``reject``. Optional JSONL
  persistence lets the queue survive process restarts.
* **Decisions** — a reviewer (or another agent acting as one)
  records :class:`ReviewDecision` records (accept / reject /
  edit) against queued items.
* **Training log** — every decision automatically emits a typed
  :class:`TrainingRecord`. That's the supervision signal a future
  calibrator + brain LoRA gets fine-tuned on.
"""
from __future__ import annotations

from orbitbrief_core.review_runtime.decision import (
    DecisionAction,
    ReviewDecision,
    ReviewItem,
    ReviewItemStatus,
    TrainingRecord,
)
from orbitbrief_core.review_runtime.queue import (
    InMemoryReviewQueue,
    JsonlReviewQueue,
    ReviewQueue,
)
from orbitbrief_core.review_runtime.training_log import (
    InMemoryTrainingLog,
    JsonlTrainingLog,
    TrainingLog,
    record_decision,
)

__all__ = [
    "DecisionAction",
    "InMemoryReviewQueue",
    "InMemoryTrainingLog",
    "JsonlReviewQueue",
    "JsonlTrainingLog",
    "ReviewDecision",
    "ReviewItem",
    "ReviewItemStatus",
    "ReviewQueue",
    "TrainingLog",
    "TrainingRecord",
    "record_decision",
]
