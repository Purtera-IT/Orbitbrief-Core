from __future__ import annotations

from functools import lru_cache
from typing import Any

from orbitbrief_core.parser.site_schematic.symbols.vocabulary import load_universal_symbol_vocabulary

_VISUAL_MODALITIES = {"visual_primitive", "annotation_token"}
_DETECTOR_ROLES = {"detector_class", "annotation_token_class"}
_FORCED_FIRST_PASS_COLLAPSES = {
    "token_rs1": "room_scheduler_outlet_marker",
    "token_rs2": "room_scheduler_outlet_marker",
    "token_rs3": "room_scheduler_outlet_marker",
    "token_csp2": "token_cip",
    "token_csp3": "token_cip",
}


def _has_detector_role(row: dict[str, Any]) -> bool:
    roles = row.get("roles", [])
    if not isinstance(roles, list):
        return False
    return any(str(value) in _DETECTOR_ROLES for value in roles)


@lru_cache(maxsize=1)
def build_first_pass_detector_class_map(*, max_detector_classes: int = 32, min_detector_classes: int = 20) -> dict[str, Any]:
    spec = load_universal_symbol_vocabulary()
    classes = spec.get("classes", [])
    if not isinstance(classes, list):
        classes = []
    class_lookup = {str(row["id"]): dict(row) for row in classes if isinstance(row, dict) and "id" in row}
    focus_sets = spec.get("packet_focus_sets", {})
    wireless_focus = set(focus_sets.get("wireless", [])) if isinstance(focus_sets, dict) else set()
    low_voltage_focus = set(focus_sets.get("low_voltage", [])) if isinstance(focus_sets, dict) else set()
    all_focus = wireless_focus | low_voltage_focus

    def resolve_detector_id(class_id: str, *, depth: int = 0) -> tuple[str | None, str]:
        if depth > 8:
            return (None, "deferred_cycle_guard")
        row = class_lookup.get(class_id)
        if row is None:
            return (None, "unknown_ontology_class")
        modality = str(row.get("modality", ""))
        if modality not in _VISUAL_MODALITIES:
            return (None, "layout_only")
        if not _has_detector_role(row):
            return (None, "not_detector_role")
        forced_parent = _FORCED_FIRST_PASS_COLLAPSES.get(class_id)
        if forced_parent:
            parent_detector, _ = resolve_detector_id(forced_parent, depth=depth + 1)
            if parent_detector is None:
                return (None, "deferred_forced_parent_unavailable")
            return (parent_detector, "mapped_forced_merge")
        training_plan = str(row.get("training_plan", "defer"))
        if training_plan == "defer":
            return (None, "deferred")
        if training_plan == "separate":
            return (class_id, "mapped_separate")
        if training_plan == "merge_parent":
            parent = str(row.get("merge_parent", "")).strip()
            if not parent:
                return (None, "deferred_missing_merge_parent")
            parent_detector, _ = resolve_detector_id(parent, depth=depth + 1)
            if parent_detector is None:
                return (None, "deferred_parent_unavailable")
            return (parent_detector, "mapped_merged")
        return (None, "deferred_unknown_training_plan")

    ontology_mapping: dict[str, dict[str, Any]] = {}
    detector_support: dict[str, set[str]] = {}
    detector_scores: dict[str, float] = {}
    required_by_focus: set[str] = set()
    for class_id, row in class_lookup.items():
        detector_id, status = resolve_detector_id(class_id)
        mapped = detector_id is not None
        ontology_mapping[class_id] = {
            "ontology_class_id": class_id,
            "detector_class_id": detector_id,
            "status": status,
            "selected_for_first_pass": False,
            "modality": str(row.get("modality", "")),
            "tier1": str(row.get("tier1", "")),
            "tier2": str(row.get("tier2", "")),
            "training_plan": str(row.get("training_plan", "")),
            "merge_parent": str(row.get("merge_parent", "")),
            "sparsity": str(row.get("sparsity", "")),
            "roles": list(row.get("roles", [])),
        }
        if not mapped:
            continue
        detector_support.setdefault(detector_id, set()).add(class_id)
        score = 0.0
        if class_id in all_focus:
            score += 8.0
        if row.get("training_plan") == "separate":
            score += 2.0
        sparsity = str(row.get("sparsity", ""))
        if sparsity == "dense":
            score += 1.0
        elif sparsity == "moderate":
            score += 0.5
        if "annotation_token_class" in row.get("roles", []):
            score += 0.25
        detector_scores[detector_id] = detector_scores.get(detector_id, 0.0) + score
        if class_id in all_focus:
            required_by_focus.add(detector_id)

    selected: list[str] = sorted(required_by_focus)
    ordered = sorted(detector_scores.items(), key=lambda item: (-item[1], item[0]))
    for detector_id, _ in ordered:
        if detector_id in selected:
            continue
        if len(selected) >= max_detector_classes:
            break
        selected.append(detector_id)
    if len(selected) < min_detector_classes:
        for detector_id, _ in ordered:
            if detector_id in selected:
                continue
            selected.append(detector_id)
            if len(selected) >= min_detector_classes:
                break
    selected_set = set(selected)

    detector_classes: list[dict[str, Any]] = []
    for detector_id in selected:
        row = class_lookup.get(detector_id, {})
        detector_classes.append(
            {
                "detector_class_id": detector_id,
                "ontology_anchor_class_id": detector_id,
                "name": str(row.get("name", detector_id)),
                "tier2": str(row.get("tier2", "")),
                "modality": str(row.get("modality", "")),
                "sparsity": str(row.get("sparsity", "")),
                "score": round(detector_scores.get(detector_id, 0.0), 4),
                "supported_ontology_classes": sorted(detector_support.get(detector_id, set())),
                "focus_required": detector_id in required_by_focus,
            }
        )

    deferred: list[dict[str, Any]] = []
    for class_id, row in ontology_mapping.items():
        detector_id = row["detector_class_id"]
        if detector_id and detector_id in selected_set:
            row["selected_for_first_pass"] = True
            row["selection_status"] = "selected"
            continue
        if detector_id and detector_id not in selected_set:
            row["selection_status"] = "mapped_but_not_selected"
            deferred.append(
                {
                    "ontology_class_id": class_id,
                    "detector_class_id": detector_id,
                    "reason": "mapped_but_not_selected",
                    "training_plan": row["training_plan"],
                }
            )
            continue
        row["selection_status"] = row["status"]
        if row["status"].startswith("deferred"):
            deferred.append(
                {
                    "ontology_class_id": class_id,
                    "detector_class_id": None,
                    "reason": row["status"],
                    "training_plan": row["training_plan"],
                }
            )

    return {
        "detector_map_version": "2026-04-09.detector_pass_v1",
        "vocabulary_version": spec.get("vocabulary_version", ""),
        "target_detector_class_count": {"min": min_detector_classes, "max": max_detector_classes},
        "detector_classes": detector_classes,
        "ontology_to_detector": ontology_mapping,
        "deferred_ontology_classes": deferred,
        "packet_focus_sets": {
            "wireless": sorted(wireless_focus),
            "low_voltage": sorted(low_voltage_focus),
        },
    }


def map_ontology_class_to_detector_class(ontology_class_id: str) -> dict[str, Any]:
    mapping = build_first_pass_detector_class_map()
    row = mapping["ontology_to_detector"].get(ontology_class_id)
    if row is None:
        return {
            "ontology_class_id": ontology_class_id,
            "detector_class_id": None,
            "selection_status": "unknown_ontology_class",
            "selected_for_first_pass": False,
        }
    return dict(row)

