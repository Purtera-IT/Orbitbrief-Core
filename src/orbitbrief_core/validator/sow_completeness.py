"""SOW-completeness validator (PR 7, post-v3 review).

Rule-based check that fires AFTER the substrate is built but BEFORE
any brain runs. The intent: when an engagement is clearly camera /
VMS scope but the source artifacts don't cover the per-domain SOW
fundamentals (video retention, recording mode, storage model,
codec / bitrate / fps), surface explicit warnings instead of letting
a brain silently infer the missing facts.

This module ships with the security_camera/camera_vms_operations
ruleset; future passes can add cabling/wireless/access/etc.

Usage::

    from orbitbrief_core.validator.sow_completeness import (
        security_camera_sow_completeness,
    )

    findings = security_camera_sow_completeness(
        selected_pack_ids=list(pack_prior.selected_pack_ids
                               or [pack_prior.top_pack_id]),
        atoms=envelope["atoms"],
    )
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SowCompletenessFinding:
    """One per-rule finding from a SOW-completeness check."""

    rule_id: str
    severity: str  # blocker | warning | info
    message: str
    detail: dict[str, Any]


_CAMERA_EVIDENCE_RE = re.compile(
    r"\b(camera|vms|video management|genetec security center|axis|hanwha|"
    r"milestone|avigilon|ptz|dome|nvr)\b",
    re.I,
)

_VIDEO_RETENTION_RE = re.compile(
    r"\b(video|footage|recording|recorded video|surveillance)\b"
    r".{0,80}\b(retention|retain|days|storage)\b|"
    r"\b(retention|retain|days|storage)\b"
    r".{0,80}\b(video|footage|recording|recorded video|surveillance)\b",
    re.I,
)

_LOG_RETENTION_RE = re.compile(
    r"\b(log|logs|ticket|incident|admin|device|firewall|vpn|audit)\b"
    r".{0,80}\b(retention|retain|365 days)\b",
    re.I,
)

_RECORDING_CONFIG_RE = re.compile(
    r"\b(continuous|motion|event[-\s]?based|hybrid)\s+recording\b|"
    r"\brecording\s+(mode|config|configuration)\b",
    re.I,
)

_STORAGE_MODEL_RE = re.compile(
    r"\b(nvr|storage server|raid|streamvault|storage array|retention server|"
    r"video archive)\b",
    re.I,
)

_BITRATE_CODEC_RE = re.compile(
    r"\b(h\.?264|h\.?265|codec|bitrate|fps|frame rate|resolution)\b",
    re.I,
)


def _atom_text(atom: dict[str, Any]) -> str:
    """Concatenate the searchable text of one envelope-atom dict."""
    return " ".join(
        str(atom.get(k) or "")
        for k in ("raw_text", "text", "normalized_text", "claim", "normalized_claim")
    )


def security_camera_sow_completeness(
    *,
    selected_pack_ids: list[str],
    atoms: list[dict[str, Any]],
) -> list[SowCompletenessFinding]:
    """Run the security-camera / camera-VMS-operations completeness
    rules.

    Returns an empty list when:
    - neither security_camera nor camera_vms_operations is in
      selected_pack_ids, OR
    - no camera/VMS evidence words appear in any atom text

    Otherwise returns one finding per missing SOW fundamental
    (video retention, recording config, storage model, codec/bitrate).
    """
    packs = set(selected_pack_ids or [])
    if not ({"security_camera", "camera_vms_operations"} & packs):
        return []

    text = "\n".join(_atom_text(a) for a in atoms or ())
    if not _CAMERA_EVIDENCE_RE.search(text):
        return []

    findings: list[SowCompletenessFinding] = []

    has_video_retention = bool(_VIDEO_RETENTION_RE.search(text))
    has_log_retention = bool(_LOG_RETENTION_RE.search(text))

    if not has_video_retention:
        findings.append(
            SowCompletenessFinding(
                rule_id="security_camera.video_retention_missing",
                severity="warning",
                message=(
                    "Security camera/VMS evidence is present, but no explicit "
                    "video footage retention SLA was found. Log retention does "
                    "not satisfy video retention."
                ),
                detail={
                    "has_log_retention": has_log_retention,
                    "expected": "video/footage/recording retention days",
                },
            )
        )

    if not _RECORDING_CONFIG_RE.search(text):
        findings.append(
            SowCompletenessFinding(
                rule_id="security_camera.recording_config_missing",
                severity="warning",
                message=(
                    "Security camera/VMS evidence is present, but recording "
                    "mode is unspecified: continuous, motion, event-based, or "
                    "hybrid."
                ),
                detail={"expected": "recording mode/configuration"},
            )
        )

    if not _STORAGE_MODEL_RE.search(text):
        findings.append(
            SowCompletenessFinding(
                rule_id="security_camera.storage_model_missing",
                severity="warning",
                message=(
                    "Security camera/VMS evidence is present, but storage / "
                    "NVR / server model or retention architecture is "
                    "unspecified."
                ),
                detail={
                    "expected": "NVR/storage server/RAID/video archive model"
                },
            )
        )

    if not _BITRATE_CODEC_RE.search(text):
        findings.append(
            SowCompletenessFinding(
                rule_id="security_camera.bitrate_codec_missing",
                severity="info",
                message=(
                    "Security camera/VMS evidence is present, but bitrate, "
                    "codec, resolution, or frame-rate assumptions are not "
                    "specified."
                ),
                detail={"expected": "codec/bitrate/fps/resolution assumptions"},
            )
        )

    return findings


__all__ = ["SowCompletenessFinding", "security_camera_sow_completeness"]
