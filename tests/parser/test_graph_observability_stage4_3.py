from __future__ import annotations

from dataclasses import dataclass

from orbitbrief_core.parser.graph.indices import GraphIndices
from orbitbrief_core.parser.graph.base import (
    build_graph_inspection_bundle,
    get_edge_provenance,
    get_node_provenance,
    get_packet_seed_diagnostics,
    summarize_graph,
)
from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.runtime import parse_and_packetize


@dataclass(frozen=True, slots=True)
class _ManifestStub:
    pack_id: str = "professional_services_text"
    role_id: str = "transcript_or_notes"


@dataclass(frozen=True, slots=True)
class _CompiledPackStub:
    manifest: _ManifestStub
    parser_profiles: dict


def _compiled_pack_stub() -> _CompiledPackStub:
    rows = [
        {"modality": "txt", "parser_profile_id": "parser:professional_services_text:txt"},
        {"modality": "md", "parser_profile_id": "parser:professional_services_text:md"},
        {"modality": "email_export", "parser_profile_id": "parser:professional_services_text:email_export"},
    ]
    return _CompiledPackStub(manifest=_ManifestStub(), parser_profiles={"rows": rows})


def _sample_parse():
    text = (
        "09:00 Alice: Deliverable is migration runbook.\n"
        "09:05 Alice: Risk is permit delay.\n"
        "09:10 Bob: Schedule is next month.\n"
        "09:12 Bob: Open question on site count?"
    )
    result = parse_and_packetize(
        router_input=RouterInput(doc_id="graph_observe_4_3_001", filename="call.txt", raw_text_preview=text, metadata={"raw_text": text}),
        compiled_pack=_compiled_pack_stub(),
    )
    return result.document_parse


def test_graph_summary_reports_counts_by_family_and_pass() -> None:
    parsed = _sample_parse()
    summary = summarize_graph(parsed)

    assert summary.node_counts_by_family.get("span", 0) >= 1
    assert isinstance(summary.edge_counts_by_family, dict)
    assert isinstance(summary.edge_counts_by_pass, dict)
    assert summary.packet_seed_count >= 0
    assert summary.cue_attachment_count >= 0


def test_provenance_lookup_for_node_and_edge() -> None:
    parsed = _sample_parse()
    assert parsed.evidence_spans
    node = get_node_provenance(parsed, parsed.evidence_spans[0].span_id)
    assert node is not None
    assert node.node_family == "span"
    assert node.source_span_ids

    assert parsed.evidence_graph.edges
    first_edge = parsed.evidence_graph.edges[0]
    edge_id = f"edge:evidence:000000:{first_edge.source_span_id}:{first_edge.target_span_id}:{first_edge.relation_type.value}"
    edge = get_edge_provenance(parsed, edge_id)
    assert edge is not None
    assert edge.source_pass
    assert isinstance(edge.reason_codes, tuple)


def test_packet_seed_diagnostics_and_inspection_bundle() -> None:
    parsed = _sample_parse()
    packet_diagnostics = get_packet_seed_diagnostics(parsed)
    assert packet_diagnostics
    assert packet_diagnostics[0].anchor_span_ids
    assert packet_diagnostics[0].source_pass

    bundle = build_graph_inspection_bundle(parsed)
    assert isinstance(bundle.summary.edge_counts_by_family, dict)
    assert bundle.packet_seed_diagnostics
    assert bundle.node_provenance_by_id
    assert bundle.edge_provenance_by_id
    top_seeds = bundle.top_packet_seed_diagnostics(limit=5)
    assert top_seeds
    assert top_seeds[0].strength_score >= 0.0
    assert top_seeds[0].neighborhood_size >= 0


def test_indices_support_composable_lookup_paths() -> None:
    parsed = _sample_parse()
    indices = GraphIndices.from_parse(parsed)
    assert indices.edge_ids_by_pass_family
    assert indices.edge_ids_by_node_id
    first_span_id = parsed.evidence_spans[0].span_id
    assert first_span_id in indices.source_span_id_to_node_ids
    # composable chain: span -> node ids -> edge ids
    linked_nodes = indices.source_span_id_to_node_ids[first_span_id]
    assert linked_nodes
    span_edge_ids = indices.source_span_id_to_edge_ids.get(first_span_id, ())
    assert isinstance(span_edge_ids, tuple)
    # packet seed lookup by cue/source pass available
    assert isinstance(indices.packet_seed_ids_by_cue_family, dict)
    assert isinstance(indices.packet_seed_ids_by_source_pass, dict)
