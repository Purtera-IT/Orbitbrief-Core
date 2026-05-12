from __future__ import annotations

from dataclasses import dataclass

from orbitbrief_core.parser.graph.cad_signals import pair_signals
from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.runtime import parse_and_packetize
from orbitbrief_core.parser.shared.types import BBox, ContainerType, DiscourseType, EvidenceSpan


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
        {"modality": "docx", "parser_profile_id": "parser:professional_services_text:docx"},
        {"modality": "email_export", "parser_profile_id": "parser:professional_services_text:email_export"},
        {"modality": "pdf_text", "parser_profile_id": "parser:professional_services_text:pdf_text"},
        {"modality": "pdf_ocr", "parser_profile_id": "parser:professional_services_text:pdf_ocr"},
        {"modality": "cad_sheet", "parser_profile_id": "parser:professional_services_text:cad_sheet"},
        {"modality": "schematic", "parser_profile_id": "parser:professional_services_text:schematic"},
        {"modality": "floorplan", "parser_profile_id": "parser:professional_services_text:floorplan"},
        {"modality": "drawing_packet", "parser_profile_id": "parser:professional_services_text:drawing_packet"},
    ]
    return _CompiledPackStub(manifest=_ManifestStub(), parser_profiles={"rows": rows})


def _run_cad_graph():
    compiled = _compiled_pack_stub()
    raw_text = (
        "Sheet Number: A-301\n"
        "Sheet Title: Network Support Plan\n"
        "Customer: Example Health\n"
        "Rev A: Added MDF support areas\n"
        "Note 1: Escort required for after-hours access.\n"
        "Callout 7\n"
        "MDF-01\n"
        "RACK-1\n"
        "SW-1\n"
        "12 ft\n"
    )
    result = parse_and_packetize(
        router_input=RouterInput(
            doc_id="cad_graph_11_5_001",
            filename="support_plan.pdf",
            mime_type="application/pdf",
            raw_text_preview=raw_text,
            metadata={
                "cad_hint": True,
                "raw_text": raw_text,
                "cad_regions": [
                    {"region_id": "tb1", "kind": "title_block", "text": "Sheet Number: A-301", "page_index": 0, "bbox": [0.01, 0.01, 0.2, 0.1], "confidence": 0.9},
                    {"region_id": "tb2", "kind": "title_block", "text": "Sheet Title: Network Support Plan", "page_index": 0, "bbox": [0.02, 0.11, 0.28, 0.18], "confidence": 0.9},
                    {"region_id": "rv1", "kind": "revision_block", "text": "Rev A: Added MDF support areas", "page_index": 0, "bbox": [0.72, 0.05, 0.95, 0.14], "confidence": 0.86},
                    {"region_id": "n1", "kind": "note_block", "text": "Note 1: Escort required for after-hours access.", "page_index": 0, "bbox": [0.15, 0.25, 0.5, 0.35], "confidence": 0.85},
                    {"region_id": "c1", "kind": "callout", "text": "Callout 7", "page_index": 0, "bbox": [0.51, 0.33, 0.58, 0.38], "confidence": 0.81},
                    {"region_id": "z1", "kind": "room_label", "text": "MDF-01", "page_index": 0, "bbox": [0.59, 0.28, 0.69, 0.36], "confidence": 0.83},
                    {"region_id": "z2", "kind": "room_label", "text": "IDF-02", "page_index": 0, "bbox": [0.68, 0.27, 0.78, 0.35], "confidence": 0.82},
                    {"region_id": "e1", "kind": "equipment_label", "text": "RACK-1", "page_index": 0, "bbox": [0.62, 0.38, 0.72, 0.45], "confidence": 0.8},
                    {"region_id": "e2", "kind": "equipment_label", "text": "SW-1", "page_index": 0, "bbox": [0.7, 0.39, 0.8, 0.46], "confidence": 0.8},
                    {"region_id": "d1", "kind": "dimension_text", "text": "12 ft", "page_index": 0, "bbox": [0.58, 0.48, 0.67, 0.53], "confidence": 0.78},
                    {"region_id": "lg1", "kind": "legend", "text": "Legend: Symbol table", "page_index": 0, "bbox": [0.03, 0.72, 0.32, 0.89], "confidence": 0.89},
                ],
            },
        ),
        compiled_pack=compiled,
    )
    return result.document_parse


