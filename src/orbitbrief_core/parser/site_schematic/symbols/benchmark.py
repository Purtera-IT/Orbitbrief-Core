from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from orbitbrief_core.parser.site_schematic.models import SiteSchematicBundle
from orbitbrief_core.parser.site_schematic.symbols.detector_class_map import build_first_pass_detector_class_map, map_ontology_class_to_detector_class
from orbitbrief_core.parser.site_schematic.symbols.profile_routing import select_profile_for_context
from orbitbrief_core.parser.site_schematic.symbols.vocabulary import (
    classify_candidate_with_vocabulary,
    load_universal_symbol_vocabulary,
    packet_focus_class_ids,
    vocabulary_class_lookup,
)


def create_symbol_benchmark_seed(
    *,
    bundle: SiteSchematicBundle,
    packet_id: str,
) -> dict[str, Any]:
    expectations: list[dict[str, Any]] = []
    page_sheet: dict[int, str] = {page.page_index: page.sheet_type for page in bundle.pages}
    vocab = load_universal_symbol_vocabulary()
    vocab_lookup = vocabulary_class_lookup()
    detector_map = build_first_pass_detector_class_map()
    focus_ids = set(packet_focus_class_ids(packet_id))
    for idx, candidate in enumerate(bundle.symbol_candidate_inputs, start=1):
        classification = classify_candidate_with_vocabulary(
            packet_id=packet_id,
            local_text=candidate.local_text_context,
            legend_texts=candidate.nearby_legend_texts,
            note_clauses=candidate.nearby_note_clauses,
            abbreviations=candidate.nearby_abbreviations,
        )
        class_id = str(classification.get("primary_class_id", "unknown"))
        detector = map_ontology_class_to_detector_class(class_id)
        class_roles = list((vocab_lookup.get(class_id) or {}).get("roles", []))
        expected_grounding = bool(candidate.nearby_legend_entry_ids) or ("legend_grounded_semantic_target" in class_roles)
        profile_id, profile_reasons = select_profile_for_context(
            sheet_type=page_sheet.get(candidate.page_index, candidate.sheet_type),
            local_text=candidate.local_text_context,
        )
        expectations.append(
            {
                "expectation_id": f"benchmark:{packet_id}:{idx}",
                "packet_id": packet_id,
                "page_index": candidate.page_index,
                "sheet_type": page_sheet.get(candidate.page_index, candidate.sheet_type),
                "region_id": candidate.region_id,
                "detail_region_id": candidate.detail_region_id,
                "subregion_id": candidate.subregion_id,
                "pseudo_page_id": candidate.pseudo_page_id,
                "candidate_id": candidate.candidate_id,
                "primitive_family": class_id,
                "tier1_family": classification.get("primary_tier1", ""),
                "tier2_family": classification.get("primary_tier2", ""),
                "modality": classification.get("primary_modality", "unknown"),
                "training_plan": classification.get("primary_training_plan", "defer"),
                "merge_parent": classification.get("primary_merge_parent", ""),
                "detector_class_id": detector.get("detector_class_id"),
                "detector_selection_status": detector.get("selection_status", ""),
                "detector_selected_for_first_pass": bool(detector.get("selected_for_first_pass", False)),
                "region_profile_id": profile_id,
                "region_profile_reasons": list(profile_reasons),
                "focus_priority": "high" if class_id in focus_ids else "normal",
                "expect_legend_grounding": expected_grounding,
                "expect_note_context": bool(candidate.nearby_note_clauses),
                "context_keywords": [row[:64] for row in candidate.nearby_note_clauses[:4]],
            }
        )
    return {
        "benchmark_name": f"symbol_landing_pad::{packet_id}",
        "benchmark_version": "2026-04-09.universal_symbol_vocab_v1",
        "packet_id": packet_id,
        "vocabulary_version": vocab.get("vocabulary_version", ""),
        "detector_map_version": detector_map.get("detector_map_version", ""),
        "detector_class_ids": [row["detector_class_id"] for row in detector_map.get("detector_classes", [])],
        "focus_class_ids": sorted(focus_ids),
        "source_summary": {
            "pages": len(bundle.pages),
            "symbol_candidate_inputs": len(bundle.symbol_candidate_inputs),
            "symbol_instances": len(bundle.symbol_instances),
            "symbol_links": len(bundle.symbol_links),
        },
        "expectations": expectations,
    }


