from __future__ import annotations

from orbitbrief_core.parser.site_schematic.models import (
    SiteSchematicAbbreviationEntry,
    SiteSchematicCableRule,
    SiteSchematicCloset,
    SiteSchematicDetailRegion,
    SiteSchematicDeviceInstance,
    SiteSchematicDrawingIndexRow,
    SiteSchematicEnvironmentalRequirement,
    SiteSchematicGraph,
    SiteSchematicGraphEdge,
    SiteSchematicGraphNode,
    SiteSchematicGroundingRequirement,
    SiteSchematicLabelingRequirement,
    SiteSchematicLegendEntry,
    SiteSchematicMountingRule,
    SiteSchematicNoteClause,
    SiteSchematicPage,
    SiteSchematicPathwayRule,
    SiteSchematicPseudoPage,
    SiteSchematicRack,
    SiteSchematicRegion,
    SiteSchematicResponsibilityAssignment,
    SiteSchematicRiserEdge,
    SiteSchematicRoom,
    SiteSchematicScopedNoteLink,
    SiteSchematicServiceLoopRequirement,
    SiteSchematicSubregion,
    SiteSchematicSymbolInstance,
    SiteSchematicSymbolLink,
    SiteSchematicSymbolResolutionOutcome,
    SiteSchematicTopologyEndpoint,
    SiteSchematicTopologyRelation,
    SiteSchematicTerminationRule,
    SiteSchematicTestingRequirement,
    SiteSchematicOutletInstance,
)


