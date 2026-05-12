from __future__ import annotations

from dataclasses import dataclass

from orbitbrief_core.parser.router import ParserRouter, RouterInput
from orbitbrief_core.parser.runtime import parse_and_packetize, route_and_parse


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


def _cad_text() -> str:
    return (
        "Sheet Number: A-101\n"
        "Sheet Title: Network Floor Plan\n"
        "Customer: Example Health\n"
        "Site: Dallas Clinic\n"
        "Rev A: Added IDF closet notes\n"
        "Note 1: Escort is required for after-hours access.\n"
        "MDF-01\n"
        "IDF-02\n"
        "AP-01\n"
        "RACK-1\n"
        "12 ft service path\n"
    )


def test_router_classifies_cad_pdf_sheet() -> None:
    compiled = _compiled_pack_stub()
    router = ParserRouter(compiled)
    plan = router.route(
        RouterInput(
            doc_id="cad_router_pdf_001",
            filename="site_floorplan.pdf",
            mime_type="application/pdf",
            raw_text_preview=_cad_text(),
            metadata={"cad_hint": True, "native_text_ratio": 0.93, "ocr_confidence": 0.9},
        )
    )
    assert plan.adapter_chain[0] == "cad_sheet"
    assert plan.strategy_chain == ("site_package",)
    assert plan.packet_policy == "drawing_packets"


def test_router_classifies_schematic_floorplan_and_drawing_packet() -> None:
    compiled = _compiled_pack_stub()
    router = ParserRouter(compiled)

    schematic = router.route(
        RouterInput(
            doc_id="cad_router_image_001",
            filename="network_schematic.png",
            mime_type="image/png",
            raw_text_preview="MDF-01 AP-01",
            metadata={"cad_hint": True},
        )
    )
    assert schematic.adapter_chain[0] == "schematic"

    floorplan = router.route(
        RouterInput(
            doc_id="cad_router_image_002",
            filename="level2_layout.jpg",
            mime_type="image/jpeg",
            raw_text_preview="Closet IDF-02",
            metadata={"cad_hint": True},
        )
    )
    assert floorplan.adapter_chain[0] == "floorplan"

    drawing_packet = router.route(
        RouterInput(
            doc_id="cad_router_image_003",
            filename="packet_capture.webp",
            mime_type="image/webp",
            raw_text_preview="drawing packet",
            metadata={"cad_hint": True, "drawing_packet": True},
        )
    )
    assert drawing_packet.adapter_chain[0] == "drawing_packet"


def test_cad_adapter_recovers_title_block_and_labels() -> None:
    compiled = _compiled_pack_stub()
    router_input = RouterInput(
        doc_id="cad_parse_001",
        filename="floorplan.pdf",
        mime_type="application/pdf",
        raw_text_preview=_cad_text(),
        metadata={"cad_hint": True, "raw_text": _cad_text()},
    )
    plan, parsed = route_and_parse(router_input=router_input, compiled_pack=compiled)
    assert plan.adapter_chain[0] == "cad_sheet"
    kinds = {str(span.metadata.get("kind")) for span in parsed.evidence_spans}
    assert "sheet_ref" in kinds
    assert "title_block_field" in kinds
    assert "room_label" in kinds
    assert "equipment_label" in kinds
    assert "note_block" in kinds
    bundle = parsed.metadata.get("cad_evidence_bundle", {})
    assert isinstance(bundle, dict)
    assert "sheet_ref" in bundle
    assert "visual_regions" in bundle
    assert "component_labels" in bundle


def test_cad_graph_edges_and_packet_families_are_emitted() -> None:
    compiled = _compiled_pack_stub()
    router_input = RouterInput(
        doc_id="cad_runtime_001",
        filename="floorplan.pdf",
        mime_type="application/pdf",
        raw_text_preview=_cad_text(),
        metadata={"cad_hint": True, "raw_text": _cad_text()},
    )
    result = parse_and_packetize(router_input=router_input, compiled_pack=compiled)
    edge_families = {str(edge.metadata.get("edge_family")) for edge in result.document_parse.evidence_graph.edges}
    assert "same_sheet" in edge_families
    assert "note_attached_to" in edge_families or "near" in edge_families
    packet_families = {str(packet.metadata.get("packet_family")) for packet in result.packet_candidates}
    assert any(
        family in packet_families
        for family in (
            "site_identity_packet",
            "network_room_or_closet_packet",
            "equipment_reference_packet",
            "constructability_packet",
            "drawing_metadata_packet",
        )
    )


def test_weak_cad_image_requires_review() -> None:
    compiled = _compiled_pack_stub()
    router_input = RouterInput(
        doc_id="cad_weak_001",
        filename="photo_capture.jpg",
        mime_type="image/jpeg",
        raw_text_preview="",
        metadata={"cad_hint": True, "raw_text": ""},
    )
    _, parsed = route_and_parse(router_input=router_input, compiled_pack=compiled)
    assert any(flag.severity.value == "high" for flag in parsed.review_flags)