def save_symbol_benchmark_seed(*, benchmark: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(benchmark, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def load_symbol_benchmark_seed(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_symbol_benchmark_seed(benchmark: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(benchmark, dict):
        return ["benchmark must be an object"]
    if not benchmark.get("benchmark_version"):
        errors.append("missing benchmark_version")
    expectations = benchmark.get("expectations")
    if not isinstance(expectations, list) or not expectations:
        errors.append("expectations must be a non-empty list")
        return errors
    required = {"expectation_id", "packet_id", "page_index", "primitive_family", "candidate_id"}
    for idx, row in enumerate(expectations, start=1):
        if not isinstance(row, dict):
            errors.append(f"expectation#{idx} must be an object")
            continue
        missing = sorted(required - set(row.keys()))
        if missing:
            errors.append(f"expectation#{idx} missing fields: {', '.join(missing)}")
    return errors


def run_symbol_benchmark(
    *,
    bundle: SiteSchematicBundle,
    benchmark: dict[str, Any],
) -> dict[str, Any]:
    expectations = benchmark.get("expectations") or []
    candidate_by_id = {row.candidate_id: row for row in bundle.symbol_candidate_inputs}
    linked_by_page = {
        row.page_index: [link for link in bundle.symbol_links if link.page_index == row.page_index]
        for row in bundle.pages
    }
    matched = 0
    legend_grounding_hits = 0
    note_context_hits = 0
    legend_grounding_expected = 0
    note_context_expected = 0
    family_hits: dict[str, int] = {}
    detector_hits: dict[str, int] = {}
    focus_ids = set(benchmark.get("focus_class_ids", []))
    focus_total = 0
    focus_hits = 0
    detector_selected_total = 0
    detector_selected_hits = 0
    unresolved_or_conflicting = 0
    linked_by_page_count = {
        row.page_index: sum(1 for link in bundle.symbol_links if link.page_index == row.page_index and link.status == "linked")
        for row in bundle.pages
    }
    false_positive_proxy: dict[str, int] = {}
    profile_hits: dict[str, int] = {}
    profile_unresolved_or_conflicting: dict[str, int] = {}
    for row in expectations:
        candidate = candidate_by_id.get(str(row.get("candidate_id", "")))
        if candidate is None:
            continue
        matched += 1
        family = str(row.get("primitive_family", "unknown"))
        family_hits[family] = family_hits.get(family, 0) + 1
        detector_class_id = str(row.get("detector_class_id", "") or "")
        if detector_class_id:
            detector_hits[detector_class_id] = detector_hits.get(detector_class_id, 0) + 1
        if row.get("detector_selected_for_first_pass"):
            detector_selected_total += 1
            detector_selected_hits += 1
        if family in focus_ids:
            focus_total += 1
            focus_hits += 1
        page_links = linked_by_page.get(candidate.page_index, [])
        if row.get("expect_legend_grounding"):
            legend_grounding_expected += 1
            if any(link.legend_entry_id for link in page_links):
                legend_grounding_hits += 1
        if row.get("expect_note_context"):
            note_context_expected += 1
            if candidate.nearby_note_clauses:
                note_context_hits += 1
        if any(link.status in {"unresolved", "conflicting"} for link in page_links):
            unresolved_or_conflicting += 1
        if detector_class_id and linked_by_page_count.get(candidate.page_index, 0) == 0:
            false_positive_proxy[detector_class_id] = false_positive_proxy.get(detector_class_id, 0) + 1
        profile_id = str(row.get("region_profile_id", "") or "unclassified")
        profile_hits[profile_id] = profile_hits.get(profile_id, 0) + 1
        if any(link.status in {"unresolved", "conflicting"} for link in page_links):
            profile_unresolved_or_conflicting[profile_id] = profile_unresolved_or_conflicting.get(profile_id, 0) + 1
    total = max(1, len(expectations))
    sparse_detector_classes = sorted([key for key, count in detector_hits.items() if count < 3])
    return {
        "kpi_view": "canonical_symbol",
        "benchmark_name": benchmark.get("benchmark_name", "unknown_benchmark"),
        "benchmark_version": benchmark.get("benchmark_version", ""),
        "expectation_count": len(expectations),
        "candidate_match_rate": round(matched / total, 4),
        "legend_grounding_expected_count": legend_grounding_expected,
        "note_context_expected_count": note_context_expected,
        "legend_grounding_rate": round(legend_grounding_hits / max(1, legend_grounding_expected), 4),
        "note_context_rate": round(note_context_hits / max(1, note_context_expected), 4),
        "focus_family_match_rate": round(focus_hits / max(1, focus_total), 4),
        "family_expectation_counts": dict(sorted(family_hits.items(), key=lambda item: (-item[1], item[0]))),
        "detector_class_coverage_rate": round(detector_selected_hits / max(1, detector_selected_total), 4),
        "detector_class_expectation_counts": dict(sorted(detector_hits.items(), key=lambda item: (-item[1], item[0]))),
        "detector_class_sparse_under_3": sparse_detector_classes,
        "unresolved_or_conflicting_rate": round(unresolved_or_conflicting / total, 4),
        "per_family_false_positive_proxy": dict(sorted(false_positive_proxy.items(), key=lambda item: (-item[1], item[0]))),
        "profile_expectation_counts": dict(sorted(profile_hits.items(), key=lambda item: (-item[1], item[0]))),
        "profile_unresolved_or_conflicting_counts": dict(sorted(profile_unresolved_or_conflicting.items(), key=lambda item: (-item[1], item[0]))),
        "symbol_status_counts": {
            "linked": sum(1 for row in bundle.symbol_links if row.status == "linked"),
            "weakly_linked": sum(1 for row in bundle.symbol_links if row.status == "weakly_linked"),
            "unresolved": sum(1 for row in bundle.symbol_links if row.status == "unresolved"),
            "conflicting": sum(1 for row in bundle.symbol_links if row.status == "conflicting"),
            "detected_but_unmapped": sum(1 for row in bundle.symbol_links if row.status == "detected_but_unmapped"),
            "candidate_requires_review": sum(1 for row in bundle.symbol_links if row.status == "candidate_requires_review"),
        },
        "resolution_outcome_counts": {
            "linked": sum(1 for row in bundle.symbol_resolution_outcomes if row.status == "linked"),
            "weakly_linked": sum(1 for row in bundle.symbol_resolution_outcomes if row.status == "weakly_linked"),
            "unresolved": sum(1 for row in bundle.symbol_resolution_outcomes if row.status == "unresolved"),
            "conflicting": sum(1 for row in bundle.symbol_resolution_outcomes if row.status == "conflicting"),
            "legend_defined_but_unused": sum(1 for row in bundle.symbol_resolution_outcomes if row.status == "legend_defined_but_unused"),
            "detected_but_unmapped": sum(1 for row in bundle.symbol_resolution_outcomes if row.status == "detected_but_unmapped"),
            "candidate_requires_review": sum(1 for row in bundle.symbol_resolution_outcomes if row.status == "candidate_requires_review"),
        },
    }


def run_topology_benchmark(*, bundle: SiteSchematicBundle) -> dict[str, Any]:
    endpoint_by_profile: dict[str, int] = {}
    relation_by_profile: dict[str, int] = {}
    relation_abstain_by_profile: dict[str, int] = {}
    endpoint_unresolved_by_profile: dict[str, int] = {}
    continuity_relation_kinds: dict[str, int] = {}
    for row in bundle.topology_endpoints:
        endpoint_by_profile[row.profile_id] = endpoint_by_profile.get(row.profile_id, 0) + 1
        if row.status != "inferred":
            endpoint_unresolved_by_profile[row.profile_id] = endpoint_unresolved_by_profile.get(row.profile_id, 0) + 1
    for row in bundle.topology_relations:
        relation_by_profile[row.profile_id] = relation_by_profile.get(row.profile_id, 0) + 1
        continuity_relation_kinds[row.relation_kind] = continuity_relation_kinds.get(row.relation_kind, 0) + 1
        if row.status != "inferred":
            relation_abstain_by_profile[row.profile_id] = relation_abstain_by_profile.get(row.profile_id, 0) + 1
    return {
        "kpi_view": "additive_topology",
        "topology_endpoint_count": len(bundle.topology_endpoints),
        "topology_relation_count": len(bundle.topology_relations),
        "topology_segment_count": len(bundle.topology_segments),
        "topology_riser_edge_count": len(bundle.riser_edges),
        "topology_endpoint_unresolved_count": sum(1 for row in bundle.topology_endpoints if row.status != "inferred"),
        "topology_relation_abstain_count": sum(1 for row in bundle.topology_relations if row.status != "inferred"),
        "profile_topology_endpoint_counts": dict(sorted(endpoint_by_profile.items(), key=lambda item: (-item[1], item[0]))),
        "profile_topology_relation_counts": dict(sorted(relation_by_profile.items(), key=lambda item: (-item[1], item[0]))),
        "profile_topology_endpoint_unresolved_counts": dict(sorted(endpoint_unresolved_by_profile.items(), key=lambda item: (-item[1], item[0]))),
        "profile_topology_abstain_counts": dict(sorted(relation_abstain_by_profile.items(), key=lambda item: (-item[1], item[0]))),
        "continuity_relation_counts": dict(sorted(continuity_relation_kinds.items(), key=lambda item: (-item[1], item[0]))),
    }

