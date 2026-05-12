from __future__ import annotations

from orbitbrief_core.parser.site_schematic.graph.build_graph import build_packet_graph
from orbitbrief_core.parser.site_schematic.models import (
    SiteSchematicPage,
    SiteSchematicSymbolInstance,
    SiteSchematicSymbolLink,
)
from orbitbrief_core.parser.site_schematic.topology_extract import build_topology_for_page


def _page() -> SiteSchematicPage:
    return SiteSchematicPage(
        page_index=1,
        page_label="page_1",
        sheet_type="riser_diagram",
        overlay_tags=("low_voltage",),
        zones=(),
        legend_entries=(),
        note_clauses=(),
        room_labels=(),
        equipment_labels=(),
    )


def test_topology_extraction_creates_profile_aware_relations() -> None:
    symbols = (
        SiteSchematicSymbolInstance(
            instance_id="sym:1",
            page_index=1,
            token="RE",
            primitive_kind="symbol",
            text="riser endpoint",
            confidence=0.9,
            overlay_tags=("low_voltage",),
            region_id="reg:riser",
            pseudo_page_id="pp:r1",
            bbox=(0.1, 0.1, 0.18, 0.18),
            metadata={"detector_class_id": "riser_endpoint", "detector_profile_id": "riser_profile"},
        ),
        SiteSchematicSymbolInstance(
            instance_id="sym:2",
            page_index=1,
            token="RW",
            primitive_kind="symbol",
            text="ladder rack runway",
            confidence=0.88,
            overlay_tags=("low_voltage",),
            region_id="reg:riser",
            pseudo_page_id="pp:r1",
            bbox=(0.2, 0.12, 0.3, 0.22),
            metadata={"detector_class_id": "ladder_rack_cable_runway", "detector_profile_id": "riser_profile"},
        ),
    )
    links = (
        SiteSchematicSymbolLink(
            link_id="link:1",
            page_index=1,
            instance_id="sym:1",
            symbol_token="RE",
            status="linked",
            confidence=0.9,
            legend_entry_id="leg:1",
        ),
        SiteSchematicSymbolLink(
            link_id="link:2",
            page_index=1,
            instance_id="sym:2",
            symbol_token="RW",
            status="linked",
            confidence=0.89,
            legend_entry_id="leg:2",
        ),
    )
    endpoints, relations, segments, riser_edges, diag = build_topology_for_page(
        page_index=1,
        sheet_type="riser_diagram",
        symbol_instances=symbols,
        symbol_links=links,
        note_clauses=("Riser continuity between endpoints.",),
    )
    assert endpoints
    assert any(row.relation_kind == "riser_continuity" and row.status == "inferred" for row in relations)
    assert segments
    assert riser_edges
    assert diag["profile_relation_counts"].get("riser_profile", 0) >= 1


def test_topology_extraction_fail_closed_on_weak_evidence() -> None:
    symbols = (
        SiteSchematicSymbolInstance(
            instance_id="sym:w1",
            page_index=1,
            token="DATA",
            primitive_kind="symbol",
            text="data outlet",
            confidence=0.45,
            overlay_tags=("low_voltage",),
            region_id="reg:legend",
            bbox=(0.1, 0.1, 0.18, 0.18),
            metadata={"detector_class_id": "data_outlet", "detector_profile_id": "control_legend_profile"},
        ),
    )
    links = (
        SiteSchematicSymbolLink(
            link_id="link:w1",
            page_index=1,
            instance_id="sym:w1",
            symbol_token="DATA",
            status="detected_but_unmapped",
            confidence=0.3,
        ),
    )
    endpoints, relations, _, _, diag = build_topology_for_page(
        page_index=1,
        sheet_type="legend_symbol",
        symbol_instances=symbols,
        symbol_links=links,
        note_clauses=(),
    )
    assert not relations
    assert not endpoints
    assert diag["profile_abstain_counts"].get("control_legend_profile", 0) >= 1


