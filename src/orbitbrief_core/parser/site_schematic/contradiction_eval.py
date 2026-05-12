from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.site_schematic.core import build_site_schematic_bundle_from_router_input
from orbitbrief_core.parser.site_schematic.models import SiteSchematicBundle, SiteSchematicReasoningFinding
from orbitbrief_core.parser.site_schematic.symbols.benchmark import (
    load_symbol_benchmark_seed,
    run_symbol_benchmark,
    run_topology_benchmark,
)

_ALLOWED_EXPECTED_OUTCOMES = {"contradiction", "high_priority_review", "ambiguous", "safe"}
_ALLOWED_TAXONOMY = {
    "legend_vs_detail_conflict",
    "detail_vs_riser_conflict",
    "rack_vs_equipment_room_conflict",
    "topology_backed_family_incompatibility",
    "cross_page_family_mismatch",
    "conflicting_structural_role_assignment",
    "grounding_vs_requirement_conflict",
    "anchor_context_incompatibility",
    "review_only_structural_ambiguity",
    "safe_no_issue",
}
_HIGH_PRIORITY_BUCKETS = {"high_priority_review", "contradiction_high_confidence"}
_ALLOWED_PACKET_TYPES = {
    "detail_installation_conflict",
    "riser_continuity_conflict",
    "rack_equipment_role_conflict",
    "mixed_structural_conflict",
    "production_control",
}
_ALLOWED_ONBOARDING_STATUS = {
    "planned",
    "manifest_draft",
    "fixture_ready",
    "fixture_validated",
    "evaluated",
    "needs_manifest_revision",
    "missing_pdf",
}


@dataclass(frozen=True, slots=True)
class ContradictionScenario:
    scenario_id: str
    taxonomy: str
    expected_outcome: str
    families: tuple[str, ...] = ()
    profiles: tuple[str, ...] = ()
    page_indices: tuple[int, ...] = ()
    notes: str = ""
    required_evidence_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ContradictionBenchmark:
    benchmark_id: str
    packet_id: str
    packet_label: str
    packet_level_expected: str
    expected_contradiction_families: tuple[str, ...]
    expected_review_only_families: tuple[str, ...]
    expected_safe_families: tuple[str, ...]
    scenarios: tuple[ContradictionScenario, ...]


@dataclass(frozen=True, slots=True)
class ContradictionPacketRegistryEntry:
    packet_id: str
    packet_label: str
    pdf_path: str
    contradiction_manifest_path: str
    symbol_benchmark_path: str = ""
    packet_type: str = ""
    contradiction_richness: str = ""
    onboarding_status: str = "planned"
    priority: int = 100
    expected_profile_coverage: tuple[str, ...] = ()
    expected_family_coverage: tuple[str, ...] = ()
    enabled: bool = True
    metadata: Mapping[str, Any] = None


def _normalized_tuple(values: Any) -> tuple[str, ...]:
    if not isinstance(values, list):
        return ()
    output: list[str] = []
    for row in values:
        value = str(row).strip()
        if value:
            output.append(value)
    return tuple(output)


def _normalized_int_tuple(values: Any) -> tuple[int, ...]:
    if not isinstance(values, list):
        return ()
    output: list[int] = []
    for row in values:
        try:
            output.append(int(row))
        except (TypeError, ValueError):
            continue
    return tuple(output)


