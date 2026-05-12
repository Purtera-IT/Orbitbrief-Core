"""Typed paths + per-stage status records for the orchestrator's output dir.

Layout::

    <out>/
      manifest.json                          # this file's serialized form
      00_envelope.json                       # canonical copy of the input
      10_pack_prior_state.json               # PackPriorState
      11_site_reality_state.json             # SiteRealityState
      20_retrieval_bundles/<pack_id>.json    # one bundle per active pack
      30_brief_state.raw.json                # planner output (pre-refiner)
      31_brief_state.refined.json            # planner output (post-refiner)
      40_brain_outputs/<pack_id>.json        # brain ScopeState per pack
      50_validations/<pack_id>.json          # ValidationReport per pack
      60_calibrations/<pack_id>.json         # CalibratorReport per pack
      70_review_queue/                       # JsonlReviewQueue dir
      71_training_records.jsonl              # JsonlTrainingLog file
      pipeline_log.json                      # one StageRecord per stage

Naming uses numeric prefixes so a directory listing reflects pipeline
order; a reviewer reading from top to bottom walks through the same
sequence the orchestrator did.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StageStatus(str, Enum):
    OK = "ok"
    SKIPPED = "skipped"
    FALLBACK = "fallback"  # ran but used the deterministic fallback path
    FAILED = "failed"


class StageRecord(BaseModel):
    """One pipeline stage's audit row."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: str
    status: StageStatus
    started_at: str
    finished_at: str
    duration_ms: int = Field(ge=0)
    artifact_path: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


@dataclass
class BriefArtifacts:
    """Filesystem handle for one engagement's artifact directory."""

    root: Path

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "20_retrieval_bundles").mkdir(parents=True, exist_ok=True)
        (self.root / "40_brain_outputs").mkdir(parents=True, exist_ok=True)
        (self.root / "50_validations").mkdir(parents=True, exist_ok=True)
        (self.root / "60_calibrations").mkdir(parents=True, exist_ok=True)
        (self.root / "70_review_queue").mkdir(parents=True, exist_ok=True)

    # ───── per-stage paths ─────

    @property
    def envelope_path(self) -> Path:
        return self.root / "00_envelope.json"

    @property
    def pack_prior_path(self) -> Path:
        return self.root / "10_pack_prior_state.json"

    @property
    def site_reality_path(self) -> Path:
        return self.root / "11_site_reality_state.json"

    def retrieval_bundle_path(self, pack_id: str) -> Path:
        return self.root / "20_retrieval_bundles" / f"{pack_id}.json"

    @property
    def brief_state_raw_path(self) -> Path:
        return self.root / "30_brief_state.raw.json"

    @property
    def brief_state_refined_path(self) -> Path:
        return self.root / "31_brief_state.refined.json"

    def brain_output_path(self, pack_id: str) -> Path:
        return self.root / "40_brain_outputs" / f"{pack_id}.json"

    def validation_path(self, pack_id: str) -> Path:
        return self.root / "50_validations" / f"{pack_id}.json"

    def calibration_path(self, pack_id: str) -> Path:
        return self.root / "60_calibrations" / f"{pack_id}.json"

    @property
    def review_queue_dir(self) -> Path:
        return self.root / "70_review_queue"

    @property
    def training_log_path(self) -> Path:
        return self.root / "71_training_records.jsonl"

    @property
    def composed_brief_path(self) -> Path:
        return self.root / "80_composed_brief.json"

    @property
    def composed_brief_markdown_path(self) -> Path:
        return self.root / "81_composed_brief.md"

    @property
    def pipeline_log_path(self) -> Path:
        return self.root / "pipeline_log.json"

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    # ───── writers ─────

    def write_json(self, path: Path, data: Any) -> Path:
        """Serialize ``data`` (dict, BaseModel, …) to ``path`` deterministically."""
        path.parent.mkdir(parents=True, exist_ok=True)
        if hasattr(data, "model_dump"):
            payload = data.model_dump(mode="json")
        elif isinstance(data, (dict, list, str, int, float, bool)) or data is None:
            payload = data
        else:
            payload = json.loads(json.dumps(data, default=str))
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False)
            + "\n",
            encoding="utf-8",
        )
        return path

    def write_pipeline_log(self, records: list[StageRecord]) -> Path:
        return self.write_json(
            self.pipeline_log_path,
            [r.model_dump(mode="json") for r in records],
        )

    def write_manifest(self, manifest: dict[str, Any]) -> Path:
        return self.write_json(self.manifest_path, manifest)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
