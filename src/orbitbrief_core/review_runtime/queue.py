"""Review-queue implementations.

Two flavors today:

* :class:`InMemoryReviewQueue` — pure dict-of-tuples; ideal for
  tests + single-process orchestrators.
* :class:`JsonlReviewQueue` — appends every item + decision as
  JSON-Lines to disk for durability across orchestrator restarts.

Both implement the :class:`ReviewQueue` protocol so the
orchestrator (when it lands) can be swapped at construction time.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Protocol

from orbitbrief_core.calibrator.calibrator import CalibratedItem
from orbitbrief_core.review_runtime.decision import (
    ReviewDecision,
    ReviewItem,
    ReviewItemStatus,
)


class ReviewQueue(Protocol):
    """Minimum review-queue surface."""

    def enqueue(self, item: CalibratedItem) -> ReviewItem: ...

    def list_open(self, limit: int | None = None) -> tuple[ReviewItem, ...]: ...

    def get(self, composite_id: str) -> ReviewItem | None: ...

    def decisions_for(self, composite_id: str) -> tuple[ReviewDecision, ...]: ...

    def record_decision(self, decision: ReviewDecision) -> ReviewItem: ...


@dataclass
class InMemoryReviewQueue:
    """Process-local queue. Items append in enqueue order."""

    _items: dict[str, ReviewItem] = field(default_factory=dict)
    _decisions: dict[str, list[ReviewDecision]] = field(default_factory=dict)
    _order: list[str] = field(default_factory=list)

    def enqueue(self, item: CalibratedItem) -> ReviewItem:
        review_item = _from_calibrated(item)
        cid = review_item.composite_id
        # Idempotent on composite id; re-enqueue resets to OPEN with new payload.
        if cid not in self._items:
            self._order.append(cid)
        self._items[cid] = review_item
        return review_item

    def list_open(self, limit: int | None = None) -> tuple[ReviewItem, ...]:
        out = [
            self._items[cid]
            for cid in self._order
            if self._items[cid].status is ReviewItemStatus.OPEN
        ]
        return tuple(out if limit is None else out[:limit])

    def get(self, composite_id: str) -> ReviewItem | None:
        return self._items.get(composite_id)

    def decisions_for(self, composite_id: str) -> tuple[ReviewDecision, ...]:
        return tuple(self._decisions.get(composite_id, ()))

    def record_decision(self, decision: ReviewDecision) -> ReviewItem:
        cid = decision.composite_id
        item = self._items.get(cid)
        if item is None:
            raise KeyError(f"review item not found: {cid}")
        self._decisions.setdefault(cid, []).append(decision)
        # Mark the item as decided; preserve its original payload so
        # the training log can compare predicted vs edited.
        decided = item.model_copy(update={"status": ReviewItemStatus.DECIDED})
        self._items[cid] = decided
        return decided


@dataclass
class JsonlReviewQueue:
    """JSONL-persisted queue. Replays the file on construction.

    Two files are created in ``directory``:

    * ``review_queue.items.jsonl`` — one ``ReviewItem`` JSON per line,
      most recent re-enqueue wins on replay.
    * ``review_queue.decisions.jsonl`` — one ``ReviewDecision`` per line.

    On disk format is append-only; deletes happen at the in-memory
    layer if reviewers retract decisions in a future iteration.
    """

    directory: Path | str
    _memory: InMemoryReviewQueue = field(default_factory=InMemoryReviewQueue)

    def __post_init__(self) -> None:
        self.directory = Path(self.directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._items_path = self.directory / "review_queue.items.jsonl"
        self._decisions_path = self.directory / "review_queue.decisions.jsonl"
        self._replay()

    # ───── internal ─────

    def _replay(self) -> None:
        if self._items_path.is_file():
            for line in self._items_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                review_item = ReviewItem.model_validate_json(line)
                # Insert into the in-memory queue manually (avoids
                # re-deriving from CalibratedItem).
                cid = review_item.composite_id
                if cid not in self._memory._items:
                    self._memory._order.append(cid)
                self._memory._items[cid] = review_item
        if self._decisions_path.is_file():
            for line in self._decisions_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                decision = ReviewDecision.model_validate_json(line)
                self._memory._decisions.setdefault(
                    decision.composite_id, []
                ).append(decision)
                if decision.composite_id in self._memory._items:
                    item = self._memory._items[decision.composite_id]
                    self._memory._items[decision.composite_id] = item.model_copy(
                        update={"status": ReviewItemStatus.DECIDED}
                    )

    def _append(self, path: Path, payload: dict | str) -> None:
        line = payload if isinstance(payload, str) else json.dumps(payload)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
            if not line.endswith("\n"):
                fh.write("\n")

    # ───── ReviewQueue ─────

    def enqueue(self, item: CalibratedItem) -> ReviewItem:
        review_item = self._memory.enqueue(item)
        self._append(self._items_path, review_item.model_dump_json())
        return review_item

    def list_open(self, limit: int | None = None) -> tuple[ReviewItem, ...]:
        return self._memory.list_open(limit)

    def get(self, composite_id: str) -> ReviewItem | None:
        return self._memory.get(composite_id)

    def decisions_for(self, composite_id: str) -> tuple[ReviewDecision, ...]:
        return self._memory.decisions_for(composite_id)

    def record_decision(self, decision: ReviewDecision) -> ReviewItem:
        decided = self._memory.record_decision(decision)
        self._append(self._decisions_path, decision.model_dump_json())
        return decided


# ────────────────────────────── helpers ────────────────────────────────


def _from_calibrated(item: CalibratedItem) -> ReviewItem:
    return ReviewItem(
        ref=item.ref,
        verdict=item.verdict,
        reasons=item.reasons,
        raw_confidence=item.raw_confidence,
        calibrated_confidence=item.calibrated_confidence,
        payload=item.payload,
    )
