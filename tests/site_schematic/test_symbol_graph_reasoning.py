from __future__ import annotations

from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.site_schematic import build_site_schematic_bundle_from_router_input
from orbitbrief_core.parser.site_schematic.models import (
    SiteSchematicGraph,
    SiteSchematicGraphEdge,
    SiteSchematicGraphNode,
    SiteSchematicSymbolInstance,
    SiteSchematicSymbolLink,
    SiteSchematicTopologyEndpoint,
    SiteSchematicTopologyRelation,
)
from orbitbrief_core.parser.site_schematic.reasoning import build_bounded_graph_reasoning


def _graph_with_symbols() -> SiteSchematicGraph:
    return SiteSchematicGraph(
        nodes=(
            SiteSchematicGraphNode(node_id="symbol:s1", kind="symbol_instance", label="DATA", page_index=1),
            SiteSchematicGraphNode(node_id="symbol:s2", kind="symbol_instance", label="DATA", page_index=2),
            SiteSchematicGraphNode(node_id="legend:leg1", kind="legend_entry", label="DATA OUTLET", page_index=1),
        ),
        edges=(
            SiteSchematicGraphEdge(
                edge_id="edge:1",
                source_node_id="symbol:s1",
                target_node_id="legend:leg1",
                relation="matches_legend",
                confidence=0.88,
            ),
        ),
    )


def test_reasoning_emits_contradiction_and_anchor_reviews() -> None:
    symbols = (
        SiteSchematicSymbolInstance(
            instance_id="s1",
            page_index=1,
            token="DATA",
            primitive_kind="symbol",
            text="data outlet",
            confidence=0.9,
            overlay_tags=("low_voltage",),
            metadata={"detector_class_id": "data_outlet", "detector_profile_id": "plan_body_profile"},
        ),
        SiteSchematicSymbolInstance(
            instance_id="s2",
            page_index=2,
            token="DATA",
            primitive_kind="symbol",
            text="data outlet",
            confidence=0.86,
            overlay_tags=("low_voltage",),
            metadata={"detector_class_id": "data_outlet", "detector_profile_id": "control_legend_profile"},
        ),
    )
    links = (
        SiteSchematicSymbolLink(
            link_id="l1",
            page_index=1,
            instance_id="s1",
            symbol_token="DATA",
            status="linked",
            confidence=0.87,
            legend_entry_id="leg1",
            legend_label="DATA OUTLET",
        ),
        SiteSchematicSymbolLink(
            link_id="l2",
            page_index=2,
            instance_id="s2",
            symbol_token="DATA",
            status="detected_but_unmapped",
            confidence=0.41,
            legend_label="DATA OUTLET",
        ),
    )
    findings, checks, contradiction_flags, anchor_suggestions, topo_suggestions, diagnostics = build_bounded_graph_reasoning(
        graph=_graph_with_symbols(),
        symbol_instances=symbols,
        symbol_links=links,
        topology_endpoints=(),
        topology_relations=(),
    )
    assert findings
    assert checks
    assert contradiction_flags
    assert any(row.finding_type == "cross_page_consistency" for row in findings)
    assert any(row.triage_bucket == "contradiction_high_confidence" for row in findings)
    assert any(row.status in {"needs_review", "ambiguous"} for row in anchor_suggestions)
    contradicted = [row for row in findings if row.status == "contradicted"]
    assert contradicted
    assert contradicted[0].evidence_symbol_instance_ids
    assert diagnostics.get("finding_count", 0) >= 1
    assert topo_suggestions == ()


