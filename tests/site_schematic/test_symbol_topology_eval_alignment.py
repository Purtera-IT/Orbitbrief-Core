from __future__ import annotations

from dataclasses import replace

from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.site_schematic import build_site_schematic_bundle_from_router_input
from orbitbrief_core.parser.site_schematic.models import SiteSchematicTopologyEndpoint, SiteSchematicTopologyRelation
from orbitbrief_core.parser.site_schematic.symbols.benchmark import create_symbol_benchmark_seed, run_symbol_benchmark, run_topology_benchmark
from orbitbrief_core.parser.site_schematic.topology_eval import build_aligned_symbol_topology_kpi_view


SAMPLE_TEXT = """
<PARSED TEXT FOR PAGE: 1 / 1>
Riser endpoint and ladder rack continuity detail.
""".strip()


def test_symbol_kpi_is_unchanged_by_topology_additions() -> None:
    bundle = build_site_schematic_bundle_from_router_input(
        RouterInput(
            doc_id="topo-align",
            filename="topo-align.pdf",
            mime_type="application/pdf",
            metadata={"full_text": SAMPLE_TEXT},
        )
    )
    benchmark = create_symbol_benchmark_seed(bundle=bundle, packet_id="topo-align")
    base = run_symbol_benchmark(bundle=bundle, benchmark=benchmark)
    enriched = replace(
        bundle,
        topology_endpoints=(
            SiteSchematicTopologyEndpoint(
                endpoint_id="ep:1",
                page_index=1,
                profile_id="riser_profile",
                endpoint_kind="riser_endpoint",
                detector_class_id="riser_endpoint",
                confidence=0.82,
                status="inferred",
            ),
        ),
        topology_relations=(
            SiteSchematicTopologyRelation(
                relation_id="rel:1",
                page_index=1,
                profile_id="riser_profile",
                relation_kind="riser_continuity",
                source_endpoint_id="ep:1",
                target_endpoint_id="ep:1",
                confidence=0.72,
                status="inferred",
            ),
        ),
    )
    after = run_symbol_benchmark(bundle=enriched, benchmark=benchmark)
    assert base["candidate_match_rate"] == after["candidate_match_rate"]
    assert base["legend_grounding_rate"] == after["legend_grounding_rate"]
    assert base["unresolved_or_conflicting_rate"] == after["unresolved_or_conflicting_rate"]


def test_topology_kpi_reports_additive_counts() -> None:
    bundle = build_site_schematic_bundle_from_router_input(
        RouterInput(
            doc_id="topo-kpi",
            filename="topo-kpi.pdf",
            mime_type="application/pdf",
            metadata={"full_text": SAMPLE_TEXT},
        )
    )
    enriched = replace(
        bundle,
        topology_endpoints=(
            SiteSchematicTopologyEndpoint(
                endpoint_id="ep:1",
                page_index=1,
                profile_id="detail_installation_profile",
                endpoint_kind="pathway_support",
                detector_class_id="j_hook_pathway_symbol",
                confidence=0.61,
                status="unresolved",
            ),
        ),
        topology_relations=(
            SiteSchematicTopologyRelation(
                relation_id="rel:1",
                page_index=1,
                profile_id="detail_installation_profile",
                relation_kind="pathway_attachment",
                source_endpoint_id="ep:1",
                target_endpoint_id="ep:1",
                confidence=0.44,
                status="unresolved",
            ),
        ),
    )
    report = run_topology_benchmark(bundle=enriched)
    assert report["kpi_view"] == "additive_topology"
    assert report["topology_endpoint_count"] == 1
    assert report["topology_relation_count"] == 1
    assert report["topology_relation_abstain_count"] == 1
    assert report["profile_topology_abstain_counts"].get("detail_installation_profile", 0) == 1


def test_alignment_view_exposes_mode_and_split_kpis() -> None:
    bundle = build_site_schematic_bundle_from_router_input(
        RouterInput(
            doc_id="topo-view",
            filename="topo-view.pdf",
            mime_type="application/pdf",
            metadata={"full_text": SAMPLE_TEXT},
        )
    )
    benchmark = create_symbol_benchmark_seed(bundle=bundle, packet_id="topo-view")
    aligned = build_aligned_symbol_topology_kpi_view(bundle=bundle, benchmark=benchmark)
    assert aligned["run_mode"] == "canonical_calibrated"
    assert aligned["topology_additive_only"] is True
    assert aligned["diagnostics"]["topology_perturbs_symbol_scores"] is False
    assert aligned["symbol_kpi"]["kpi_view"] == "canonical_symbol"
    assert aligned["topology_kpi"]["kpi_view"] == "additive_topology"