def test_cad_graph_emits_stage5_edge_families() -> None:
    parsed = _run_cad_graph()
    edge_families = {str(edge.metadata.get("edge_family")) for edge in parsed.evidence_graph.edges}
    assert "same_sheet" in edge_families
    assert "inside_zone" in edge_families
    assert "near" in edge_families
    assert "note_attached_to" in edge_families
    assert "callout_for" in edge_families
    assert "component_in_zone" in edge_families
    assert "component_near_component" in edge_families
    assert "possible_topology_neighbor" in edge_families
    assert "same_title_block" in edge_families
    assert "same_revision_block" in edge_families
    assert "sheet_metadata_for" in edge_families
    assert "revision_metadata_for" in edge_families


def test_cad_graph_suppresses_noise_regions_from_semantic_neighborhoods() -> None:
    parsed = _run_cad_graph()
    noisy_ids = {span.span_id for span in parsed.evidence_spans if bool(span.metadata.get("cad_noise_downgraded"))}
    assert noisy_ids
    cad_semantic_families = {
        "inside_region",
        "inside_zone",
        "near",
        "overlaps",
        "same_title_block",
        "same_revision_block",
        "note_attached_to",
        "callout_for",
        "annotation_for",
        "revision_applies_to",
        "component_in_zone",
        "component_near_component",
        "possible_topology_neighbor",
        "possible_support_area",
        "possible_distribution_room",
        "sheet_metadata_for",
        "sheet_title_for",
        "revision_metadata_for",
    }
    semantic_edges = [
        edge
        for edge in parsed.evidence_graph.edges
        if str(edge.metadata.get("edge_family")) in cad_semantic_families
    ]
    assert all(edge.source_span_id not in noisy_ids and edge.target_span_id not in noisy_ids for edge in semantic_edges)


def test_cad_graph_exposes_deterministic_cad_signals_for_packetizer() -> None:
    parsed = _run_cad_graph()
    signal_rows = parsed.metadata.get("cad_signals")
    assert isinstance(signal_rows, list)
    assert signal_rows
    sample = signal_rows[0]
    assert "left_span_id" in sample
    assert "right_span_id" in sample
    assert "same_sheet" in sample
    assert "overlap_ratio" in sample
    assert "lexical_overlap" in sample


def test_cad_pair_signals_compute_geometry_and_quality_features() -> None:
    left = EvidenceSpan(
        span_id="span:left",
        text="MDF-01",
        normalized_text="mdf-01",
        doc_id="doc:test",
        container_type=ContainerType.DOCUMENT,
        discourse_type=DiscourseType.PROJECT_MEMO,
        section_path=("drawing_sheet", "A-301"),
        chronology_rank=10,
        authority_score=0.82,
        bbox=BBox(0.1, 0.1, 0.5, 0.5),
        metadata={"kind": "room_label"},
    )
    right = EvidenceSpan(
        span_id="span:right",
        text="RACK-1",
        normalized_text="rack-1",
        doc_id="doc:test",
        container_type=ContainerType.DOCUMENT,
        discourse_type=DiscourseType.PROJECT_MEMO,
        section_path=("drawing_sheet", "A-301"),
        chronology_rank=12,
        authority_score=0.78,
        bbox=BBox(0.2, 0.2, 0.45, 0.45),
        metadata={"kind": "equipment_label"},
    )
    sig = pair_signals(left, right, metadata={})
    assert sig.same_sheet is True
    assert sig.near is True
    assert sig.inside_region is True
    assert sig.overlap_ratio > 0.0
    assert sig.ocr_confidence_compatibility > 0.8

