from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.site_schematic import build_site_schematic_bundle_from_router_input
from orbitbrief_core.parser.site_schematic.contradiction_eval import (
    load_contradiction_benchmark,
    run_contradiction_benchmark,
    validate_contradiction_benchmark,
)
from orbitbrief_core.parser.site_schematic.models import SiteSchematicReasoningFinding
from orbitbrief_core.parser.site_schematic.topology_eval import build_aligned_symbol_topology_and_contradiction_view
from orbitbrief_core.parser.site_schematic.symbols.benchmark import load_symbol_benchmark_seed


def _fixture(name: str) -> Path:
    return Path(__file__).resolve().parent / "fixtures" / name


def _bundle_with_findings(findings: tuple[SiteSchematicReasoningFinding, ...]):
    base = build_site_schematic_bundle_from_router_input(
        RouterInput(
            doc_id="contradiction-harness",
            filename="contradiction-harness.pdf",
            mime_type="application/pdf",
            metadata={"full_text": "LEGEND DATA RISER PATCH PANEL"},
        )
    )
    return replace(base, reasoning_findings=findings)


def test_contradiction_benchmark_fixture_schema_is_valid() -> None:
    fixture = load_contradiction_benchmark(_fixture("contradiction_benchmark_synthetic_conflict.json"))
    errors = validate_contradiction_benchmark(fixture)
    assert errors == []


def test_contradiction_benchmark_schema_rejects_invalid_taxonomy() -> None:
    fixture = load_contradiction_benchmark(_fixture("contradiction_benchmark_synthetic_conflict.json"))
    fixture["scenarios"][0]["taxonomy"] = "not_real_taxonomy"
    errors = validate_contradiction_benchmark(fixture)
    assert any("invalid taxonomy" in row for row in errors)


def test_contradiction_harness_scores_contradiction_and_review_lift() -> None:
    findings = (
        SiteSchematicReasoningFinding(
            finding_id="f1",
            finding_type="anchor_reconciliation",
            severity="high",
            status="contradicted",
            confidence=0.92,
            summary="Patch panel conflicts with inferred pathway relation",
            triage_bucket="contradiction_high_confidence",
            priority_score=91.0,
            evidence_symbol_instance_ids=("sym-1",),
            evidence_topology_ids=("rel-1",),
            page_indices=(2,),
            profile_ids=("detail_installation_profile",),
            metadata={
                "family": "patch_panel_row",
                "contradiction_reasons": ["detail_installation_strengthened_anchor_relation_incompatible"],
            },
        ),
        SiteSchematicReasoningFinding(
            finding_id="f2",
            finding_type="cross_page_consistency",
            severity="high",
            status="needs_review",
            confidence=0.81,
            summary="Riser endpoint family mismatch across pages",
            triage_bucket="high_priority_review",
            priority_score=72.0,
            evidence_symbol_instance_ids=("sym-2",),
            page_indices=(3,),
            profile_ids=("riser_profile",),
            metadata={"family": "riser_endpoint"},
        ),
        SiteSchematicReasoningFinding(
            finding_id="f3",
            finding_type="anchor_reconciliation",
            severity="low",
            status="supported",
            confidence=0.76,
            summary="Door contact remains consistent",
            triage_bucket="informational_supported",
            priority_score=33.0,
            evidence_symbol_instance_ids=("sym-3",),
            page_indices=(1,),
            profile_ids=("plan_body_profile",),
            metadata={"family": "door_contact_marker"},
        ),
    )
    bundle = _bundle_with_findings(findings)
    benchmark = load_contradiction_benchmark(_fixture("contradiction_benchmark_synthetic_conflict.json"))
    report = run_contradiction_benchmark(bundle=bundle, benchmark=benchmark)
    assert report["kpi_view"] == "contradiction_benchmark"
    assert report["contradiction_recall"] >= 1.0
    assert report["high_priority_review_recall"] >= 1.0
    assert report["false_contradiction_rate"] == 0.0
    assert report["evidence_completeness_rate"] >= 1.0


def test_contradiction_eval_lane_is_separate_from_symbol_topology_kpi() -> None:
    bundle = build_site_schematic_bundle_from_router_input(
        RouterInput(
            doc_id="contradiction-lane-separation",
            filename="contradiction-lane-separation.pdf",
            mime_type="application/pdf",
            metadata={"full_text": "LEGEND DATA OUTLET RISER"},
        )
    )
    symbol_benchmark = load_symbol_benchmark_seed(_fixture("symbol_benchmark_wireless.json"))
    contradiction_benchmark = load_contradiction_benchmark(_fixture("contradiction_benchmark_wireless.json"))
    report = build_aligned_symbol_topology_and_contradiction_view(
        bundle=bundle,
        benchmark=symbol_benchmark,
        contradiction_benchmark=contradiction_benchmark,
    )
    assert report["symbol_kpi"]["kpi_view"] == "canonical_symbol"
    assert report["topology_kpi"]["kpi_view"] == "additive_topology"
    assert report["contradiction_eval"]["kpi_view"] == "contradiction_benchmark"
    assert report["diagnostics"]["truth_path_unchanged"] is True


def test_contradiction_benchmark_reports_semantic_fit_mismatch_reasons() -> None:
    findings = (
        SiteSchematicReasoningFinding(
            finding_id="safe-only-1",
            finding_type="anchor_reconciliation",
            severity="low",
            status="supported",
            confidence=0.7,
            summary="Only safe signal present",
            triage_bucket="informational_supported",
            priority_score=10.0,
            evidence_symbol_instance_ids=("sym-safe",),
            page_indices=(1,),
            profile_ids=("plan_body_profile",),
            metadata={"family": "door_contact_marker"},
        ),
    )
    bundle = _bundle_with_findings(findings)
    benchmark = load_contradiction_benchmark(_fixture("contradiction_benchmark_synthetic_conflict.json"))
    report = run_contradiction_benchmark(bundle=bundle, benchmark=benchmark)
    assert "semantic_fit_summary" in report
    assert report["semantic_fit_summary"]["weak_scenario_count"] >= 1
    first = report["scenario_results"][0]
    assert "semantic_fit" in first
    assert "unmet_reasons" in first["semantic_fit"]
    assert first["semantic_fit"]["unmet_reasons"]