def test_graph_ingests_topology_nodes_and_edges() -> None:
    symbols = (
        SiteSchematicSymbolInstance(
            instance_id="sym:1",
            page_index=1,
            token="RE",
            primitive_kind="symbol",
            text="riser endpoint",
            confidence=0.9,
            overlay_tags=("low_voltage",),
            region_id="reg:riser",
            bbox=(0.1, 0.1, 0.18, 0.18),
            metadata={"detector_class_id": "riser_endpoint", "detector_profile_id": "riser_profile"},
        ),
        SiteSchematicSymbolInstance(
            instance_id="sym:2",
            page_index=1,
            token="RW",
            primitive_kind="symbol",
            text="ladder rack runway",
            confidence=0.88,
            overlay_tags=("low_voltage",),
            region_id="reg:riser",
            bbox=(0.2, 0.12, 0.3, 0.22),
            metadata={"detector_class_id": "ladder_rack_cable_runway", "detector_profile_id": "riser_profile"},
        ),
    )
    links = (
        SiteSchematicSymbolLink(link_id="link:1", page_index=1, instance_id="sym:1", symbol_token="RE", status="linked", confidence=0.9),
        SiteSchematicSymbolLink(link_id="link:2", page_index=1, instance_id="sym:2", symbol_token="RW", status="linked", confidence=0.9),
    )
    endpoints, relations, _, _, _ = build_topology_for_page(
        page_index=1,
        sheet_type="riser_diagram",
        symbol_instances=symbols,
        symbol_links=links,
        note_clauses=("riser and rack continuity",),
    )
    graph = build_packet_graph(
        pages=(_page(),),
        regions=(),
        legend_entries=(),
        abbreviations=(),
        drawing_index_rows=(),
        note_clauses=(),
        mounting_rules=(),
        termination_rules=(),
        environmental_requirements=(),
        grounding_requirements=(),
        testing_requirements=(),
        labeling_requirements=(),
        responsibility_assignments=(),
        cable_rules=(),
        pathway_rules=(),
        service_loop_requirements=(),
        device_instances=(),
        outlet_instances=(),
        rooms=(),
        closets=(),
        racks=(),
        riser_edges=(),
        symbol_instances=symbols,
        symbol_links=links,
        topology_endpoints=endpoints,
        topology_relations=relations,
    )
    assert any(node.kind == "topology_endpoint" for node in graph.nodes)
    assert any(edge.relation in {"riser_continuity", "rack_connectivity", "mixed_detail_continuity"} for edge in graph.edges)


def test_topology_profile_evidence_expands_in_installation_context() -> None:
    symbols = (
        SiteSchematicSymbolInstance(
            instance_id="sym:i1",
            page_index=2,
            token="JH",
            primitive_kind="symbol",
            text="j-hook pathway",
            confidence=0.86,
            overlay_tags=("low_voltage",),
            region_id="reg:install",
            pseudo_page_id="pp:install",
            bbox=(0.1, 0.1, 0.2, 0.2),
            metadata={
                "detector_class_id": "j_hook_pathway_symbol",
                "detector_profile_id": "detail_installation_profile",
                "region_kind": "installation_region",
                "pseudo_page_role": "installation_detail",
            },
        ),
        SiteSchematicSymbolInstance(
            instance_id="sym:i2",
            page_index=2,
            token="RW",
            primitive_kind="symbol",
            text="ladder runway",
            confidence=0.88,
            overlay_tags=("low_voltage",),
            region_id="reg:install",
            pseudo_page_id="pp:install",
            bbox=(0.22, 0.12, 0.33, 0.23),
            metadata={
                "detector_class_id": "ladder_rack_cable_runway",
                "detector_profile_id": "detail_installation_profile",
                "region_kind": "installation_region",
                "pseudo_page_role": "installation_detail",
            },
        ),
    )
    links = (
        SiteSchematicSymbolLink(
            link_id="link:i1",
            page_index=2,
            instance_id="sym:i1",
            symbol_token="JH",
            status="weakly_linked",
            confidence=0.7,
            legend_entry_id="leg:i1",
        ),
        SiteSchematicSymbolLink(
            link_id="link:i2",
            page_index=2,
            instance_id="sym:i2",
            symbol_token="RW",
            status="linked",
            confidence=0.84,
            legend_entry_id="leg:i2",
        ),
    )
    endpoints, relations, _, _, diag = build_topology_for_page(
        page_index=2,
        sheet_type="installation_detail",
        symbol_instances=symbols,
        symbol_links=links,
        note_clauses=("Installation detail shows j-hook support and pathway continuation.",),
    )
    assert any(ep.status == "inferred" for ep in endpoints)
    assert any(rel.relation_kind == "pathway_attachment" for rel in relations)
    assert diag["accepted_endpoint_samples"]
    assert diag["accepted_relation_samples"] or diag["rejected_relation_samples"]
    assert all("reasons" in row for row in diag["accepted_endpoint_samples"])


