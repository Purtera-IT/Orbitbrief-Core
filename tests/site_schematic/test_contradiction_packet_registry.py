from __future__ import annotations

from pathlib import Path

from orbitbrief_core.parser.site_schematic.contradiction_eval import (
    build_contradiction_manifest_template,
    load_contradiction_packet_registry,
    run_contradiction_packet_registry_eval,
    summarize_contradiction_packet_activation,
    summarize_contradiction_packet_registry,
    validate_contradiction_packet_registry,
)


def _fixture(name: str) -> Path:
    return Path(__file__).resolve().parent / "fixtures" / name


def test_contradiction_packet_registry_schema_valid() -> None:
    registry = load_contradiction_packet_registry(_fixture("contradiction_packet_registry.json"))
    errors = validate_contradiction_packet_registry(registry)
    assert errors == []
    packet_ids = {row.get("packet_id") for row in registry.get("packets", [])}
    assert "detail_installation_conflict_packet_01" in packet_ids
    assert "riser_continuity_conflict_packet_01" in packet_ids
    assert "rack_equipment_role_conflict_packet_01" in packet_ids


def test_contradiction_packet_registry_eval_runs_and_separates_kpi_views() -> None:
    registry_path = _fixture("contradiction_packet_registry.json")
    registry = load_contradiction_packet_registry(registry_path)
    report = run_contradiction_packet_registry_eval(
        registry=registry,
        registry_base_dir=registry_path.parent,
    )
    assert report["kpi_view"] == "contradiction_packet_registry_eval"
    assert report["registry_packet_count"] >= 2
    assert "packet_reports" in report
    statuses = {row.get("status") for row in report["packet_reports"]}
    assert statuses & {"evaluated", "missing_pdf"}
    evaluated = [row for row in report["packet_reports"] if row.get("status") == "evaluated"]
    if evaluated:
        first = evaluated[0]
        assert first["contradiction_eval"]["kpi_view"] == "contradiction_benchmark"
        assert first["symbol_kpi"]["kpi_view"] == "canonical_symbol"
        assert first["topology_kpi"]["kpi_view"] == "additive_topology"
        assert first["diagnostics"]["truth_path_unchanged"] is True


def test_contradiction_packet_registry_supports_packet_subset_selection() -> None:
    registry_path = _fixture("contradiction_packet_registry.json")
    registry = load_contradiction_packet_registry(registry_path)
    report = run_contradiction_packet_registry_eval(
        registry=registry,
        registry_base_dir=registry_path.parent,
        selected_packet_ids=("wireless_real_packet_control",),
    )
    statuses = {row["packet_id"]: row["status"] for row in report["packet_reports"]}
    assert statuses.get("wireless_real_packet_control") in {"evaluated", "missing_pdf"}
    assert statuses.get("low_voltage_real_packet_structural") == "filtered_out"
    activation = {row["packet_id"]: row.get("activation_status") for row in report["packet_reports"]}
    assert activation.get("low_voltage_real_packet_structural") == "planned"


def test_contradiction_registry_summary_includes_coverage_and_readiness() -> None:
    registry_path = _fixture("contradiction_packet_registry.json")
    registry = load_contradiction_packet_registry(registry_path)
    summary = summarize_contradiction_packet_registry(
        registry=registry,
        registry_base_dir=registry_path.parent,
    )
    assert summary["registry_packet_count"] >= 2
    assert "status_counts" in summary
    assert "packet_type_counts" in summary
    assert "scenario_taxonomy_counts" in summary
    assert "scenario_expected_outcome_counts" in summary
    assert "detail_installation_conflict_packet_01" in set(summary.get("missing_pdf_packets", []))
    assert "riser_continuity_conflict_packet_01" in set(summary.get("missing_pdf_packets", []))
    assert "rack_equipment_role_conflict_packet_01" in set(summary.get("missing_pdf_packets", []))
    assert summary.get("packet_type_counts", {}).get("detail_installation_conflict", 0) >= 1
    assert summary.get("packet_type_counts", {}).get("riser_continuity_conflict", 0) >= 1
    assert summary.get("packet_type_counts", {}).get("rack_equipment_role_conflict", 0) >= 1
    assert summary.get("readiness_status_counts", {}).get("missing_pdf", 0) >= 3


