"""SOW completeness validator tests (generic rulebook v1).

Replaces the original PR7 narrow security-camera-only tests now
that the validator covers 29 domains × 138 checks via a YAML
rulebook. The behavior the original tests guarded is still
guarded — log retention does NOT satisfy video retention, etc. —
but the rule_id naming and result shape come from the new generic
API (``evaluate_sow_completeness`` returns ``SowCompletenessResult``).
"""
from __future__ import annotations

from orbitbrief_core.validator.sow_completeness import (
    SowCompletenessResult,
    evaluate_sow_completeness,
    load_sow_rules,
)


def test_rulebook_loads_with_expected_coverage():
    rules = load_sow_rules()
    assert (rules.get("global_checks") or [])
    assert len(rules.get("domains") or {}) >= 29
    total_checks = sum(
        len(d.get("checks") or []) for d in (rules.get("domains") or {}).values()
    )
    assert total_checks >= 100


def test_no_blockers_when_no_camera_evidence():
    """When the case has no camera vocabulary, security_camera rules
    don't contribute (their domain isn't even active)."""
    res = evaluate_sow_completeness(
        selected_pack_ids=["wireless"],
        atoms=[{"raw_text": "Cisco AP refresh and RF survey"}],
        packets=[],
        site_clusters=[],
    )
    assert isinstance(res, SowCompletenessResult)
    cam_findings = [f for f in res.findings if f.domain_id == "security_camera"]
    assert cam_findings == []


def test_camera_log_retention_does_not_satisfy_video_retention():
    """Log retention is NOT video retention. The video_retention
    blocker still fires."""
    atoms = [
        {"raw_text": "security camera, VMS maintenance, analytics"},
        {
            "raw_text": (
                "Default retention target is 365 days for admin / device / "
                "ticket / incident logs."
            )
        },
    ]
    res = evaluate_sow_completeness(
        selected_pack_ids=["security_camera"],
        atoms=atoms,
        packets=[],
        site_clusters=[],
    )
    rule_ids = {f.rule_id for f in res.findings}
    assert "security_camera.video_retention" in rule_ids
    assert "security_camera.recording_config" in rule_ids
    assert "security_camera.storage_nvr" in rule_ids


def test_video_retention_explicit_clears_finding():
    """Explicit video retention + recording config + storage model
    + codec all clear their findings."""
    atoms = [
        {"raw_text": "Genetec Security Center camera operations"},
        {
            "raw_text": (
                "Video retention SLA: 90 days continuous recording on "
                "Streamvault NVR with H.265 codec at 4096 kbps and 15 fps."
            )
        },
        {"raw_text": "Cameras are 4MP fixed dome models, in-ceiling mount."},
        {"raw_text": "Privacy mask zones approved by Facilities."},
        {"raw_text": "Camera VLAN 200 with PoE budget per port."},
        {"raw_text": "Acceptance: FoV review + stream health + uptime SLA."},
    ]
    res = evaluate_sow_completeness(
        selected_pack_ids=["security_camera"],
        atoms=atoms,
        packets=[],
        site_clusters=[],
    )
    rule_ids = {f.rule_id for f in res.findings}
    for cleared in (
        "security_camera.video_retention",
        "security_camera.recording_config",
        "security_camera.storage_nvr",
        "security_camera.resolution_bitrate_codec",
    ):
        assert cleared not in rule_ids, (cleared, rule_ids)


def test_camera_vms_operations_pack_also_triggers_camera_rules():
    res = evaluate_sow_completeness(
        selected_pack_ids=["camera_vms_operations"],
        atoms=[{"raw_text": "Genetec Security Center VMS health monitoring"}],
        packets=[],
        site_clusters=[],
    )
    rule_ids = {f.rule_id for f in res.findings}
    assert any(rid.startswith("camera_vms_operations.") for rid in rule_ids) or any(
        rid.startswith("security_camera.") for rid in rule_ids
    )


def test_evidence_inferred_domains_run_even_without_routing():
    """If selected_pack_ids = ['other'] but the atoms mention
    enough cabling vocabulary (≥4 distinct trigger alternatives:
    Cat6, drops, fluke, tia-568, faceplate, …), low-voltage cabling
    rules still fire because the domain is inferred from evidence.
    A single passing mention does NOT activate the domain — that
    was over-eager and produced 386 findings on the corpus."""
    res = evaluate_sow_completeness(
        selected_pack_ids=["other"],
        atoms=[
            {"raw_text": "186 Belden Cat6 CMP drops with RJ45 termination"},
            {"raw_text": "Fluke Versiv permanent-link tested per TIA-568.2-D"},
            {"raw_text": "Patch panel + faceplate + keystone install"},
        ],
        packets=[],
        site_clusters=[],
    )
    cabling_ids = {
        f.rule_id for f in res.findings if f.domain_id == "low_voltage_cabling"
    }
    assert cabling_ids, [f.rule_id for f in res.findings]


def test_single_incidental_mention_does_not_activate_unrelated_domain():
    """A paging onboarding doc that incidentally mentions ``fire
    alarm bypass`` does NOT activate the fire_safety domain (was
    over-eager — produced 386 findings on the 17-case corpus)."""
    res = evaluate_sow_completeness(
        selected_pack_ids=["paging_mass_notification"],
        atoms=[
            {"raw_text": "InformaCast paging deployment with bell schedule"},
            {"raw_text": "Coordinate with fire alarm bypass during cutover testing"},
        ],
        packets=[],
        site_clusters=[],
    )
    fs = {f.rule_id for f in res.findings if f.domain_id == "fire_safety"}
    assert not fs, fs


def test_status_summary_counts_findings():
    res = evaluate_sow_completeness(
        selected_pack_ids=["security_camera"],
        atoms=[{"raw_text": "Genetec Security Center cameras"}],
        packets=[],
        site_clusters=[],
    )
    d = res.to_dict()
    assert d["status"] in {"green", "yellow", "red"}
    assert d["summary"]["total_findings"] == len(res.findings)
    assert (
        d["summary"]["blocker"] + d["summary"]["warning"] + d["summary"]["info"]
        == d["summary"]["total_findings"]
    )
