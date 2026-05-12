from __future__ import annotations

from orbitbrief_core.parser.site_schematic.models import (
    SiteSchematicSymbolInstance,
    SiteSchematicSymbolLink,
    SiteSchematicTopologyEndpoint,
    SiteSchematicTopologyRelation,
)
from orbitbrief_core.parser.site_schematic.symbols.linker import strengthen_symbol_links_with_topology


def test_strengthens_detail_installation_anchor_when_inferred_local_support_exists() -> None:
    symbols = (
        SiteSchematicSymbolInstance(
            instance_id="s1",
            page_index=1,
            token="JACK",
            primitive_kind="symbol",
            text="telecomm jack",
            confidence=0.86,
            metadata={"detector_profile_id": "detail_installation_profile", "detector_class_id": "telecomm_jack_tag"},
        ),
    )
    links = (
        SiteSchematicSymbolLink(
            link_id="l1",
            page_index=1,
            instance_id="s1",
            symbol_token="JACK",
            status="detected_but_unmapped",
            confidence=0.24,
        ),
    )
    endpoints = (
        SiteSchematicTopologyEndpoint(
            endpoint_id="ep1",
            page_index=1,
            profile_id="detail_installation_profile",
            endpoint_kind="termination_point",
            detector_class_id="telecomm_jack_tag",
            symbol_instance_ids=("s1",),
            detail_region_id="dr:1",
            pseudo_page_id="pp:1",
            confidence=0.82,
            status="inferred",
            metadata={"has_note_support": True},
        ),
        SiteSchematicTopologyEndpoint(
            endpoint_id="ep2",
            page_index=1,
            profile_id="detail_installation_profile",
            endpoint_kind="pathway_runway",
            detector_class_id="ladder_rack_cable_runway",
            symbol_instance_ids=("s1",),
            detail_region_id="dr:1",
            pseudo_page_id="pp:1",
            confidence=0.86,
            status="inferred",
            metadata={"has_note_support": True, "legend_entry_id": "legend:1"},
        ),
    )
    relations = (
        SiteSchematicTopologyRelation(
            relation_id="rel1",
            page_index=1,
            profile_id="detail_installation_profile",
            relation_kind="pathway_attachment",
            source_endpoint_id="ep1",
            target_endpoint_id="ep2",
            confidence=0.92,
            status="inferred",
        ),
    )
    strengthened, diag = strengthen_symbol_links_with_topology(
        symbol_instances=symbols,
        symbol_links=links,
        topology_endpoints=endpoints,
        topology_relations=relations,
    )
    assert strengthened[0].status in {"weakly_linked", "linked"}
    assert strengthened[0].confidence > links[0].confidence
    assert (strengthened[0].metadata or {}).get("grounding_strengthened") is True
    assert diag.get("strengthened_anchor_count", 0) >= 1


def test_does_not_strengthen_when_only_unresolved_topology_exists() -> None:
    symbols = (
        SiteSchematicSymbolInstance(
            instance_id="s2",
            page_index=1,
            token="JACK",
            primitive_kind="symbol",
            text="telecomm jack",
            confidence=0.86,
            metadata={"detector_profile_id": "detail_installation_profile", "detector_class_id": "telecomm_jack_tag"},
        ),
    )
    links = (
        SiteSchematicSymbolLink(link_id="l2", page_index=1, instance_id="s2", symbol_token="JACK", status="detected_but_unmapped", confidence=0.24),
    )
    endpoints = (
        SiteSchematicTopologyEndpoint(
            endpoint_id="ep3",
            page_index=1,
            profile_id="detail_installation_profile",
            endpoint_kind="termination_point",
            detector_class_id="telecomm_jack_tag",
            symbol_instance_ids=("s2",),
            detail_region_id="dr:2",
            confidence=0.71,
            status="unresolved",
            metadata={"has_note_support": True},
        ),
    )
    relations = (
        SiteSchematicTopologyRelation(
            relation_id="rel2",
            page_index=1,
            profile_id="detail_installation_profile",
            relation_kind="pathway_attachment",
            source_endpoint_id="ep3",
            target_endpoint_id="ep3",
            confidence=0.7,
            status="unresolved",
        ),
    )
    strengthened, diag = strengthen_symbol_links_with_topology(
        symbol_instances=symbols,
        symbol_links=links,
        topology_endpoints=endpoints,
        topology_relations=relations,
    )
    assert strengthened[0].status == "detected_but_unmapped"
    assert diag.get("strengthened_anchor_count", 0) == 0
    assert diag.get("rejected_samples")


def test_uses_inferred_endpoint_detector_class_when_symbol_class_missing() -> None:
    symbols = (
        SiteSchematicSymbolInstance(
            instance_id="s3",
            page_index=1,
            token="RIS",
            primitive_kind="symbol",
            text="riser endpoint",
            confidence=0.86,
            metadata={"detector_profile_id": "riser_profile"},
        ),
    )
    links = (
        SiteSchematicSymbolLink(
            link_id="l3",
            page_index=1,
            instance_id="s3",
            symbol_token="RIS",
            status="detected_but_unmapped",
            confidence=0.24,
        ),
    )
    endpoints = (
        SiteSchematicTopologyEndpoint(
            endpoint_id="ep4",
            page_index=1,
            profile_id="riser_profile",
            endpoint_kind="riser_node",
            detector_class_id="riser_endpoint",
            symbol_instance_ids=("s3",),
            detail_region_id="dr:3",
            subregion_id="sr:3",
            confidence=0.9,
            status="inferred",
            metadata={"has_note_support": True},
        ),
        SiteSchematicTopologyEndpoint(
            endpoint_id="ep5",
            page_index=1,
            profile_id="riser_profile",
            endpoint_kind="riser_node",
            detector_class_id="riser_endpoint",
            symbol_instance_ids=("s3",),
            detail_region_id="dr:3",
            subregion_id="sr:3",
            confidence=0.88,
            status="inferred",
            metadata={"has_note_support": True},
        ),
    )
    relations = (
        SiteSchematicTopologyRelation(
            relation_id="rel3",
            page_index=1,
            profile_id="riser_profile",
            relation_kind="riser_continuity",
            source_endpoint_id="ep4",
            target_endpoint_id="ep5",
            confidence=0.9,
            status="inferred",
        ),
    )
    strengthened, _ = strengthen_symbol_links_with_topology(
        symbol_instances=symbols,
        symbol_links=links,
        topology_endpoints=endpoints,
        topology_relations=relations,
    )
    assert strengthened[0].status in {"weakly_linked", "linked"}