def test_reasoning_abstains_without_topology_relations() -> None:
    symbols = (
        SiteSchematicSymbolInstance(
            instance_id="s1",
            page_index=1,
            token="RE",
            primitive_kind="symbol",
            text="riser endpoint",
            confidence=0.83,
            overlay_tags=("low_voltage",),
            metadata={"detector_class_id": "riser_endpoint", "detector_profile_id": "riser_profile"},
        ),
        SiteSchematicSymbolInstance(
            instance_id="s2",
            page_index=1,
            token="RW",
            primitive_kind="symbol",
            text="ladder rack",
            confidence=0.81,
            overlay_tags=("low_voltage",),
            metadata={"detector_class_id": "ladder_rack_cable_runway", "detector_profile_id": "riser_profile"},
        ),
    )
    links = (
        SiteSchematicSymbolLink(link_id="l1", page_index=1, instance_id="s1", symbol_token="RE", status="linked", confidence=0.84),
        SiteSchematicSymbolLink(link_id="l2", page_index=1, instance_id="s2", symbol_token="RW", status="linked", confidence=0.83),
    )
    endpoints = (
        SiteSchematicTopologyEndpoint(
            endpoint_id="ep1",
            page_index=1,
            profile_id="riser_profile",
            endpoint_kind="riser_endpoint",
            detector_class_id="riser_endpoint",
            symbol_instance_ids=("s1",),
            confidence=0.74,
            status="inferred",
        ),
        SiteSchematicTopologyEndpoint(
            endpoint_id="ep2",
            page_index=1,
            profile_id="riser_profile",
            endpoint_kind="pathway_runway",
            detector_class_id="ladder_rack_cable_runway",
            symbol_instance_ids=("s2",),
            confidence=0.7,
            status="inferred",
        ),
    )
    findings, _, _, _, _, _ = build_bounded_graph_reasoning(
        graph=_graph_with_symbols(),
        symbol_instances=symbols,
        symbol_links=links,
        topology_endpoints=endpoints,
        topology_relations=(),
    )
    assert any(row.status == "abstained" and row.finding_type == "topology_continuity_review" for row in findings)
    assert any(row.triage_bucket == "ambiguity_needs_review" for row in findings if row.status == "abstained")


def test_reasoning_diagnostics_present_in_bundle_registry() -> None:
    sample_text = """
<PARSED TEXT FOR PAGE: 1 / 1>
TC001 LEGEND
DATA OUTLET
""".strip()
    bundle = build_site_schematic_bundle_from_router_input(
        RouterInput(
            doc_id="reasoning-bundle",
            filename="reasoning-bundle.pdf",
            mime_type="application/pdf",
            metadata={"full_text": sample_text},
        )
    )
    diag = dict(bundle.model_registry).get("graph_reasoning", {})
    assert isinstance(diag, dict)
    assert "finding_count" in diag


