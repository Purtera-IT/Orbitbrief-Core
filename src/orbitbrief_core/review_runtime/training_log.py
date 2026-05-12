"""Training-data log: every reviewer decision becomes one record.

Cold-start: an in-memory list and a JSONL persister. Both
implement the :class:`TrainingLog` protocol so the orchestrator
can swap them at construction. Records are append-only; we never
overwrite a past judgement.

The single entry point :func:`record_decision` ties a reviewer's
:class:`ReviewDecision` back to the original :class:`ReviewItem`
and emits a fully-formed :class:`TrainingRecord`. The
calibrator's :meth:`fit_platt` (Phase 6+) and the brain's LoRA
fine-tune (Phase 6+) both read from logs of these records.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Protocol

from orbitbrief_core.review_runtime.decision import (
    DecisionAction,
    ReviewDecision,
    ReviewItem,
    TrainingRecord,
)


class TrainingLog(Protocol):
    """Append-only log of training-grade decision records."""

    def append(self, record: TrainingRecord) -> None: ...

    def all(self) -> tuple[TrainingRecord, ...]: ...


@dataclass
class InMemoryTrainingLog:
    """List-backed log; tests + single-process orchestrators."""

    _records: list[TrainingRecord] = field(default_factory=list)

    def append(self, record: TrainingRecord) -> None:
        self._records.append(record)

    def all(self) -> tuple[TrainingRecord, ...]:
        return tuple(self._records)


@dataclass
class JsonlTrainingLog:
    """JSONL-persisted log; replays on construction.

    File: ``<directory>/training_records.jsonl``.
    """

    directory: Path | str
    _records: list[TrainingRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.directory = Path(self.directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._path = self.directory / "training_records.jsonl"
        if self._path.is_file():
            for line in self._path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                self._records.append(TrainingRecord.model_validate_json(line))

    def append(self, record: TrainingRecord) -> None:
        self._records.append(record)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(record.model_dump_json())
            fh.write("\n")

    def all(self) -> tuple[TrainingRecord, ...]:
        return tuple(self._records)


def record_decision(
    *,
    item: ReviewItem,
    decision: ReviewDecision,
    log: TrainingLog,
) -> TrainingRecord:
    """Bind a :class:`ReviewDecision` to its source item and persist a training record."""
    if item.composite_id != decision.composite_id:
        raise ValueError(
            f"item/decision composite_id mismatch: "
            f"{item.composite_id} vs {decision.composite_id}"
        )
    record = TrainingRecord(
        composite_id=item.composite_id,
        brain=item.ref.brain,
        section=item.ref.section,
        project_id=item.ref.project_id,
        compile_id=item.ref.compile_id,
        predicted_payload=item.payload,
        predicted_calibrated_confidence=item.calibrated_confidence,
        predicted_raw_confidence=item.raw_confidence,
        predicted_verdict=item.verdict,
        reviewer_action=decision.action,
        reviewer_notes=decision.notes,
        edited_payload=decision.edited_payload,
        decided_by=decision.decided_by,
        decided_at=decision.decided_at,
        accepted=decision.action in (DecisionAction.ACCEPT, DecisionAction.EDIT),
    )
    log.append(record)
    return record
