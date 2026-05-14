"""PR7 (post-v3 review) — security camera SOW completeness validator."""
from __future__ import annotations

from orbitbrief_core.validator.sow_completeness import (
    security_camera_sow_completeness,
)


def test_no_findings_when_no_camera_pack_selected():
    findings = security_camera_sow_completeness(
        selected_pack_ids=["wireless"],
        atoms=[{"raw_text": "Cisco AP refresh"}],
    )
    assert findings == []


def test_no_findings_when_no_camera_evidence():
    findings = security_camera_sow_completeness(
        selected_pack_ids=["security_camera"],
        atoms=[{"raw_text": "Just some prose about wireless deployments"}],
    )
    assert findings == []


def test_camera_log_retention_does_not_satisfy_video_retention():
    """Log retention is NOT video retention. The finding fires."""
    atoms = [
        {
            "raw_text": "security camera, VMS maintenance, analytics",
            "atom_type": "scope_item",
        },
        {
            "raw_text": (
                "Default retention target is 365 days for admin / device / "
                "ticket / incident logs."
            ),
            "atom_type": "constraint",
        },
    ]
    findings = security_camera_sow_completeness(
        selected_pack_ids=["security_camera"],
        atoms=atoms,
    )
    ids = {f.rule_id for f in findings}
    assert "security_camera.video_retention_missing" in ids
    assert "security_camera.recording_config_missing" in ids
    assert "security_camera.storage_model_missing" in ids


def test_video_retention_explicit_clears_finding():
    """If the evidence DOES say video retention, no
    video_retention_missing finding."""
    atoms = [
        {"raw_text": "Genetec Security Center camera operations"},
        {
            "raw_text": (
                "Video retention SLA: 90 days continuous recording on "
                "Streamvault NVR with H.265 codec at 4096 kbps and 15 fps."
            )
        },
    ]
    findings = security_camera_sow_completeness(
        selected_pack_ids=["security_camera"],
        atoms=atoms,
    )
    ids = {f.rule_id for f in findings}
    assert "security_camera.video_retention_missing" not in ids
    assert "security_camera.recording_config_missing" not in ids
    assert "security_camera.storage_model_missing" not in ids
    assert "security_camera.bitrate_codec_missing" not in ids


def test_camera_vms_operations_pack_also_triggers():
    findings = security_camera_sow_completeness(
        selected_pack_ids=["camera_vms_operations"],
        atoms=[{"raw_text": "Genetec Security Center VMS health monitoring"}],
    )
    assert any(
        f.rule_id == "security_camera.video_retention_missing" for f in findings
    )
