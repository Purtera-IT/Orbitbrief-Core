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


def test_config_only_quote_context_suppresses_install_survey_wireless_gaps():
    res = evaluate_sow_completeness(
        selected_pack_ids=["wireless"],
        atoms=[
            {"raw_text": "Cisco AP refresh for wireless access points"},
            {"raw_text": "Configure SSID and deliver RF heatmap"},
            {
                "atom_type": "task",
                "raw_text": "Ubiquiti configuration support",
                "value": {
                    "quote_context": {
                        "delivery_model": "config_only",
                        "source": "neural_head",
                        "confidence": 0.93,
                        "relation": "quote_delivery_model",
                    }
                },
            },
        ],
        packets=[],
        site_clusters=[],
        service_routing={"enabled": True, "primary": "wireless", "confidence": 0.95},
    )

    rule_ids = {f.rule_id for f in res.findings}
    assert "wireless.heatmap_deliverables" not in rule_ids
    assert "wireless.mounting_access" not in rule_ids
    assert "wireless.survey_type" not in rule_ids
    assert res.coverage["quote_context_suppressed"] > 0


def test_network_install_suppresses_ongoing_ops_network_maintenance_gaps():
    """SD-WAN / Meraki remote-hands installs keep network_maintenance routing
    but must not yellow on firmware-gold-image / OEM-TAC / VLAN-audit ops gaps."""
    res = evaluate_sow_completeness(
        selected_pack_ids=["network_maintenance", "global"],
        atoms=[
            {
                "raw_text": (
                    "Sodexo customer: Need help with Remote Hands for 13 corporate "
                    "offices Transitioning from MPLS to SDWAN Meraki MX devices "
                    "Turning on circuits at each location. Mid-august wrap-up "
                    "milestone for the engagement."
                )
            },
            {"raw_text": "Will probably not do Montreal to keep everything on US paper"},
            {"raw_text": "Maybe we can do a site survey charge for the walkthrough"},
        ],
        packets=[],
        site_clusters=[
            {"kind": "physical_site", "name": f"Site {i}", "publishable": True}
            for i in range(13)
        ],
        service_routing={
            "enabled": True,
            "primary": "network_maintenance",
            "confidence": 0.78,
        },
        include_global=True,
    )
    rule_ids = {f.rule_id for f in res.findings}
    assert "network_maintenance.firmware_baseline_missing" not in rule_ids
    assert "network_maintenance.oem_tac_escalation_missing" not in rule_ids
    assert "network_maintenance.vlan_port_audit_cadence_missing" not in rule_ids
    assert "network_maintenance.coverage_tier" not in rule_ids
    assert "network_maintenance.port_vlan_wan" not in rule_ids
    assert "network_maintenance.device_inventory" not in rule_ids
    assert res.coverage.get("network_install_ops_suppressed", 0) > 0
    # Boundary + survey-charge language should clear the two global warnings.
    assert "global.explicit_exclusions" not in rule_ids
    assert "global.commercial_structure" not in rule_ids
    assert all(f.severity != "warning" for f in res.findings if f.domain_id == "network_maintenance")
    # Info-only leftovers (assumptions / failover) must not yellow the handoff.
    assert res.status == "green"


def test_trusted_wireless_primary_without_anchors_is_dropped():
    """UPS/APC battery installs must not keep wireless SOW blockers active
    just because the neural router head confidently mis-embeds them."""
    res = evaluate_sow_completeness(
        selected_pack_ids=["wireless", "electrical", "commercial"],
        atoms=[
            {
                "atom_type": "task",
                "raw_text": (
                    "Install one (1) customer provided battery pack, model "
                    "APCRBC140, into the applicable UPS."
                ),
            },
            {
                "atom_type": "scope_item",
                "raw_text": "Customer provides the APCRBC140 battery pack at site.",
            },
        ],
        packets=[],
        site_clusters=[{"kind": "physical_site", "canonical_name": "tampa fl 33602"}],
        service_routing={"enabled": True, "primary": "wireless", "confidence": 0.92},
    )
    wireless_findings = [f for f in res.findings if f.domain_id == "wireless"]
    assert wireless_findings == []
    assert "wireless" not in res.active_domain_ids
    rule_ids = {f.rule_id for f in res.findings}
    assert "wireless.ap_count_model" not in rule_ids
    assert "wireless.ssid_vlan_auth_matrix_missing" not in rule_ids


def test_professional_services_dropped_without_advisory_anchors():
    """Generic install SOW language (requirements / Validate deliverables)
    must not activate professional_services or its deliverables blocker."""
    res = evaluate_sow_completeness(
        selected_pack_ids=["professional_services", "electrical", "commercial"],
        atoms=[
            {
                "atom_type": "task",
                "raw_text": (
                    "Install one (1) customer provided battery pack, model "
                    "APCRBC140, into the applicable UPS."
                ),
            },
            {
                "atom_type": "scope_item",
                "raw_text": "Validate deliverables with Customer",
            },
            {
                "atom_type": "scope_item",
                "raw_text": "Provide any specific installation requirements as needed.",
            },
            {
                "atom_type": "deliverable",
                "raw_text": "Photos of new device installed",
            },
        ],
        packets=[],
        site_clusters=[{"kind": "physical_site", "canonical_name": "tampa fl 33602"}],
        service_routing={
            "enabled": True,
            "primary": None,
            "abstained": True,
            "abstain_reason": "missing_evidence_anchors",
            "confidence": 0.92,
        },
    )
    assert "professional_services" not in res.active_domain_ids
    rule_ids = {f.rule_id for f in res.findings}
    assert "professional_services.deliverables" not in rule_ids


def test_professional_services_deliverable_atom_satisfies_blocker():
    """When PS is legitimately active, a typed deliverable atom clears the
    deliverables blocker even without the word 'deliverable' in prose."""
    res = evaluate_sow_completeness(
        selected_pack_ids=["professional_services"],
        atoms=[
            {
                "atom_type": "scope_item",
                "raw_text": (
                    "Professional services discovery workshop and future-state "
                    "assessment engagement for the campus network."
                ),
            },
            {
                "atom_type": "deliverable",
                "raw_text": "Photos of new device installed",
            },
        ],
        packets=[],
        site_clusters=[],
    )
    assert "professional_services" in res.active_domain_ids
    rule_ids = {f.rule_id for f in res.findings}
    assert "professional_services.deliverables" not in rule_ids