def test_contradiction_packet_reports_include_activation_status_metadata() -> None:
    registry_path = _fixture("contradiction_packet_registry.json")
    registry = load_contradiction_packet_registry(registry_path)
    report = run_contradiction_packet_registry_eval(
        registry=registry,
        registry_base_dir=registry_path.parent,
    )
    packet_reports = report.get("packet_reports", [])
    assert packet_reports
    for row in packet_reports:
        assert "activation_status" in row
        assert "recommended_onboarding_status" in row
        assert "transition_reason" in row
    activation_summary = summarize_contradiction_packet_activation(packet_reports)
    assert "activation_status_counts" in activation_summary
    assert "active_packet_ids" in activation_summary
    assert "pending_packet_ids" in activation_summary


def test_detail_packet_missing_pdf_status_is_deterministic() -> None:
    registry_path = _fixture("contradiction_packet_registry.json")
    registry = load_contradiction_packet_registry(registry_path)
    report = run_contradiction_packet_registry_eval(
        registry=registry,
        registry_base_dir=registry_path.parent,
        selected_packet_ids=("detail_installation_conflict_packet_01",),
    )
    by_packet = {row["packet_id"]: row for row in report.get("packet_reports", [])}
    detail = by_packet["detail_installation_conflict_packet_01"]
    assert detail["status"] == "missing_pdf"
    assert detail["activation_status"] == "missing_pdf"
    assert detail["recommended_onboarding_status"] == "manifest_draft"
    assert detail["transition_reason"] == "pdf_fixture_not_found"


def test_detail_installation_manifest_has_contradiction_and_review_mix() -> None:
    manifest = _fixture("contradiction_manifest_detail_installation_conflict_packet_01.json").read_text(encoding="utf-8")
    assert "topology_backed_family_incompatibility" in manifest
    assert "\"expected_outcome\": \"contradiction\"" in manifest
    assert "\"expected_outcome\": \"high_priority_review\"" in manifest
    assert "\"expected_outcome\": \"ambiguous\"" in manifest
    assert "\"expected_outcome\": \"safe\"" in manifest


def test_riser_continuity_manifest_has_cross_page_and_structural_mix() -> None:
    manifest = _fixture("contradiction_manifest_riser_continuity_conflict_packet_01.json").read_text(encoding="utf-8")
    assert "cross_page_family_mismatch" in manifest
    assert "conflicting_structural_role_assignment" in manifest
    assert "topology_backed_family_incompatibility" in manifest
    assert "\"expected_outcome\": \"contradiction\"" in manifest
    assert "\"expected_outcome\": \"high_priority_review\"" in manifest
    assert "\"expected_outcome\": \"ambiguous\"" in manifest
    assert "\"expected_outcome\": \"safe\"" in manifest


def test_rack_equipment_manifest_has_role_conflict_mix() -> None:
    manifest = _fixture("contradiction_manifest_rack_equipment_role_conflict_packet_01.json").read_text(encoding="utf-8")
    assert "rack_vs_equipment_room_conflict" in manifest
    assert "topology_backed_family_incompatibility" in manifest
    assert "review_only_structural_ambiguity" in manifest
    assert "\"expected_outcome\": \"contradiction\"" in manifest
    assert "\"expected_outcome\": \"high_priority_review\"" in manifest
    assert "\"expected_outcome\": \"ambiguous\"" in manifest
    assert "\"expected_outcome\": \"safe\"" in manifest


def test_contradiction_manifest_template_generation_defaults_are_valid() -> None:
    template = build_contradiction_manifest_template(
        packet_id="new_detail_installation_conflict_packet",
        packet_label="New Detail Installation Conflict Packet",
    )
    assert template["packet_id"] == "new_detail_installation_conflict_packet"
    assert template["packet_level_expected"] in {"contradiction", "high_priority_review", "ambiguous", "safe"}
    assert template["packet_type"] == "detail_installation_conflict"
    assert len(template["scenarios"]) >= 2