def test_topology_infers_class_from_profile_token_hints() -> None:
    symbols = (
        SiteSchematicSymbolInstance(
            instance_id="sym:t1",
            page_index=3,
            token="RIS",
            primitive_kind="symbol",
            text="RIS",
            confidence=0.84,
            overlay_tags=("low_voltage",),
            region_id="reg:riser",
            pseudo_page_id="pp:riser",
            bbox=(0.1, 0.1, 0.18, 0.18),
            metadata={"detector_profile_id": "riser_profile", "region_kind": "riser_region", "pseudo_page_role": "riser"},
        ),
        SiteSchematicSymbolInstance(
            instance_id="sym:t2",
            page_index=3,
            token="PP",
            primitive_kind="symbol",
            text="PP",
            confidence=0.82,
            overlay_tags=("low_voltage",),
            region_id="reg:riser",
            pseudo_page_id="pp:riser",
            bbox=(0.2, 0.12, 0.28, 0.2),
            metadata={"detector_profile_id": "riser_profile", "region_kind": "riser_region", "pseudo_page_role": "riser"},
        ),
    )
    links = (
        SiteSchematicSymbolLink(link_id="link:t1", page_index=3, instance_id="sym:t1", symbol_token="RIS", status="linked", confidence=0.82),
        SiteSchematicSymbolLink(link_id="link:t2", page_index=3, instance_id="sym:t2", symbol_token="PP", status="linked", confidence=0.81),
    )
    endpoints, _, _, _, diag = build_topology_for_page(
        page_index=3,
        sheet_type="riser_diagram",
        symbol_instances=symbols,
        symbol_links=links,
        note_clauses=("Riser continuity and patch panel routing.",),
    )
    assert endpoints
    assert any(ep.detector_class_id == "riser_endpoint" for ep in endpoints)
    assert any(ep.detector_class_id == "patch_panel_row" for ep in endpoints)
    assert any((ep.metadata or {}).get("derived_detector_class_id") for ep in endpoints)
    assert diag["accepted_endpoint_samples"]


def test_topology_structural_profile_can_promote_detected_unmapped_with_strong_context() -> None:
    symbols = (
        SiteSchematicSymbolInstance(
            instance_id="sym:s1",
            page_index=4,
            token="RIS",
            primitive_kind="symbol",
            text="riser endpoint",
            confidence=0.86,
            overlay_tags=("low_voltage",),
            region_id="reg:riser",
            bbox=(0.10, 0.10, 0.18, 0.18),
            metadata={"detector_class_id": "riser_endpoint", "detector_profile_id": "riser_profile"},
        ),
        SiteSchematicSymbolInstance(
            instance_id="sym:s2",
            page_index=4,
            token="RW",
            primitive_kind="symbol",
            text="ladder runway",
            confidence=0.85,
            overlay_tags=("low_voltage",),
            region_id="reg:riser",
            bbox=(0.19, 0.11, 0.29, 0.21),
            metadata={"detector_class_id": "ladder_rack_cable_runway", "detector_profile_id": "riser_profile"},
        ),
    )
    links = (
        SiteSchematicSymbolLink(
            link_id="link:s1",
            page_index=4,
            instance_id="sym:s1",
            symbol_token="RIS",
            status="detected_but_unmapped",
            confidence=0.58,
        ),
        SiteSchematicSymbolLink(
            link_id="link:s2",
            page_index=4,
            instance_id="sym:s2",
            symbol_token="RW",
            status="detected_but_unmapped",
            confidence=0.57,
        ),
    )
    endpoints, relations, _, _, diag = build_topology_for_page(
        page_index=4,
        sheet_type="riser_diagram",
        symbol_instances=symbols,
        symbol_links=links,
        note_clauses=("Riser trunk and runway continuity.",),
    )
    assert any(ep.status == "inferred" for ep in endpoints)
    assert any(rel.status == "inferred" for rel in relations)
    assert any("structural_profile_context_support" in (ep.metadata or {}).get("evidence_reasons", ()) for ep in endpoints)
    assert any("structural_profile_context_support" in tuple(row.get("reasons", ())) for row in diag["accepted_endpoint_samples"])