def test_reasoning_uses_inferred_vs_unresolved_topology_distinctly() -> None:
    symbols = (
        SiteSchematicSymbolInstance(
            instance_id="r1",
            page_index=1,
            token="RIS",
            primitive_kind="symbol",
            text="riser endpoint",
            confidence=0.86,
            overlay_tags=("low_voltage",),
            metadata={"detector_class_id": "riser_endpoint", "detector_profile_id": "riser_profile"},
        ),
        SiteSchematicSymbolInstance(
            instance_id="r2",
            page_index=1,
            token="RIS",
            primitive_kind="symbol",
            text="riser endpoint",
            confidence=0.84,
            overlay_tags=("low_voltage",),
            metadata={"detector_class_id": "riser_endpoint", "detector_profile_id": "riser_profile"},
        ),
    )
    links = (
        SiteSchematicSymbolLink(link_id="lr1", page_index=1, instance_id="r1", symbol_token="RIS", status="linked", confidence=0.88),
        SiteSchematicSymbolLink(link_id="lr2", page_index=1, instance_id="r2", symbol_token="RIS", status="detected_but_unmapped", confidence=0.7),
    )
    endpoints = (
        SiteSchematicTopologyEndpoint(
            endpoint_id="ep:r1",
            page_index=1,
            profile_id="riser_profile",
            endpoint_kind="riser_endpoint",
            detector_class_id="riser_endpoint",
            symbol_instance_ids=("r1",),
            confidence=0.83,
            status="inferred",
        ),
        SiteSchematicTopologyEndpoint(
            endpoint_id="ep:r2",
            page_index=1,
            profile_id="riser_profile",
            endpoint_kind="riser_endpoint",
            detector_class_id="riser_endpoint",
            symbol_instance_ids=("r2",),
            confidence=0.71,
            status="unresolved",
        ),
    )
    relations = (
        SiteSchematicTopologyRelation(
            relation_id="rel:r",
            page_index=1,
            profile_id="riser_profile",
            relation_kind="riser_continuity",
            source_endpoint_id="ep:r1",
            target_endpoint_id="ep:r2",
            confidence=0.79,
            status="inferred",
        ),
        SiteSchematicTopologyRelation(
            relation_id="rel:r2",
            page_index=1,
            profile_id="riser_profile",
            relation_kind="riser_continuity",
            source_endpoint_id="ep:r2",
            target_endpoint_id="ep:r1",
            confidence=0.55,
            status="unresolved",
        ),
    )
    findings, _, _, _, _, diagnostics = build_bounded_graph_reasoning(
        graph=_graph_with_symbols(),
        symbol_instances=symbols,
        symbol_links=links,
        topology_endpoints=endpoints,
        topology_relations=relations,
    )
    assert any(
        row.finding_type == "anchor_reconciliation"
        and row.status in {"needs_review", "contradicted"}
        and row.metadata.get("inferred_topology_relation_count", 0) >= 1
        for row in findings
    )
    topo_rows = [row for row in findings if row.finding_type == "topology_continuity_review"]
    assert topo_rows
    assert any(row.metadata.get("topology_evidence_tier") == "strong_inferred" for row in topo_rows)
    assert any(row.metadata.get("topology_evidence_tier") == "weak_unresolved" for row in topo_rows)
    assert diagnostics.get("topology_status_counts", {}).get("inferred_relation_count", 0) >= 1
    assert diagnostics.get("topology_aware_high_priority_review_count", 0) >= 1


def test_reasoning_escalates_contradiction_for_inferred_topology_family_conflict() -> None:
    symbols = (
        SiteSchematicSymbolInstance(
            instance_id="c1",
            page_index=5,
            token="DATA",
            primitive_kind="symbol",
            text="data outlet",
            confidence=0.9,
            overlay_tags=("low_voltage",),
            metadata={"detector_class_id": "data_outlet", "detector_profile_id": "rack_detail_profile"},
        ),
    )
    links = (
        SiteSchematicSymbolLink(
            link_id="lc1",
            page_index=5,
            instance_id="c1",
            symbol_token="DATA",
            status="linked",
            confidence=0.86,
            legend_entry_id="leg:data",
            legend_label="DATA",
        ),
    )
    endpoints = (
        SiteSchematicTopologyEndpoint(
            endpoint_id="ep:c1a",
            page_index=5,
            profile_id="rack_detail_profile",
            endpoint_kind="rack_anchor",
            detector_class_id="patch_panel_row",
            symbol_instance_ids=("c1",),
            confidence=0.82,
            status="inferred",
        ),
        SiteSchematicTopologyEndpoint(
            endpoint_id="ep:c1b",
            page_index=5,
            profile_id="rack_detail_profile",
            endpoint_kind="rack_anchor",
            detector_class_id="patch_panel_row",
            symbol_instance_ids=("c1",),
            confidence=0.81,
            status="inferred",
        ),
    )
    relations = (
        SiteSchematicTopologyRelation(
            relation_id="rel:c1",
            page_index=5,
            profile_id="rack_detail_profile",
            relation_kind="rack_connectivity",
            source_endpoint_id="ep:c1a",
            target_endpoint_id="ep:c1b",
            confidence=0.88,
            status="inferred",
        ),
    )
    findings, _, contradiction_flags, _, _, _ = build_bounded_graph_reasoning(
        graph=_graph_with_symbols(),
        symbol_instances=symbols,
        symbol_links=links,
        topology_endpoints=endpoints,
        topology_relations=relations,
    )
    anchor_rows = [row for row in findings if row.finding_type == "anchor_reconciliation"]
    assert anchor_rows
    assert any(row.status == "contradicted" for row in anchor_rows)
    assert any("inferred_topology_relation_incompatible_with_grounded_family" in row.metadata.get("contradiction_reasons", []) for row in anchor_rows)
    assert any(row.metadata.get("rule_name") == "inferred_topology_family_conflict" for row in anchor_rows)
    assert contradiction_flags