def load_contradiction_benchmark(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_contradiction_packet_registry(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_contradiction_benchmark(benchmark: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(benchmark, Mapping):
        return ["benchmark must be an object"]
    for key in ("benchmark_id", "packet_id", "packet_label", "packet_level_expected", "scenarios"):
        if not benchmark.get(key):
            errors.append(f"missing {key}")
    packet_level = str(benchmark.get("packet_level_expected", "")).strip()
    if packet_level and packet_level not in _ALLOWED_EXPECTED_OUTCOMES:
        errors.append(f"invalid packet_level_expected: {packet_level}")
    scenarios = benchmark.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        errors.append("scenarios must be a non-empty list")
        return errors
    required = {"scenario_id", "taxonomy", "expected_outcome"}
    for idx, row in enumerate(scenarios, start=1):
        if not isinstance(row, Mapping):
            errors.append(f"scenario#{idx} must be an object")
            continue
        missing = sorted(required - set(row.keys()))
        if missing:
            errors.append(f"scenario#{idx} missing fields: {', '.join(missing)}")
            continue
        taxonomy = str(row.get("taxonomy", "")).strip()
        expected_outcome = str(row.get("expected_outcome", "")).strip()
        if taxonomy not in _ALLOWED_TAXONOMY:
            errors.append(f"scenario#{idx} has invalid taxonomy: {taxonomy}")
        if expected_outcome not in _ALLOWED_EXPECTED_OUTCOMES:
            errors.append(f"scenario#{idx} has invalid expected_outcome: {expected_outcome}")
    return errors


def validate_contradiction_packet_registry(registry: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(registry, Mapping):
        return ["registry must be an object"]
    packets = registry.get("packets")
    if not isinstance(packets, list) or not packets:
        return ["registry.packets must be a non-empty list"]
    required = {"packet_id", "packet_label", "pdf_path", "contradiction_manifest_path"}
    seen_packet_ids: set[str] = set()
    for idx, row in enumerate(packets, start=1):
        if not isinstance(row, Mapping):
            errors.append(f"packet#{idx} must be an object")
            continue
        missing = sorted(required - set(row.keys()))
        if missing:
            errors.append(f"packet#{idx} missing fields: {', '.join(missing)}")
            continue
        packet_id = str(row.get("packet_id", "")).strip()
        if not packet_id:
            errors.append(f"packet#{idx} has empty packet_id")
        elif packet_id in seen_packet_ids:
            errors.append(f"packet#{idx} duplicates packet_id: {packet_id}")
        else:
            seen_packet_ids.add(packet_id)
        packet_type = str(row.get("packet_type", "")).strip()
        if packet_type and packet_type not in _ALLOWED_PACKET_TYPES:
            errors.append(f"packet#{idx} has unsupported packet_type: {packet_type}")
        status = str(row.get("onboarding_status", "planned")).strip() or "planned"
        if status not in _ALLOWED_ONBOARDING_STATUS:
            errors.append(f"packet#{idx} has unsupported onboarding_status: {status}")
        priority = row.get("priority", 100)
        try:
            int(priority)
        except (TypeError, ValueError):
            errors.append(f"packet#{idx} has non-integer priority")
    return errors


def parse_contradiction_packet_registry(registry: Mapping[str, Any]) -> tuple[ContradictionPacketRegistryEntry, ...]:
    errors = validate_contradiction_packet_registry(registry)
    if errors:
        raise ValueError("; ".join(errors))
    output: list[ContradictionPacketRegistryEntry] = []
    for row in registry.get("packets", []):
        output.append(
            ContradictionPacketRegistryEntry(
                packet_id=str(row.get("packet_id", "")).strip(),
                packet_label=str(row.get("packet_label", "")).strip(),
                pdf_path=str(row.get("pdf_path", "")).strip(),
                contradiction_manifest_path=str(row.get("contradiction_manifest_path", "")).strip(),
                symbol_benchmark_path=str(row.get("symbol_benchmark_path", "")).strip(),
                packet_type=str(row.get("packet_type", "")).strip(),
                contradiction_richness=str(row.get("contradiction_richness", "")).strip(),
                onboarding_status=str(row.get("onboarding_status", "planned")).strip() or "planned",
                priority=int(row.get("priority", 100)),
                expected_profile_coverage=_normalized_tuple(row.get("expected_profile_coverage")),
                expected_family_coverage=_normalized_tuple(row.get("expected_family_coverage")),
                enabled=bool(row.get("enabled", True)),
                metadata=dict(row.get("metadata", {})) if isinstance(row.get("metadata"), Mapping) else {},
            )
        )
    return tuple(output)


def parse_contradiction_benchmark(benchmark: Mapping[str, Any]) -> ContradictionBenchmark:
    errors = validate_contradiction_benchmark(benchmark)
    if errors:
        raise ValueError("; ".join(errors))
    scenarios = tuple(
        ContradictionScenario(
            scenario_id=str(row.get("scenario_id", "")).strip(),
            taxonomy=str(row.get("taxonomy", "")).strip(),
            expected_outcome=str(row.get("expected_outcome", "")).strip(),
            families=_normalized_tuple(row.get("families")),
            profiles=_normalized_tuple(row.get("profiles")),
            page_indices=_normalized_int_tuple(row.get("page_indices")),
            notes=str(row.get("notes", "")).strip(),
            required_evidence_fields=_normalized_tuple(row.get("required_evidence_fields")),
        )
        for row in benchmark.get("scenarios", [])
    )
    return ContradictionBenchmark(
        benchmark_id=str(benchmark.get("benchmark_id", "")).strip(),
        packet_id=str(benchmark.get("packet_id", "")).strip(),
        packet_label=str(benchmark.get("packet_label", "")).strip(),
        packet_level_expected=str(benchmark.get("packet_level_expected", "")).strip(),
        expected_contradiction_families=_normalized_tuple(benchmark.get("expected_contradiction_families")),
        expected_review_only_families=_normalized_tuple(benchmark.get("expected_review_only_families")),
        expected_safe_families=_normalized_tuple(benchmark.get("expected_safe_families")),
        scenarios=scenarios,
    )


def _taxonomy_tags_for_finding(row: SiteSchematicReasoningFinding) -> set[str]:
    metadata = dict(row.metadata or {})
    reasons = {str(reason).strip() for reason in metadata.get("contradiction_reasons", []) if str(reason).strip()}
    tags: set[str] = set()
    if row.finding_type == "cross_page_consistency":
        tags.add("cross_page_family_mismatch")
    if row.finding_type == "anchor_reconciliation":
        tags.add("anchor_context_incompatibility")
    if row.finding_type == "topology_continuity_review":
        tags.add("review_only_structural_ambiguity")
    if any("detail_installation" in reason for reason in reasons) or any("pathway_attachment" in reason for reason in reasons):
        tags.add("legend_vs_detail_conflict")
    if any("riser" in reason for reason in reasons):
        tags.add("detail_vs_riser_conflict")
    if any("rack" in reason or "equipment" in reason for reason in reasons):
        tags.add("rack_vs_equipment_room_conflict")
    if any("incompatible" in reason for reason in reasons):
        tags.add("topology_backed_family_incompatibility")
        tags.add("conflicting_structural_role_assignment")
    if any("requirement" in reason or "legend" in reason for reason in reasons):
        tags.add("grounding_vs_requirement_conflict")
    if row.status == "supported":
        tags.add("safe_no_issue")
    return tags or {"review_only_structural_ambiguity"}


def _family_for_finding(row: SiteSchematicReasoningFinding) -> str:
    metadata = dict(row.metadata or {})
    return str(metadata.get("family", "")).strip() or str(metadata.get("detector_class_id", "")).strip()


def _matches_scenario(row: SiteSchematicReasoningFinding, scenario: ContradictionScenario) -> bool:
    tags = _taxonomy_tags_for_finding(row)
    if scenario.taxonomy not in tags:
        return False
    family = _family_for_finding(row)
    if scenario.families and family and family not in set(scenario.families):
        return False
    if scenario.profiles and not set(row.profile_ids) & set(scenario.profiles):
        return False
    if scenario.page_indices and not set(row.page_indices) & set(scenario.page_indices):
        return False
    return True


def _rows_for_taxonomy(rows: Iterable[SiteSchematicReasoningFinding], taxonomy: str) -> list[SiteSchematicReasoningFinding]:
    needle = str(taxonomy).strip()
    return [row for row in rows if needle in _taxonomy_tags_for_finding(row)]


def _evidence_complete(row: SiteSchematicReasoningFinding, required_fields: Iterable[str]) -> bool:
    metadata = dict(row.metadata or {})
    for field_name in required_fields:
        key = str(field_name).strip()
        if not key:
            continue
        if key == "evidence_node_ids" and not row.evidence_node_ids:
            return False
        if key == "evidence_edge_ids" and not row.evidence_edge_ids:
            return False
        if key == "evidence_symbol_instance_ids" and not row.evidence_symbol_instance_ids:
            return False
        if key == "evidence_topology_ids" and not row.evidence_topology_ids:
            return False
        if key == "profile_ids" and not row.profile_ids:
            return False
        if key == "page_indices" and not row.page_indices:
            return False
        if key.startswith("metadata.") and not metadata.get(key.split(".", 1)[1]):
            return False
    return True


def run_contradiction_benchmark(
    *,
    bundle: SiteSchematicBundle,
    benchmark: Mapping[str, Any],
) -> dict[str, Any]:
    manifest = parse_contradiction_benchmark(benchmark)
    findings = tuple(bundle.reasoning_findings)
    family_counter = Counter(_family_for_finding(row) for row in findings if _family_for_finding(row))
    profile_counter = Counter(profile for row in findings for profile in row.profile_ids if profile)
    page_counter = Counter(page for row in findings for page in row.page_indices)
    scenario_results: list[dict[str, Any]] = []
    expected_contradictions = 0
    recovered_contradictions = 0
    expected_high_priority = 0
    recovered_high_priority = 0
    false_contradictions = 0
    abstained = 0
    contradiction_by_family: Counter[str] = Counter()
    contradiction_by_profile: Counter[str] = Counter()
    evidence_complete_hits = 0
    evidence_total_checks = 0
    weak_scenario_ids: list[str] = []
    for scenario in manifest.scenarios:
        taxonomy_rows = _rows_for_taxonomy(findings, scenario.taxonomy)
        family_scoped = [
            row
            for row in taxonomy_rows
            if not scenario.families or not _family_for_finding(row) or _family_for_finding(row) in set(scenario.families)
        ]
        profile_scoped = [
            row for row in family_scoped if not scenario.profiles or set(row.profile_ids) & set(scenario.profiles)
        ]
        scoped = [row for row in profile_scoped if not scenario.page_indices or set(row.page_indices) & set(scenario.page_indices)]
        contradiction_rows = [row for row in scoped if row.status == "contradicted"]
        high_priority_rows = [row for row in scoped if row.triage_bucket in _HIGH_PRIORITY_BUCKETS or row.status == "contradicted"]
        ambiguous_rows = [row for row in scoped if row.status in {"needs_review", "ambiguous", "abstained"}]
        if scenario.expected_outcome == "contradiction":
            expected_contradictions += 1
            if contradiction_rows:
                recovered_contradictions += 1
            elif ambiguous_rows:
                abstained += 1
        elif scenario.expected_outcome == "high_priority_review":
            expected_high_priority += 1
            if high_priority_rows:
                recovered_high_priority += 1
            elif ambiguous_rows:
                abstained += 1
        elif scenario.expected_outcome == "safe":
            if contradiction_rows:
                false_contradictions += 1
        for row in contradiction_rows:
            family = _family_for_finding(row) or "unknown"
            contradiction_by_family[family] += 1
            for profile in row.profile_ids:
                if profile:
                    contradiction_by_profile[profile] += 1
        matched_rows = contradiction_rows or high_priority_rows or ambiguous_rows or scoped
        required = tuple(scenario.required_evidence_fields)
        if required and matched_rows:
            evidence_total_checks += len(matched_rows)
            evidence_complete_hits += sum(1 for row in matched_rows if _evidence_complete(row, required))
        status = "unmatched"
        if scenario.expected_outcome == "contradiction":
            status = "matched_contradiction" if contradiction_rows else ("abstained" if ambiguous_rows else "missed")
        elif scenario.expected_outcome == "high_priority_review":
            status = "matched_high_priority" if high_priority_rows else ("abstained" if ambiguous_rows else "missed")
        elif scenario.expected_outcome == "ambiguous":
            status = "matched_ambiguous" if ambiguous_rows else "missed"
        elif scenario.expected_outcome == "safe":
            status = "safe_confirmed" if not contradiction_rows and not high_priority_rows else "unexpected_escalation"
        unmet_reasons: list[str] = []
        if status in {"missed", "unmatched"}:
            if not taxonomy_rows:
                unmet_reasons.append("taxonomy_not_observed_in_packet")
            elif scenario.families and not family_scoped and all(family_counter.get(fam, 0) == 0 for fam in scenario.families):
                unmet_reasons.append("wrong_family_or_missing_family_grounding")
            elif scenario.profiles and not profile_scoped and all(profile_counter.get(profile, 0) == 0 for profile in scenario.profiles):
                unmet_reasons.append("wrong_profile_or_profile_not_observed")
            elif scenario.page_indices and not scoped and all(page_counter.get(page, 0) == 0 for page in scenario.page_indices):
                unmet_reasons.append("wrong_page_scope")
            else:
                unmet_reasons.append("outcome_not_supported_by_current_findings")
        if required and matched_rows and any(not _evidence_complete(row, required) for row in matched_rows):
            unmet_reasons.append("insufficient_evidence_requirements")
        if status in {"missed", "unexpected_escalation"}:
            weak_scenario_ids.append(scenario.scenario_id)
        scenario_results.append(
            {
                "scenario_id": scenario.scenario_id,
                "taxonomy": scenario.taxonomy,
                "expected_outcome": scenario.expected_outcome,
                "status": status,
                "matched_finding_ids": [row.finding_id for row in matched_rows[:16]],
                "matched_count": len(matched_rows),
                "contradiction_count": len(contradiction_rows),
                "high_priority_count": len(high_priority_rows),
                "ambiguous_count": len(ambiguous_rows),
                "families": list(scenario.families),
                "profiles": list(scenario.profiles),
                "page_indices": list(scenario.page_indices),
                "semantic_fit": {
                    "taxonomy_candidate_count": len(taxonomy_rows),
                    "family_candidate_count": len(family_scoped),
                    "profile_candidate_count": len(profile_scoped),
                    "final_scope_candidate_count": len(scoped),
                    "unmet_reasons": unmet_reasons,
                },
            }
        )
    actual_contradiction_scenarios = sum(1 for row in scenario_results if row.get("contradiction_count", 0) > 0)
    actual_high_priority_scenarios = sum(1 for row in scenario_results if row.get("high_priority_count", 0) > 0)
    contradiction_precision = recovered_contradictions / max(1, actual_contradiction_scenarios)
    contradiction_recall = recovered_contradictions / max(1, expected_contradictions)
    high_priority_recall = recovered_high_priority / max(1, expected_high_priority)
    false_contradiction_rate = max(0, actual_contradiction_scenarios - recovered_contradictions) / max(1, actual_contradiction_scenarios)
    return {
        "kpi_view": "contradiction_benchmark",
        "benchmark_id": manifest.benchmark_id,
        "packet_id": manifest.packet_id,
        "packet_label": manifest.packet_label,
        "packet_level_expected": manifest.packet_level_expected,
        "scenario_count": len(manifest.scenarios),
        "contradiction_recall": round(contradiction_recall, 4),
        "contradiction_precision": round(contradiction_precision, 4),
        "high_priority_review_recall": round(high_priority_recall, 4),
        "false_contradiction_rate": round(false_contradiction_rate, 4),
        "abstain_rate": round(abstained / max(1, expected_contradictions + expected_high_priority), 4),
        "actual_contradiction_scenarios": actual_contradiction_scenarios,
        "actual_high_priority_scenarios": actual_high_priority_scenarios,
        "contradiction_by_family": dict(sorted(contradiction_by_family.items(), key=lambda item: (-item[1], item[0]))),
        "contradiction_by_profile": dict(sorted(contradiction_by_profile.items(), key=lambda item: (-item[1], item[0]))),
        "family_finding_counts": dict(sorted(family_counter.items(), key=lambda item: (-item[1], item[0]))),
        "profile_finding_counts": dict(sorted(profile_counter.items(), key=lambda item: (-item[1], item[0]))),
        "evidence_completeness_rate": round(evidence_complete_hits / max(1, evidence_total_checks), 4),
        "semantic_fit_summary": {
            "weak_scenario_ids": weak_scenario_ids,
            "weak_scenario_count": len(weak_scenario_ids),
        },
        "scenario_results": scenario_results,
        "expected_sets": {
            "expected_contradiction_families": list(manifest.expected_contradiction_families),
            "expected_review_only_families": list(manifest.expected_review_only_families),
            "expected_safe_families": list(manifest.expected_safe_families),
        },
    }


def _resolve_path(base_dir: Path, relative_or_abs: str) -> Path:
    candidate = Path(relative_or_abs)
    if candidate.is_absolute():
        return candidate
    return (base_dir / candidate).resolve()


def _derive_manifest_alignment(contradiction_eval: Mapping[str, Any]) -> dict[str, Any]:
    scenario_results = contradiction_eval.get("scenario_results", [])
    if not isinstance(scenario_results, list):
        scenario_results = []
    non_safe = [row for row in scenario_results if str(row.get("expected_outcome", "")).strip() != "safe"]
    matched_non_safe = [
        row
        for row in non_safe
        if str(row.get("status", "")).strip() in {"matched_contradiction", "matched_high_priority", "matched_ambiguous", "abstained"}
    ]
    safe_rows = [row for row in scenario_results if str(row.get("expected_outcome", "")).strip() == "safe"]
    safe_escalations = [
        row for row in safe_rows if str(row.get("status", "")).strip() == "unexpected_escalation"
    ]
    non_safe_match_rate = len(matched_non_safe) / max(1, len(non_safe))
    semantic_fit_summary = contradiction_eval.get("semantic_fit_summary", {})
    weak_scenario_count = 0
    if isinstance(semantic_fit_summary, Mapping):
        try:
            weak_scenario_count = int(semantic_fit_summary.get("weak_scenario_count", 0))
        except (TypeError, ValueError):
            weak_scenario_count = 0
    needs_manifest_revision = bool(safe_escalations) or (bool(non_safe) and not matched_non_safe) or weak_scenario_count > 0
    return {
        "non_safe_scenario_count": len(non_safe),
        "matched_non_safe_scenario_count": len(matched_non_safe),
        "safe_scenario_count": len(safe_rows),
        "safe_unexpected_escalation_count": len(safe_escalations),
        "non_safe_match_rate": round(non_safe_match_rate, 4),
        "weak_scenario_count": weak_scenario_count,
        "weak_scenario_ids": list(semantic_fit_summary.get("weak_scenario_ids", []))
        if isinstance(semantic_fit_summary, Mapping)
        else [],
        "needs_manifest_revision": needs_manifest_revision,
    }


def _derive_activation_status_for_packet_report(packet_report: Mapping[str, Any]) -> dict[str, Any]:
    status = str(packet_report.get("status", "")).strip()
    if status == "missing_pdf":
        return {
            "activation_status": "missing_pdf",
            "recommended_onboarding_status": "manifest_draft",
            "transition_reason": "pdf_fixture_not_found",
            "manifest_alignment": {},
        }
    if status in {"missing_manifest", "disabled"}:
        return {
            "activation_status": "needs_manifest_revision",
            "recommended_onboarding_status": "needs_manifest_revision",
            "transition_reason": "manifest_unavailable_or_packet_disabled",
            "manifest_alignment": {},
        }
    if status != "evaluated":
        return {
            "activation_status": "planned",
            "recommended_onboarding_status": "planned",
            "transition_reason": "not_evaluated",
            "manifest_alignment": {},
        }
    contradiction_eval = packet_report.get("contradiction_eval", {})
    manifest_alignment = _derive_manifest_alignment(contradiction_eval if isinstance(contradiction_eval, Mapping) else {})
    if manifest_alignment.get("needs_manifest_revision"):
        return {
            "activation_status": "needs_manifest_revision",
            "recommended_onboarding_status": "needs_manifest_revision",
            "transition_reason": "scenario_alignment_failed",
            "manifest_alignment": manifest_alignment,
        }
    return {
        "activation_status": "evaluated",
        "recommended_onboarding_status": "evaluated",
        "transition_reason": "packet_evaluated_with_manifest_alignment",
        "manifest_alignment": manifest_alignment,
    }


def build_bundle_for_contradiction_packet(*, pdf_path: Path, packet_id: str) -> SiteSchematicBundle:
    return build_site_schematic_bundle_from_router_input(
        RouterInput(
            doc_id=pdf_path.stem or packet_id,
            filename=pdf_path.name,
            mime_type="application/pdf",
            metadata={"path": str(pdf_path)},
        )
    )


def run_contradiction_packet_registry_eval(
    *,
    registry: Mapping[str, Any],
    registry_base_dir: Path,
    selected_packet_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    packet_rows = parse_contradiction_packet_registry(registry)
    selected = {str(row).strip() for row in (selected_packet_ids or ()) if str(row).strip()}
    packet_reports: list[dict[str, Any]] = []
    for packet in packet_rows:
        if selected and packet.packet_id not in selected:
            packet_report = {
                "packet_id": packet.packet_id,
                "packet_label": packet.packet_label,
                "packet_type": packet.packet_type,
                "onboarding_status": packet.onboarding_status,
                "status": "filtered_out",
            }
            packet_report.update(_derive_activation_status_for_packet_report(packet_report))
            packet_reports.append(packet_report)
            continue
        if not packet.enabled:
            packet_report = {
                "packet_id": packet.packet_id,
                "packet_label": packet.packet_label,
                "packet_type": packet.packet_type,
                "onboarding_status": packet.onboarding_status,
                "status": "disabled",
            }
            packet_report.update(_derive_activation_status_for_packet_report(packet_report))
            packet_reports.append(packet_report)
            continue
        pdf_path = _resolve_path(registry_base_dir, packet.pdf_path)
        manifest_path = _resolve_path(registry_base_dir, packet.contradiction_manifest_path)
        symbol_path = _resolve_path(registry_base_dir, packet.symbol_benchmark_path) if packet.symbol_benchmark_path else None
        if not pdf_path.exists():
            packet_report = {
                "packet_id": packet.packet_id,
                "packet_label": packet.packet_label,
                "packet_type": packet.packet_type,
                "onboarding_status": packet.onboarding_status,
                "status": "missing_pdf",
                "pdf_path": str(pdf_path),
            }
            packet_report.update(_derive_activation_status_for_packet_report(packet_report))
            packet_reports.append(packet_report)
            continue
        if not manifest_path.exists():
            packet_report = {
                "packet_id": packet.packet_id,
                "packet_label": packet.packet_label,
                "packet_type": packet.packet_type,
                "onboarding_status": packet.onboarding_status,
                "status": "missing_manifest",
                "manifest_path": str(manifest_path),
            }
            packet_report.update(_derive_activation_status_for_packet_report(packet_report))
            packet_reports.append(packet_report)
            continue
        bundle = build_bundle_for_contradiction_packet(pdf_path=pdf_path, packet_id=packet.packet_id)
        contradiction_manifest = load_contradiction_benchmark(manifest_path)
        contradiction_report = run_contradiction_benchmark(bundle=bundle, benchmark=contradiction_manifest)
        symbol_report = run_symbol_benchmark(bundle=bundle, benchmark=load_symbol_benchmark_seed(symbol_path)) if symbol_path and symbol_path.exists() else {}
        topology_report = run_topology_benchmark(bundle=bundle)
        packet_report = {
            "packet_id": packet.packet_id,
            "packet_label": packet.packet_label,
            "packet_type": packet.packet_type,
            "onboarding_status": packet.onboarding_status,
            "priority": packet.priority,
            "expected_profile_coverage": list(packet.expected_profile_coverage),
            "expected_family_coverage": list(packet.expected_family_coverage),
            "status": "evaluated",
            "pdf_path": str(pdf_path),
            "manifest_path": str(manifest_path),
            "symbol_benchmark_path": str(symbol_path) if symbol_path else "",
            "symbol_kpi": symbol_report,
            "topology_kpi": topology_report,
            "contradiction_eval": contradiction_report,
            "diagnostics": {
                "truth_path_unchanged": True,
                "topology_additive_only": True,
                "advisory_only": True,
            },
        }
        packet_report.update(_derive_activation_status_for_packet_report(packet_report))
        packet_reports.append(packet_report)
    evaluated_rows = [row for row in packet_reports if row.get("status") == "evaluated"]
    contradiction_recalls = [
        float((row.get("contradiction_eval", {}) or {}).get("contradiction_recall", 0.0))
        for row in evaluated_rows
    ]
    high_priority_recalls = [
        float((row.get("contradiction_eval", {}) or {}).get("high_priority_review_recall", 0.0))
        for row in evaluated_rows
    ]
    return {
        "kpi_view": "contradiction_packet_registry_eval",
        "registry_packet_count": len(packet_rows),
        "evaluated_packet_count": len(evaluated_rows),
        "skipped_packet_count": len(packet_reports) - len(evaluated_rows),
        "average_contradiction_recall": round(sum(contradiction_recalls) / max(1, len(contradiction_recalls)), 4),
        "average_high_priority_review_recall": round(sum(high_priority_recalls) / max(1, len(high_priority_recalls)), 4),
        "packet_reports": packet_reports,
    }


def summarize_contradiction_packet_activation(packet_reports: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    activation_counts: Counter[str] = Counter()
    active_packet_ids: list[str] = []
    pending_packet_ids: list[str] = []
    needs_manifest_revision_packet_ids: list[str] = []
    active_families: set[str] = set()
    active_profiles: set[str] = set()
    for row in packet_reports:
        packet_id = str(row.get("packet_id", "")).strip()
        activation_status = str(row.get("activation_status", "planned")).strip() or "planned"
        activation_counts[activation_status] += 1
        if activation_status in {"fixture_validated", "evaluated"}:
            active_packet_ids.append(packet_id)
            active_families.update(str(f).strip() for f in row.get("expected_family_coverage", []) if str(f).strip())
            active_profiles.update(str(p).strip() for p in row.get("expected_profile_coverage", []) if str(p).strip())
        elif activation_status == "needs_manifest_revision":
            needs_manifest_revision_packet_ids.append(packet_id)
        else:
            pending_packet_ids.append(packet_id)
    return {
        "activation_status_counts": dict(sorted(activation_counts.items())),
        "active_packet_ids": sorted(pid for pid in active_packet_ids if pid),
        "pending_packet_ids": sorted(pid for pid in pending_packet_ids if pid),
        "needs_manifest_revision_packet_ids": sorted(pid for pid in needs_manifest_revision_packet_ids if pid),
        "active_expected_family_coverage": sorted(active_families),
        "active_expected_profile_coverage": sorted(active_profiles),
    }


def build_contradiction_manifest_template(
    *,
    packet_id: str,
    packet_label: str,
    packet_level_expected: str = "high_priority_review",
    packet_type: str = "detail_installation_conflict",
) -> dict[str, Any]:
    packet_key = str(packet_id).strip() or "new_packet"
    label = str(packet_label).strip() or "New Contradiction Packet"
    expected = str(packet_level_expected).strip() or "high_priority_review"
    if expected not in _ALLOWED_EXPECTED_OUTCOMES:
        expected = "high_priority_review"
    ptype = str(packet_type).strip() or "detail_installation_conflict"
    if ptype not in _ALLOWED_PACKET_TYPES:
        ptype = "detail_installation_conflict"
    return {
        "benchmark_id": f"contradiction_manifest::{packet_key}_v1",
        "packet_id": packet_key,
        "packet_label": label,
        "packet_level_expected": expected,
        "packet_type": ptype,
        "expected_contradiction_families": [],
        "expected_review_only_families": [],
        "expected_safe_families": [],
        "scenarios": [
            {
                "scenario_id": f"{packet_key}-scenario-1",
                "taxonomy": "topology_backed_family_incompatibility",
                "expected_outcome": "contradiction",
                "families": [],
                "profiles": [],
                "page_indices": [],
                "required_evidence_fields": [
                    "evidence_symbol_instance_ids",
                    "evidence_topology_ids",
                    "profile_ids",
                    "metadata.contradiction_reasons",
                ],
                "notes": "Fill with a contradiction-grade structural conflict.",
            },
            {
                "scenario_id": f"{packet_key}-scenario-2",
                "taxonomy": "cross_page_family_mismatch",
                "expected_outcome": "high_priority_review",
                "families": [],
                "profiles": [],
                "page_indices": [],
                "required_evidence_fields": [
                    "evidence_symbol_instance_ids",
                    "profile_ids",
                    "page_indices",
                ],
                "notes": "Fill with review-grade mismatch where contradiction is unsafe.",
            },
        ],
    }


def summarize_contradiction_packet_registry(
    *,
    registry: Mapping[str, Any],
    registry_base_dir: Path,
) -> dict[str, Any]:
    packet_rows = parse_contradiction_packet_registry(registry)
    status_counts: Counter[str] = Counter()
    packet_type_counts: Counter[str] = Counter()
    taxonomy_counts: Counter[str] = Counter()
    expected_outcome_counts: Counter[str] = Counter()
    missing_pdf: list[str] = []
    missing_manifest: list[str] = []
    manifest_errors: dict[str, list[str]] = {}
    for packet in packet_rows:
        status_counts[packet.onboarding_status] += 1
        packet_type_counts[packet.packet_type or "untyped"] += 1
        pdf_path = _resolve_path(registry_base_dir, packet.pdf_path)
        manifest_path = _resolve_path(registry_base_dir, packet.contradiction_manifest_path)
        if not pdf_path.exists():
            missing_pdf.append(packet.packet_id)
        if not manifest_path.exists():
            missing_manifest.append(packet.packet_id)
            continue
        manifest = load_contradiction_benchmark(manifest_path)
        errors = validate_contradiction_benchmark(manifest)
        if errors:
            manifest_errors[packet.packet_id] = errors
        for scenario in manifest.get("scenarios", []):
            taxonomy_counts[str(scenario.get("taxonomy", "")).strip() or "unknown"] += 1
            expected_outcome_counts[str(scenario.get("expected_outcome", "")).strip() or "unknown"] += 1
    readiness_counts: Counter[str] = Counter()
    for packet in packet_rows:
        manifest_path = _resolve_path(registry_base_dir, packet.contradiction_manifest_path)
        pdf_path = _resolve_path(registry_base_dir, packet.pdf_path)
        if not pdf_path.exists():
            readiness_counts["missing_pdf"] += 1
        elif not manifest_path.exists():
            readiness_counts["missing_manifest"] += 1
        elif packet.packet_id in manifest_errors:
            readiness_counts["needs_manifest_revision"] += 1
        else:
            readiness_counts["fixture_ready"] += 1
    return {
        "registry_packet_count": len(packet_rows),
        "status_counts": dict(status_counts),
        "readiness_status_counts": dict(sorted(readiness_counts.items())),
        "packet_type_counts": dict(packet_type_counts),
        "missing_pdf_packets": sorted(missing_pdf),
        "missing_manifest_packets": sorted(missing_manifest),
        "manifest_validation_errors": manifest_errors,
        "scenario_taxonomy_counts": dict(sorted(taxonomy_counts.items(), key=lambda item: (-item[1], item[0]))),
        "scenario_expected_outcome_counts": dict(sorted(expected_outcome_counts.items(), key=lambda item: (-item[1], item[0]))),
    }