def test_topology_detail_installation_bridge_promotes_termination_anchor_and_relation() -> None:
    symbols = (
        SiteSchematicSymbolInstance(
            instance_id="sym:d1",
            page_index=5,
            token="JH",
            primitive_kind="symbol",
            text="j-hook support",
            confidence=0.84,
            overlay_tags=("low_voltage",),
            region_id="reg:install",
            pseudo_page_id="pp:install",
            bbox=(0.12, 0.12, 0.2, 0.2),
            metadata={
                "detector_class_id": "j_hook_pathway_symbol",
                "detector_profile_id": "detail_installation_profile",
                "detail_region_id": "dr:1",
                "subregion_id": "sr:1",
            },
        ),
        SiteSchematicSymbolInstance(
            instance_id="sym:d2",
            page_index=5,
            token="JACK",
            primitive_kind="symbol",
            text="telecomm jack",
            confidence=0.72,
            overlay_tags=("low_voltage",),
            region_id="reg:install",
            pseudo_page_id="pp:install",
            bbox=(0.21, 0.13, 0.3, 0.22),
            metadata={
                "detector_class_id": "telecomm_jack_tag",
                "detector_profile_id": "detail_installation_profile",
                "detail_region_id": "dr:1",
                "subregion_id": "sr:1",
            },
        ),
    )
    links = (
        SiteSchematicSymbolLink(
            link_id="link:d1",
            page_index=5,
            instance_id="sym:d1",
            symbol_token="JH",
            status="detected_but_unmapped",
            confidence=0.24,
        ),
        SiteSchematicSymbolLink(
            link_id="link:d2",
            page_index=5,
            instance_id="sym:d2",
            symbol_token="JACK",
            status="detected_but_unmapped",
            confidence=0.24,
        ),
    )
    endpoints, relations, _, _, diag = build_topology_for_page(
        page_index=5,
        sheet_type="installation_detail",
        symbol_instances=symbols,
        symbol_links=links,
        note_clauses=("Installation detail with j-hook pathway support and jack termination.",),
    )
    promoted = [ep for ep in endpoints if ep.detector_class_id == "telecomm_jack_tag"]
    assert promoted
    assert promoted[0].status == "inferred"
    assert (promoted[0].metadata or {}).get("grounding_topology_bridge_rule") == "detail_installation_termination_locality_bridge_v1"
    assert any(rel.status == "inferred" and rel.profile_id == "detail_installation_profile" for rel in relations)
    assert diag["endpoint_bridge_promotions"].get("detail_installation_profile", 0) >= 1
    assert diag["promoted_endpoint_samples"]


def test_topology_detail_installation_bridge_remains_fail_closed_without_locality() -> None:
    symbols = (
        SiteSchematicSymbolInstance(
            instance_id="sym:f1",
            page_index=6,
            token="JH",
            primitive_kind="symbol",
            text="j-hook support",
            confidence=0.84,
            overlay_tags=("low_voltage",),
            region_id="reg:install-a",
            pseudo_page_id="pp:a",
            bbox=(0.05, 0.05, 0.12, 0.12),
            metadata={
                "detector_class_id": "j_hook_pathway_symbol",
                "detector_profile_id": "detail_installation_profile",
                "detail_region_id": "dr:a",
                "subregion_id": "sr:a",
            },
        ),
        SiteSchematicSymbolInstance(
            instance_id="sym:f2",
            page_index=6,
            token="JACK",
            primitive_kind="symbol",
            text="telecomm jack",
            confidence=0.72,
            overlay_tags=("low_voltage",),
            region_id="reg:install-b",
            pseudo_page_id="pp:b",
            bbox=(0.78, 0.78, 0.9, 0.9),
            metadata={
                "detector_class_id": "telecomm_jack_tag",
                "detector_profile_id": "detail_installation_profile",
                "detail_region_id": "dr:b",
                "subregion_id": "sr:b",
            },
        ),
    )
    links = (
        SiteSchematicSymbolLink(link_id="link:f1", page_index=6, instance_id="sym:f1", symbol_token="JH", status="detected_but_unmapped", confidence=0.24),
        SiteSchematicSymbolLink(link_id="link:f2", page_index=6, instance_id="sym:f2", symbol_token="JACK", status="detected_but_unmapped", confidence=0.24),
    )
    endpoints, relations, _, _, diag = build_topology_for_page(
        page_index=6,
        sheet_type="installation_detail",
        symbol_instances=symbols,
        symbol_links=links,
        note_clauses=("Installation detail with support and termination text.",),
    )
    jack = next(ep for ep in endpoints if ep.detector_class_id == "telecomm_jack_tag")
    assert jack.status == "unresolved"
    assert not any(rel.status == "inferred" and rel.profile_id == "detail_installation_profile" for rel in relations)
    assert diag["endpoint_bridge_promotions"].get("detail_installation_profile", 0) == 0
