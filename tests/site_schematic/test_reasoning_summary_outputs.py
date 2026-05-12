from __future__ import annotations

from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.site_schematic import build_site_schematic_bundle_from_router_input
from orbitbrief_core.parser.site_schematic.models import (
    SiteSchematicReasoningFinding,
    SiteSchematicSymbolLink,
    SiteSchematicTopologyEndpoint,
    SiteSchematicTopologyRelation,
)
from orbitbrief_core.parser.site_schematic.reasoning import build_reasoning_summaries


def test_build_reasoning_summaries_roll_up_packet_family_and_profile_views() -> None:
    findings = (
        SiteSchematicReasoningFinding(
            finding_id="f1",
            finding_type="anchor_reconciliation",
            severity="high",
            status="needs_review",
            confidence=0.82,
            summary="Data outlet needs structural review",
            triage_bucket="high_priority_review",
            priority_score=74.0,
            evidence_node_ids=("n1",),
            evidence_edge_ids=("e1",),
            evidence_symbol_instance_ids=("s1",),
            evidence_topology_ids=("rel1",),
            page_indices=(2,),
            profile_ids=("detail_installation_profile",),
            metadata={"family": "data_outlet", "anchor_grounding_tier": "strong", "link_status": "weakly_linked"},
        ),
        SiteSchematicReasoningFinding(
            finding_id="f2",
            finding_type="cross_page_consistency",
            severity="medium",
            status="supported",
            confidence=0.78,
            summary="Riser endpoint family stays consistent",
            triage_bucket="informational_supported",
            priority_score=42.0,
            evidence_symbol_instance_ids=("s2",),
            evidence_topology_ids=("ep1",),
            page_indices=(2, 3),
            profile_ids=("riser_profile",),
            metadata={"family": "riser_endpoint", "anchor_grounding_tier": "mixed"},
        ),
    )
    links = (
        SiteSchematicSymbolLink(
            link_id="l1",
            page_index=2,
            instance_id="s1",
            symbol_token="DATA",
            status="weakly_linked",
            confidence=0.76,
        ),
    )
    endpoints = (
        SiteSchematicTopologyEndpoint(
            endpoint_id="ep1",
            page_index=2,
            profile_id="riser_profile",
            endpoint_kind="riser_endpoint",
            detector_class_id="riser_endpoint",
            symbol_instance_ids=("s2",),
            confidence=0.84,
            status="inferred",
        ),
    )
    relations = (
        SiteSchematicTopologyRelation(
            relation_id="rel1",
            page_index=2,
            profile_id="detail_installation_profile",
            relation_kind="pathway_attachment",
            source_endpoint_id="ep1",
            target_endpoint_id="ep1",
            confidence=0.81,
            status="inferred",
        ),
    )
    (
        packet_summary,
        family_summaries,
        review_queue,
        topology_coverage,
        profile_summaries,
    ) = build_reasoning_summaries(
        findings=findings,
        symbol_links=links,
        topology_endpoints=endpoints,
        topology_relations=relations,
    )
    assert packet_summary.total_findings == 2
    assert packet_summary.high_priority_count == 1
    assert family_summaries
    data_outlet = next(row for row in family_summaries if row.family == "data_outlet")
    assert data_outlet.mixed_count == 1
    assert data_outlet.supporting_finding_ids
    assert review_queue.total_items == 1
    assert topology_coverage.inferred_endpoint_count == 1
    assert topology_coverage.inferred_relation_count == 1
    assert any(row.profile_id == "detail_installation_profile" for row in profile_summaries)


def test_bundle_exposes_reasoning_summary_outputs() -> None:
    sample_text = """
<PARSED TEXT FOR PAGE: 1 / 1>
DATA OUTLET
RISER
LEGEND
""".strip()
    bundle = build_site_schematic_bundle_from_router_input(
        RouterInput(
            doc_id="reasoning-summary-bundle",
            filename="reasoning-summary-bundle.pdf",
            mime_type="application/pdf",
            metadata={"full_text": sample_text},
        )
    )
    assert bundle.packet_reasoning_summary is not None
    assert bundle.review_queue_summary is not None
    assert bundle.topology_coverage_summary is not None
    registry = dict(bundle.model_registry)
    summary_block = dict(registry.get("graph_reasoning_summary", {}))
    assert "packet_reasoning_summary" in summary_block
    assert "review_queue_summary" in summary_block