def test_reasoning_detail_installation_inferred_pathway_mixed_grounding_high_priority() -> None:
    symbols = (
        SiteSchematicSymbolInstance(
            instance_id="d1",
            page_index=6,
            token="JACK",
            primitive_kind="symbol",
            text="telecomm jack",
            confidence=0.86,
            overlay_tags=("low_voltage",),
            metadata={"detector_class_id": "telecomm_jack_tag", "detector_profile_id": "detail_installation_profile"},
        ),
    )
    links = (
        SiteSchematicSymbolLink(
            link_id="ld1",
            page_index=6,
            instance_id="d1",
            symbol_token="JACK",
            status="detected_but_unmapped",
            confidence=0.68,
        ),
    )
    endpoints = (
        SiteSchematicTopologyEndpoint(
            endpoint_id="ep:d1",
            page_index=6,
            profile_id="detail_installation_profile",
            endpoint_kind="termination_point",
            detector_class_id="telecomm_jack_tag",
            symbol_instance_ids=("d1",),
            detail_region_id="dr:install",
            pseudo_page_id="pp:install",
            confidence=0.82,
            status="inferred",
            metadata={"has_note_support": True, "legend_entry_id": "leg:d1"},
        ),
        SiteSchematicTopologyEndpoint(
            endpoint_id="ep:d2",
            page_index=6,
            profile_id="detail_installation_profile",
            endpoint_kind="pathway_runway",
            detector_class_id="ladder_rack_cable_runway",
            symbol_instance_ids=("d1",),
            detail_region_id="dr:install",
            pseudo_page_id="pp:install",
            confidence=0.83,
            status="inferred",
            metadata={"has_note_support": True},
        ),
    )
    relations = (
        SiteSchematicTopologyRelation(
            relation_id="rel:d1",
            page_index=6,
            profile_id="detail_installation_profile",
            relation_kind="pathway_attachment",
            source_endpoint_id="ep:d1",
            target_endpoint_id="ep:d2",
            confidence=0.9,
            status="inferred",
        ),
    )
    findings, _, _, _, _, diagnostics = build_bounded_graph_reasoning(
        graph=_graph_with_symbols(),
        symbol_instances=symbols,
        symbol_links=links,
        topology_endpoints=endpoints,
        topology_relations=relations,
    )
    detail_rows = [row for row in findings if row.finding_type == "anchor_reconciliation" and "detail_installation_profile" in set(row.profile_ids)]
    assert detail_rows
    assert any("detail_installation_inferred_pathway_mixed_grounding" in row.metadata.get("contradiction_reasons", []) for row in detail_rows)
    assert any(row.triage_bucket == "high_priority_review" for row in detail_rows)
    assert diagnostics.get("detail_installation_high_priority_review_count", 0) >= 1


