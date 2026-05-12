"""End-to-end against a live Ollama Qwen3-14B and a real parser-os envelope.

Uses the same ``mixed_envelope`` fixture Phase 1+2 already build
(parser-os COPPER_001 dossier compiled live). Skipped if Ollama
isn't reachable or parser-os corpus isn't present.

This is the strongest "is it MVP yet?" check we can run locally —
if it goes green, we have a real pipeline producing a real
reviewable brief from real artifacts.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from orbitbrief_core.inference.client import OpenAIChatClient
from orbitbrief_core.orchestrator import (
    BrainRegistry,
    BriefPipeline,
    PipelineConfig,
    StageStatus,
)


OLLAMA_BASE = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
QWEN3_CHAT_MODEL = os.environ.get("QWEN3_CHAT_MODEL", "qwen3:14b")


def _ollama_reachable() -> bool:
    import urllib.request

    try:
        urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=2.0).read(8)
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not _ollama_reachable(),
        reason=f"Ollama not reachable at {OLLAMA_BASE}",
    ),
]


def test_pipeline_runs_end_to_end_on_real_envelope(
    tmp_path: Path, mixed_envelope_path: Path
) -> None:
    """Full Phase 0–6 pipeline on a real parser-os envelope; no FAILED stages."""
    chat = OpenAIChatClient(base_url=OLLAMA_BASE, timeout_s=240.0)
    pipeline = BriefPipeline(
        chat_client=chat,
        planner_default_model=QWEN3_CHAT_MODEL,
        planner_escalated_model=QWEN3_CHAT_MODEL,  # avoid 32B for the smoke
        pack_prior_chat_model=QWEN3_CHAT_MODEL,
        site_reality_chat_model=QWEN3_CHAT_MODEL,
        config=PipelineConfig(persist_review_queue=True),
    )

    out_dir = tmp_path / "artifacts"
    result = pipeline.compile(mixed_envelope_path, out_dir=out_dir)

    failed = [r for r in result.stage_records if r.status is StageStatus.FAILED]
    assert not failed, [(r.stage, r.detail) for r in failed]

    # Substrate must be there.
    assert result.artifacts.envelope_path.is_file()
    assert result.artifacts.pack_prior_path.is_file()
    assert result.artifacts.site_reality_path.is_file()
    # Planner must have produced (or fallen back to) a BriefState.
    assert result.artifacts.brief_state_raw_path.is_file()
    assert result.artifacts.brief_state_refined_path.is_file()

    # Manifest is well-formed.
    manifest = json.loads(result.artifacts.manifest_path.read_text())
    assert manifest["skipped_brains_no_chat"] is False
    assert manifest["envelope_path"] == str(mixed_envelope_path)