def build_packet_graph(
    *,
    pages: tuple[SiteSchematicPage, ...],
    regions: tuple[SiteSchematicRegion, ...],
    legend_entries: tuple[SiteSchematicLegendEntry, ...],
    abbreviations: tuple[SiteSchematicAbbreviationEntry, ...],
    drawing_index_rows: tuple[SiteSchematicDrawingIndexRow, ...],
    note_clauses: tuple[SiteSchematicNoteClause, ...],
    mounting_rules: tuple[SiteSchematicMountingRule, ...],
    termination_rules: tuple[SiteSchematicTerminationRule, ...],
    environmental_requirements: tuple[SiteSchematicEnvironmentalRequirement, ...],
    grounding_requirements: tuple[SiteSchematicGroundingRequirement, ...],
    testing_requirements: tuple[SiteSchematicTestingRequirement, ...],
    labeling_requirements: tuple[SiteSchematicLabelingRequirement, ...],
    responsibility_assignments: tuple[SiteSchematicResponsibilityAssignment, ...],
    cable_rules: tuple[SiteSchematicCableRule, ...],
    pathway_rules: tuple[SiteSchematicPathwayRule, ...],
    service_loop_requirements: tuple[SiteSchematicServiceLoopRequirement, ...],
    device_instances: tuple[SiteSchematicDeviceInstance, ...],
    outlet_instances: tuple[SiteSchematicOutletInstance, ...],
    rooms: tuple[SiteSchematicRoom, ...],
    closets: tuple[SiteSchematicCloset, ...],
    racks: tuple[SiteSchematicRack, ...],
    riser_edges: tuple[SiteSchematicRiserEdge, ...],
    symbol_instances: tuple[SiteSchematicSymbolInstance, ...],
    symbol_links: tuple[SiteSchematicSymbolLink, ...],
    symbol_resolution_outcomes: tuple[SiteSchematicSymbolResolutionOutcome, ...] = (),
    detail_regions: tuple[SiteSchematicDetailRegion, ...] = (),
    subregions: tuple[SiteSchematicSubregion, ...] = (),
    pseudo_pages: tuple[SiteSchematicPseudoPage, ...] = (),
    scoped_note_links: tuple[SiteSchematicScopedNoteLink, ...] = (),
    topology_endpoints: tuple[SiteSchematicTopologyEndpoint, ...] = (),
    topology_relations: tuple[SiteSchematicTopologyRelation, ...] = (),
) -> SiteSchematicGraph:
    nodes: list[SiteSchematicGraphNode] = []
    edges: list[SiteSchematicGraphEdge] = []

    def add_node(node_id: str, kind: str, label: str, *, page_index: int | None = None, metadata: dict | None = None) -> None:
        nodes.append(SiteSchematicGraphNode(node_id=node_id, kind=kind, label=label, page_index=page_index, metadata=metadata or {}))

    def add_edge(source: str, target: str, relation: str, confidence: float, *, metadata: dict | None = None) -> None:
        edge_id = f"edge:{relation}:{len(edges) + 1}"
        edges.append(
            SiteSchematicGraphEdge(
                edge_id=edge_id,
                source_node_id=source,
                target_node_id=target,
                relation=relation,
                confidence=confidence,
                metadata=metadata or {},
            )
        )

    for page in pages:
        add_node(f"page:{page.page_index}", "page", page.sheet_title or page.page_label, page_index=page.page_index, metadata={"sheet_type": page.sheet_type, "sheet_number": page.sheet_number})
    for region in regions:
        add_node(f"region:{region.region_id}", "region", region.kind, page_index=region.page_index, metadata={"bbox": region.bbox})
        add_edge(f"page:{region.page_index}", f"region:{region.region_id}", "contains", region.confidence)
    for region in detail_regions:
        add_node(
            f"detail_region:{region.detail_region_id}",
            "detail_region",
            region.kind,
            page_index=region.page_index,
            metadata={"bbox": region.bbox, "parent_region_id": region.parent_region_id},
        )
        add_edge(f"page:{region.page_index}", f"detail_region:{region.detail_region_id}", "contains", region.confidence)
        add_edge(f"region:{region.parent_region_id}", f"detail_region:{region.detail_region_id}", "contains", region.confidence)
    for region in subregions:
        add_node(
            f"subregion:{region.subregion_id}",
            "subregion",
            region.role,
            page_index=region.page_index,
            metadata={"bbox": region.bbox, "detail_region_id": region.detail_region_id, "parent_region_id": region.parent_region_id},
        )
        add_edge(f"detail_region:{region.detail_region_id}", f"subregion:{region.subregion_id}", "contains", region.confidence)
    for row in pseudo_pages:
        add_node(
            f"pseudo_page:{row.pseudo_page_id}",
            "pseudo_page",
            row.role,
            page_index=row.page_index,
            metadata={"bbox": row.bbox, "subregion_id": row.subregion_id, "detail_region_id": row.detail_region_id},
        )
        if row.subregion_id:
            add_edge(f"subregion:{row.subregion_id}", f"pseudo_page:{row.pseudo_page_id}", "projected_as", row.confidence)
    for entry in legend_entries:
        add_node(f"legend:{entry.entry_id}", "legend_entry", entry.label, page_index=entry.page_index, metadata={"primitive_kind": entry.primitive_kind, "symbol_token": entry.symbol_token})
        add_edge(f"page:{entry.page_index}", f"legend:{entry.entry_id}", "defined_on_page", entry.confidence)
    for entry in abbreviations:
        add_node(f"abbr:{entry.entry_id}", "abbreviation", f"{entry.token} = {entry.meaning}", page_index=entry.page_index, metadata={"category": entry.category})
        add_edge(f"page:{entry.page_index}", f"abbr:{entry.entry_id}", "defined_on_page", entry.confidence)
    for row in drawing_index_rows:
        node_id = f"drawing_index:{row.row_id}"
        add_node(node_id, "drawing_index_row", f"{row.sheet_number} {row.sheet_title}".strip(), page_index=row.page_index)
        add_edge(f"page:{row.page_index}", node_id, "defined_on_page", row.confidence)
    note_nodes_by_text: dict[str, str] = {}
    for row in note_clauses:
        node_id = f"note:{row.clause_id}"
        add_node(node_id, "note_clause", row.text, page_index=row.page_index, metadata={"status": row.status, "clause_type": row.clause_type})
        add_edge(f"page:{row.page_index}", node_id, "appears_on_sheet", row.confidence)
        note_nodes_by_text[row.text.lower()] = node_id
    for row in rooms:
        node_id = f"room:{row.room_id}"
        add_node(node_id, "room", row.label, page_index=row.page_index, metadata={"room_kind": row.room_kind, "status": row.status})
        add_edge(f"page:{row.page_index}", node_id, "appears_on_sheet", row.confidence)
    for row in closets:
        node_id = f"closet:{row.closet_id}"
        add_node(node_id, "closet", row.label, page_index=row.page_index, metadata={"closet_kind": row.closet_kind, "status": row.status})
        add_edge(f"page:{row.page_index}", node_id, "appears_on_sheet", row.confidence)
    for row in racks:
        node_id = f"rack:{row.rack_id}"
        add_node(node_id, "rack", row.label, page_index=row.page_index, metadata={"status": row.status})
        add_edge(f"page:{row.page_index}", node_id, "appears_on_sheet", row.confidence)
    for row in device_instances:
        node_id = f"device:{row.device_id}"
        add_node(node_id, "device_instance", row.token, page_index=row.page_index, metadata={"device_type": row.device_type, "status": row.status})
        add_edge(f"page:{row.page_index}", node_id, "appears_on_sheet", row.confidence)
    for row in outlet_instances:
        node_id = f"outlet:{row.outlet_id}"
        add_node(node_id, "outlet_instance", row.outlet_type, page_index=row.page_index, metadata={"status": row.status})
        add_edge(f"page:{row.page_index}", node_id, "appears_on_sheet", row.confidence)
    for row in riser_edges:
        node_id = f"topology:{row.edge_id}"
        add_node(node_id, "topology_segment", row.target_label, page_index=row.page_index, metadata={"medium": row.medium, "status": row.status})
        add_edge(f"page:{row.page_index}", node_id, "appears_on_sheet", row.confidence)
    for row in topology_endpoints:
        node_id = f"topology_endpoint:{row.endpoint_id}"
        add_node(
            node_id,
            "topology_endpoint",
            row.endpoint_kind,
            page_index=row.page_index,
            metadata={
                "profile_id": row.profile_id,
                "detector_class_id": row.detector_class_id,
                "status": row.status,
                "region_id": row.region_id,
                "detail_region_id": row.detail_region_id,
                "subregion_id": row.subregion_id,
                "pseudo_page_id": row.pseudo_page_id,
                **dict(row.metadata),
            },
        )
        add_edge(f"page:{row.page_index}", node_id, "appears_on_sheet", row.confidence, metadata={"status": row.status})
        for symbol_id in row.symbol_instance_ids:
            add_edge(f"symbol:{symbol_id}", node_id, "supports_topology_endpoint", row.confidence, metadata={"profile_id": row.profile_id})
    for row in topology_relations:
        node_id = f"topology_relation:{row.relation_id}"
        add_node(
            node_id,
            "topology_relation",
            row.relation_kind,
            page_index=row.page_index,
            metadata={"profile_id": row.profile_id, "status": row.status, **dict(row.metadata)},
        )
        add_edge(f"page:{row.page_index}", node_id, "appears_on_sheet", row.confidence, metadata={"status": row.status})
        add_edge(f"topology_endpoint:{row.source_endpoint_id}", node_id, "topology_source", row.confidence, metadata={"relation_kind": row.relation_kind})
        add_edge(node_id, f"topology_endpoint:{row.target_endpoint_id}", "topology_target", row.confidence, metadata={"relation_kind": row.relation_kind})
        if row.status == "inferred":
            add_edge(
                f"topology_endpoint:{row.source_endpoint_id}",
                f"topology_endpoint:{row.target_endpoint_id}",
                row.relation_kind,
                row.confidence,
                metadata={"profile_id": row.profile_id},
            )
    for symbol in symbol_instances:
        add_node(f"symbol:{symbol.instance_id}", "symbol_instance", symbol.token, page_index=symbol.page_index, metadata={"primitive_kind": symbol.primitive_kind, "bbox": symbol.bbox})
        add_edge(f"page:{symbol.page_index}", f"symbol:{symbol.instance_id}", "contains", symbol.confidence)
        if symbol.region_id:
            add_edge(f"region:{symbol.region_id}", f"symbol:{symbol.instance_id}", "located_in_region", symbol.confidence)
        if symbol.pseudo_page_id:
            add_edge(f"pseudo_page:{symbol.pseudo_page_id}", f"symbol:{symbol.instance_id}", "contains", symbol.confidence)
    for link in symbol_links:
        symbol_node = f"symbol:{link.instance_id}"
        if link.legend_entry_id:
            add_edge(symbol_node, f"legend:{link.legend_entry_id}", "matches_legend", link.confidence, metadata={"status": link.status})
            add_edge(symbol_node, f"legend:{link.legend_entry_id}", "derived_from_legend", link.confidence, metadata={"status": link.status})
        for idx, note in enumerate(link.related_note_clauses, start=1):
            note_id = f"note:{link.page_index}:{idx}:{abs(hash(note)) % 100000}"
            add_node(note_id, "note_clause", note, page_index=link.page_index)
            add_edge(symbol_node, note_id, "related_note", link.confidence)
            add_edge(symbol_node, note_id, "derived_from_note", link.confidence)
        if link.room_label:
            room_id = f"room:{link.page_index}:{abs(hash(link.room_label)) % 100000}"
            add_node(room_id, "room", link.room_label, page_index=link.page_index)
            add_edge(symbol_node, room_id, "located_in", link.confidence)
    for row in symbol_resolution_outcomes:
        node_id = f"symbol_outcome:{row.outcome_id}"
        add_node(
            node_id,
            "symbol_resolution_outcome",
            row.status,
            page_index=row.page_index,
            metadata={
                "instance_id": row.instance_id,
                "legend_entry_id": row.legend_entry_id,
                "reason_codes": list(row.reason_codes),
                **dict(row.metadata),
            },
        )
        add_edge(f"page:{row.page_index}", node_id, "resolution_status", row.confidence, metadata={"status": row.status})
        if row.instance_id:
            add_edge(f"symbol:{row.instance_id}", node_id, "resolution_status", row.confidence, metadata={"status": row.status})
        if row.legend_entry_id:
            add_edge(f"legend:{row.legend_entry_id}", node_id, "resolution_status", row.confidence, metadata={"status": row.status})
    for row in scoped_note_links:
        scoped_node = note_nodes_by_text.get(row.note_text.lower())
        if not scoped_node:
            continue
        if row.scope_level == "page_global":
            continue
        for target in row.scope_targets:
            add_edge(scoped_node, f"pseudo_page:{target}", "scoped_to_subregion", row.confidence, metadata={"status": row.status})
            add_edge(scoped_node, f"pseudo_page:{target}", "scoped_to", row.confidence, metadata={"status": row.status})

    # Rule nodes and policy relations.
    for rows, kind, relation in (
        (mounting_rules, "mounting_rule", "requires"),
        (termination_rules, "termination_rule", "terminates_at"),
        (environmental_requirements, "environmental_requirement", "constrained_by"),
        (grounding_requirements, "grounding_requirement", "grounded_by"),
        (testing_requirements, "testing_requirement", "verified_by"),
        (labeling_requirements, "labeling_requirement", "verified_by"),
        (responsibility_assignments, "responsibility_assignment", "requires"),
        (cable_rules, "cable_rule", "constrained_by"),
        (pathway_rules, "pathway_rule", "routed_to"),
        (service_loop_requirements, "service_loop_requirement", "requires"),
    ):
        for idx, row in enumerate(rows, start=1):
            node_id = f"{kind}:{idx}:{row.page_index}"
            label = getattr(row, "text", "")
            add_node(node_id, kind, label, page_index=row.page_index, metadata={"status": getattr(row, "status", "stated")})
            add_edge(f"page:{row.page_index}", node_id, "defined_by", getattr(row, "confidence", 0.7))
            add_edge(f"page:{row.page_index}", node_id, relation, min(0.92, getattr(row, "confidence", 0.7)))
            for symbol in symbol_instances:
                if symbol.page_index != row.page_index:
                    continue
                add_edge(f"symbol:{symbol.instance_id}", node_id, relation, min(0.9, getattr(row, "confidence", 0.7)))

    for row in riser_edges:
        source_page = f"page:{row.page_index}"
        topo_node = f"topology:{row.edge_id}"
        add_edge(source_page, topo_node, "routed_to", row.confidence, metadata={"medium": row.medium})
        for closet in closets:
            if closet.page_index == row.page_index:
                add_edge(f"closet:{closet.closet_id}", topo_node, "homeruns_to", min(row.confidence + 0.05, 0.9))

    for outlet in outlet_instances:
        for idx, rule in enumerate(termination_rules, start=1):
            if outlet.page_index == rule.page_index:
                add_edge(
                    f"outlet:{outlet.outlet_id}",
                    f"termination_rule:{idx}:{rule.page_index}",
                    "terminates_at",
                    min(outlet.confidence + 0.1, 0.9),
                )
        for idx, rule in enumerate(pathway_rules, start=1):
            if outlet.page_index == rule.page_index:
                add_edge(
                    f"outlet:{outlet.outlet_id}",
                    f"pathway_rule:{idx}:{rule.page_index}",
                    "routed_to",
                    min(outlet.confidence + 0.1, 0.9),
                )

    for rack in racks:
        for idx, ground in enumerate(grounding_requirements, start=1):
            if rack.page_index == ground.page_index:
                add_edge(
                    f"rack:{rack.rack_id}",
                    f"grounding_requirement:{idx}:{ground.page_index}",
                    "grounded_by",
                    min(ground.confidence + 0.05, 0.9),
                )

    return SiteSchematicGraph(nodes=tuple(nodes), edges=tuple(edges))
