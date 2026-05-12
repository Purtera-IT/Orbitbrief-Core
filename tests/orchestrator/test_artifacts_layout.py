"""Artifact directory layout invariants."""
from __future__ import annotations

import json
from pathlib import Path

from orbitbrief_core.orchestrator.artifacts import BriefArtifacts


def test_root_creates_subdirs(tmp_path: Path) -> None:
    art = BriefArtifacts(tmp_path / "x")
    for sub in ("20_retrieval_bundles", "40_brain_outputs", "50_validations", "60_calibrations", "70_review_queue"):
        assert (art.root / sub).is_dir(), sub


def test_per_pack_paths_are_stable(tmp_path: Path) -> None:
    art = BriefArtifacts(tmp_path / "x")
    assert art.retrieval_bundle_path("msp").name == "msp.json"
    assert art.brain_output_path("wireless").parent.name == "40_brain_outputs"
    assert art.calibration_path("msp").suffix == ".json"


def test_write_json_pretty_and_deterministic(tmp_path: Path) -> None:
    art = BriefArtifacts(tmp_path / "x")
    payload = {"b": 2, "a": 1}
    art.write_json(art.root / "demo.json", payload)
    text = (art.root / "demo.json").read_text()
    # Pretty-printed (2-space) + ends with newline.
    assert text.endswith("\n")
    assert "  " in text
    assert json.loads(text) == payload