def test_reasoning_detail_installation_inferred_pathway_incompatible_linked_can_contradict() -> None:
    symbols = (
        SiteSchematicSymbolInstance(
            instance_id="d2",
            page_index=7,
            token="PP",
            primitive_kind="symbol",
            text="patch panel",
            confidence=0.89,
            overlay_tags=("low_voltage",),
            metadata={"detector_class_id": "patch_panel_row", "detector_profile_id": "detail_installation_profile"},
        ),
    )
    links = (
        SiteSchematicSymbolLink(
            link_id="ld2",
            page_index=7,
            instance_id="d2",
            symbol_token="PP",
            status="linked",
            confidence=0.86,
            legend_entry_id="leg:pp",
        ),
    )
    endpoints = (
        SiteSchematicTopologyEndpoint(
            endpoint_id="ep:x1",
            page_index=7,
            profile_id="detail_installation_profile",
            endpoint_kind="rack_component",
            detector_class_id="patch_panel_row",
            symbol_instance_ids=("d2",),
            detail_region_id="dr:x",
            pseudo_page_id="pp:x",
            confidence=0.84,
            status="inferred",
            metadata={"has_note_support": True, "legend_entry_id": "leg:pp"},
        ),
        SiteSchematicTopologyEndpoint(
            endpoint_id="ep:x2",
            page_index=7,
            profile_id="detail_installation_profile",
            endpoint_kind="pathway_runway",
            detector_class_id="ladder_rack_cable_runway",
            symbol_instance_ids=("d2",),
            detail_region_id="dr:x",
            pseudo_page_id="pp:x",
            confidence=0.83,
            status="inferred",
            metadata={"has_note_support": True},
        ),
    )
    relations = (
        SiteSchematicTopologyRelation(
            relation_id="rel:x",
            page_index=7,
            profile_id="detail_installation_profile",
            relation_kind="pathway_attachment",
            source_endpoint_id="ep:x1",
            target_endpoint_id="ep:x2",
            confidence=0.9,
            status="inferred",
        ),
    )
    findings, _, contradiction_flags, _, _, diagnostics = build_bounded_graph_reasoning(
        graph=_graph_with_symbols(),
        symbol_instances=symbols,
        symbol_links=links,
        topology_endpoints=endpoints,
        topology_relations=relations,
    )
    anchor_rows = [row for row in findings if row.finding_type == "anchor_reconciliation"]
    assert anchor_rows
    assert any(row.status == "contradicted" for row in anchor_rows)
    assert any("detail_installation_inferred_relation_family_incompatible" in row.metadata.get("contradiction_reasons", []) for row in anchor_rows)
    assert any(row.metadata.get("rule_name") == "inferred_topology_family_conflict" for row in anchor_rows)
    assert diagnostics.get("detail_installation_contradiction_count", 0) >= 1
    assert contradiction_flags


def test_reasoning_strengthened_anchor_drives_detail_installation_contradiction() -> None:
    symbols = (
        SiteSchematicSymbolInstance(
            instance_id="ds1",
            page_index=9,
            token="PP",
            primitive_kind="symbol",
            text="patch panel",
            confidence=0.9,
            overlay_tags=("low_voltage",),
            metadata={"detector_class_id": "patch_panel_row", "detector_profile_id": "detail_installation_profile"},
        ),
    )
    links = (
        SiteSchematicSymbolLink(
            link_id="lds1",
            page_index=9,
            instance_id="ds1",
            symbol_token="PP",
            status="linked",
            confidence=0.86,
            legend_entry_id="leg:pp",
            metadata={
                "grounding_strengthened": True,
                "grounding_strengthening_rule": "structural_topology_anchor_bridge_v1",
                "grounding_strengthening_original_status": "detected_but_unmapped",
            },
        ),
    )
    endpoints = (
        SiteSchematicTopologyEndpoint(
            endpoint_id="ep:ds1a",
            page_index=9,
            profile_id="detail_installation_profile",
            endpoint_kind="rack_component",
            detector_class_id="patch_panel_row",
            symbol_instance_ids=("ds1",),
            detail_region_id="dr:ds1",
            pseudo_page_id="pp:ds1",
            confidence=0.84,
            status="inferred",
            metadata={"has_note_support": True, "legend_entry_id": "leg:pp"},
        ),
        SiteSchematicTopologyEndpoint(
            endpoint_id="ep:ds1b",
            page_index=9,
            profile_id="detail_installation_profile",
            endpoint_kind="pathway_runway",
            detector_class_id="ladder_rack_cable_runway",
            symbol_instance_ids=("ds1",),
            detail_region_id="dr:ds1",
            pseudo_page_id="pp:ds1",
            confidence=0.83,
            status="inferred",
            metadata={"has_note_support": True},
        ),
    )
    relations = (
        SiteSchematicTopologyRelation(
            relation_id="rel:ds1",
            page_index=9,
            profile_id="detail_installation_profile",
            relation_kind="pathway_attachment",
            source_endpoint_id="ep:ds1a",
            target_endpoint_id="ep:ds1b",
            confidence=0.9,
            status="inferred",
        ),
    )
    findings, _, contradiction_flags, _, _, diagnostics = build_bounded_graph_reasoning(
        graph=_graph_with_symbols(),
        symbol_instances=symbols,
        symbol_links=links,
        topology_endpoints=endpoints,
        topology_relations=relations,
    )
    anchor_rows = [row for row in findings if row.finding_type == "anchor_reconciliation"]
    assert anchor_rows
    assert any(row.status == "contradicted" for row in anchor_rows)
    assert any(
        "detail_installation_strengthened_anchor_relation_incompatible" in row.metadata.get("contradiction_reasons", [])
        for row in anchor_rows
    )
    assert any(row.metadata.get("anchor_strengthened") is True for row in anchor_rows)
    assert diagnostics.get("strengthened_anchor_contradiction_count", 0) >= 1
    assert contradiction_flags


