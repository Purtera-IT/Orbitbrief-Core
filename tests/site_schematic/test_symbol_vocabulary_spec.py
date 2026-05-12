from __future__ import annotations

from orbitbrief_core.parser.site_schematic.symbols.vocabulary import (
    classify_candidate_with_vocabulary,
    load_universal_symbol_vocabulary,
    packet_focus_class_ids,
    vocabulary_class_lookup,
)


def test_universal_symbol_vocabulary_has_required_tiers_and_roles() -> None:
    spec = load_universal_symbol_vocabulary()
    assert spec["vocabulary_version"]
    tiers = spec["tiers"]
    assert "tier1" in tiers and "tier2" in tiers and "tier3" in tiers
    classes = spec["classes"]
    assert classes
    roles = {role for row in classes for role in row.get("roles", [])}
    assert "layout_region_class" in roles
    assert "detector_class" in roles
    assert "annotation_token_class" in roles
    assert "legend_grounded_semantic_target" in roles


def test_universal_symbol_vocabulary_contains_merge_and_defer_guidance() -> None:
    lookup = vocabulary_class_lookup()
    plans = {row["training_plan"] for row in lookup.values()}
    assert "separate" in plans
    assert "merge_parent" in plans
    assert "defer" in plans


def test_packet_focus_sets_are_defined_and_classification_uses_them() -> None:
    wireless_focus = packet_focus_class_ids("wireless")
    low_voltage_focus = packet_focus_class_ids("low_voltage")
    assert wireless_focus
    assert low_voltage_focus
    result = classify_candidate_with_vocabulary(
        packet_id="wireless",
        local_text="WM AP IN ROOM 101",
        legend_texts=("WALL MOUNTED AP",),
        note_clauses=("WIRELESS ACCESS POINT",),
        abbreviations=("WM=wall mounted",),
    )
    assert result["primary_class_id"] != "unknown"
    assert result["primary_tier2"] in {"device_marker", "annotation_token"}
