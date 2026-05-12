"""Pipeline smoke: every stage runs end-to-end with a scripted chat client."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from orbitbrief_core.brains.managed_services import ManagedServicesBrain
from orbitbrief_core.orchestrator import (
    BrainRegistry,
    BriefPipeline,
    PipelineConfig,
    StageStatus,
)

from tests.brains.conftest import ScriptedChatClient


def _planner_payload(envelope_dict, *, top_pack_id: str = "msp") -> str:
    """Hand-crafted BriefState payload that round-trips through validation."""
    atom_ids = [a["id"] for a in envelope_dict["atoms"]]
    return json.dumps(
        {
            "project_id": envelope_dict["project_id"],
            "compile_id": envelope_dict["compile_id"],
            "generated_at": "2026-01-01T00:00:00Z",
            "pack_activations": [
                {
                    "pack_id": top_pack_id,
                    "status": "active",
                    "confidence": 0.9,
                    "rationale": "msp keywords dense",
                }
            ],
            "sites": [],
            "claims": [
                {
                    "id": "claim_001",
                    "statement": "Endpoint monitoring across 220 devices.",
                    "supporting_atom_ids": atom_ids[:1],
                    "supporting_packet_ids": ["pkt_s1"],
                    "confidence": 0.85,
                    "pack_id": top_pack_id,
                }
            ],
            "contradictions": [],
            "review_flags": [],
            "orchestration": [
                {"action": "run_brain", "target": "managed_services", "payload": {}}
            ],
            "model_used": "qwen3:14b",
            "tier": "default",
            "escalation_log": {},
            "token_cost": {},
        }
    )


def _brain_payload(envelope_dict) -> str:
    """Hand-crafted ManagedServicesScopeState payload referencing real packets/atoms."""
    return json.dumps(
        {
            "project_id": envelope_dict["project_id"],
            "compile_id": envelope_dict["compile_id"],
            "generated_at": "2026-01-01T00:00:00Z",
            "scope_items": [
                {
                    "id": "scope_001",
                    "statement": "24x7 endpoint monitoring across 220 devices.",
                    "supporting_packet_ids": ["pkt_s1"],
                    "supporting_atom_ids": ["a1"],
                    "confidence": 0.9,
                    "category": "monitoring",
                },
                {
                    "id": "scope_002",
                    "statement": "Monthly OS and third-party patching with reboot windows.",
                    "supporting_packet_ids": ["pkt_s2"],
                    "supporting_atom_ids": ["a2"],
                    "confidence": 0.85,
                    "category": "patching",
                },
            ],
            "exclusions": [
                {
                    "id": "excl_001",
                    "statement": "Hardware replacement out of scope.",
                    "supporting_packet_ids": ["pkt_x1"],
                    "supporting_atom_ids": ["a3"],
                    "confidence": 0.95,
                    "rationale": "Explicit exclusion.",
                }
            ],
            "customer_responsibilities": [
                {
                    "id": "cust_001",
                    "statement": "Designate change-approval contact within 5 business days.",
                    "supporting_packet_ids": ["pkt_c1"],
                    "supporting_atom_ids": ["a4"],
                    "confidence": 0.9,
                    "deadline_relative": "T+5d",
                }
            ],
            "milestones": [],
            "assumptions": [
                {
                    "id": "as_001",
                    "statement": "Endpoint logs satisfy HIPAA retention (6 years).",
                    "supporting_packet_ids": ["pkt_compl1"],
                    "supporting_atom_ids": ["a6"],
                    "confidence": 0.8,
                    "risk_if_false": "Compliance gap.",
                }
            ],
            "dispatch_readiness_flags": [
                {
                    "id": "rf_001",
                    "statement": "Onsite dispatch needs prior badge approval; 48-hour lead.",
                    "supporting_packet_ids": ["pkt_site1"],
                    "supporting_atom_ids": ["a5"],
                    "confidence": 0.9,
                    "severity": "yellow",
                    "blocker_owner": "customer_security_lead",
                }
            ],
            "open_questions": [],
        }
    )


def test_pipeline_writes_every_stage_artifact(
    tmp_path: Path, msp_envelope_dict, msp_envelope_path: Path
) -> None:
    """End-to-end with a scripted chat: every per-stage artifact lands on disk."""
    chat = ScriptedChatClient(
        replies=[
            _planner_payload(msp_envelope_dict),
            _brain_payload(msp_envelope_dict),
        ]
    )
    registry = BrainRegistry()
    registry.register("msp", lambda c: ManagedServicesBrain(chat_client=c))
    pipeline = BriefPipeline(chat_client=chat, brain_registry=registry)

    out = tmp_path / "artifacts"
    result = pipeline.compile(msp_envelope_path, out_dir=out)

    # Substrate artifacts exist and are valid JSON.
    assert result.artifacts.envelope_path.is_file()
    assert result.artifacts.pack_prior_path.is_file()
    assert result.artifacts.site_reality_path.is_file()
    # The msp pack is the top one; its bundle was written.
    assert result.artifacts.retrieval_bundle_path("msp").is_file()
    # Planner + refiner artifacts.
    assert result.artifacts.brief_state_raw_path.is_file()
    assert result.artifacts.brief_state_refined_path.is_file()
    # Brain + validator + calibrator artifacts.
    assert result.artifacts.brain_output_path("msp").is_file()
    assert result.artifacts.validation_path("msp").is_file()
    assert result.artifacts.calibration_path("msp").is_file()
    # Pipeline log + manifest.
    assert result.artifacts.pipeline_log_path.is_file()
    assert result.artifacts.manifest_path.is_file()

    # No FAILED stages.
    assert not any(
        r.status is StageStatus.FAILED for r in result.stage_records
    ), [r.stage for r in result.stage_records if r.status is StageStatus.FAILED]


def test_pipeline_skips_brain_stages_without_chat_client(
    tmp_path: Path, msp_envelope_path: Path
) -> None:
    """Without a chat client, substrate runs and brain stages cleanly SKIP."""
    pipeline = BriefPipeline(chat_client=None)
    out = tmp_path / "artifacts"
    result = pipeline.compile(msp_envelope_path, out_dir=out)

    # Substrate artifacts still present.
    assert result.artifacts.pack_prior_path.is_file()
    assert result.artifacts.site_reality_path.is_file()
    # Planner + brain artifacts NOT present (those stages were skipped).
    assert not result.artifacts.brief_state_raw_path.is_file()
    # The pipeline log records the SKIPs.
    log = json.loads(result.artifacts.pipeline_log_path.read_text())
    statuses = [(r["stage"], r["status"]) for r in log]
    assert ("30_planner", "skipped") in statuses
    assert any(s.startswith("40_brain") and v == "skipped" for s, v in statuses)
    assert result.skipped_brains_no_chat is True


def test_pipeline_enqueues_review_items(
    tmp_path: Path, msp_envelope_dict, msp_envelope_path: Path
) -> None:
    """Calibrator NEEDS_REVIEW items land in the persistent review queue."""
    chat = ScriptedChatClient(
        replies=[
            _planner_payload(msp_envelope_dict),
            _brain_payload(msp_envelope_dict),
        ]
    )
    registry = BrainRegistry()
    registry.register("msp", lambda c: ManagedServicesBrain(chat_client=c))
    pipeline = BriefPipeline(chat_client=chat, brain_registry=registry)
    out = tmp_path / "artifacts"
    result = pipeline.compile(msp_envelope_path, out_dir=out)

    queue_dir = result.artifacts.review_queue_dir
    assert queue_dir.is_dir()
    items_file = queue_dir / "review_queue.items.jsonl"
    # Should have queued at least the borderline items.
    if result.queued_count > 0:
        assert items_file.is_file()
        lines = [
            line for line in items_file.read_text().splitlines() if line.strip()
        ]
        assert len(lines) == result.queued_count