def test_reasoning_mixed_anchor_remains_review_not_contradiction() -> None:
    symbols = (
        SiteSchematicSymbolInstance(
            instance_id="dm1",
            page_index=10,
            token="PP",
            primitive_kind="symbol",
            text="patch panel",
            confidence=0.84,
            overlay_tags=("low_voltage",),
            metadata={"detector_class_id": "patch_panel_row", "detector_profile_id": "detail_installation_profile"},
        ),
    )
    links = (
        SiteSchematicSymbolLink(
            link_id="ldm1",
            page_index=10,
            instance_id="dm1",
            symbol_token="PP",
            status="detected_but_unmapped",
            confidence=0.62,
        ),
    )
    endpoints = (
        SiteSchematicTopologyEndpoint(
            endpoint_id="ep:dm1a",
            page_index=10,
            profile_id="detail_installation_profile",
            endpoint_kind="rack_component",
            detector_class_id="patch_panel_row",
            symbol_instance_ids=("dm1",),
            detail_region_id="dr:dm1",
            pseudo_page_id="pp:dm1",
            confidence=0.83,
            status="inferred",
            metadata={"has_note_support": True, "legend_entry_id": "leg:pp"},
        ),
        SiteSchematicTopologyEndpoint(
            endpoint_id="ep:dm1b",
            page_index=10,
            profile_id="detail_installation_profile",
            endpoint_kind="pathway_runway",
            detector_class_id="ladder_rack_cable_runway",
            symbol_instance_ids=("dm1",),
            detail_region_id="dr:dm1",
            pseudo_page_id="pp:dm1",
            confidence=0.83,
            status="inferred",
            metadata={"has_note_support": True},
        ),
    )
    relations = (
        SiteSchematicTopologyRelation(
            relation_id="rel:dm1",
            page_index=10,
            profile_id="detail_installation_profile",
            relation_kind="pathway_attachment",
            source_endpoint_id="ep:dm1a",
            target_endpoint_id="ep:dm1b",
            confidence=0.9,
            status="inferred",
        ),
    )
    findings, _, _, _, _, _ = build_bounded_graph_reasoning(
        graph=_graph_with_symbols(),
        symbol_instances=symbols,
        symbol_links=links,
        topology_endpoints=endpoints,
        topology_relations=relations,
    )
    anchor_rows = [row for row in findings if row.finding_type == "anchor_reconciliation"]
    assert anchor_rows
    assert any(row.metadata.get("anchor_grounding_tier") == "mixed" for row in anchor_rows)
    assert all(row.status != "contradicted" for row in anchor_rows)

