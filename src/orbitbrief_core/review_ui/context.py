"""Server-side context object: queue + log + composed brief loader."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from orbitbrief_core.composer import ComposedBrief
from orbitbrief_core.review_runtime import (
    JsonlReviewQueue,
    JsonlTrainingLog,
    ReviewQueue,
    TrainingLog,
)


@dataclass
class ReviewContext:
    """All the runtime state a reviewer-UI process needs."""

    artifacts_dir: Path
    queue: ReviewQueue = field(init=False)
    training_log: TrainingLog = field(init=False)

    def __post_init__(self) -> None:
        self.artifacts_dir = Path(self.artifacts_dir)
        # The orchestrator writes the queue + log under
        # 70_review_queue/ within the artifacts dir.
        queue_dir = self.artifacts_dir / "70_review_queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        self.queue = JsonlReviewQueue(queue_dir)
        self.training_log = JsonlTrainingLog(queue_dir)

    def composed_brief(self) -> ComposedBrief | None:
        path = self.artifacts_dir / "80_composed_brief.json"
        if not path.is_file():
            return None
        return ComposedBrief.model_validate_json(path.read_text(encoding="utf-8"))

    def composed_brief_markdown(self) -> str | None:
        path = self.artifacts_dir / "81_composed_brief.md"
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

    def inspection_html(self) -> str | None:
        path = self.artifacts_dir / "91_inspection_report.html"
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

    def inspection_json(self) -> dict | None:
        path = self.artifacts_dir / "90_inspection_report.json"
        if not path.is_file():
            return None
        import json
        return json.loads(path.read_text(encoding="utf-8"))

    def manifest(self) -> dict[str, Any]:
        path = self.artifacts_dir / "manifest.json"
        if not path.is_file():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
