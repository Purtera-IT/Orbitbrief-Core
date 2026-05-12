from __future__ import annotations

from dataclasses import dataclass

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


def _rich_cad_result():
    compiled = _compiled_pack_stub()
    raw_text = (
        "Sheet Number: A-401\n"
        "Sheet Title: Site Readiness Plan\n"
        "Customer: Example Health\n"
        "Site: Dallas Clinic\n"
        "Rev A: Added MDF escort restrictions\n"
        "Note 1: Escort required for after-hours access.\n"
        "Note 2: Install AP in MDF closet and patch to SW-1.\n"
        "Callout 8\n"
        "MDF-01\n"
        "IDF-02\n"
        "AP-01\n"
        "SW-1\n"
        "RACK-1\n"
        "12 ft service pathway\n"
    )
    return parse_and_packetize(
        router_input=RouterInput(
            doc_id="cad_packet_stage11_6_001",
            filename="site_readiness_plan.pdf",
            mime_type="application/pdf",
            raw_text_preview=raw_text,
            metadata={
                "cad_hint": True,
                "raw_text": raw_text,
                "cad_regions": [
                    {"region_id": "tb1", "kind": "title_block", "text": "Sheet Number: A-401", "page_index": 0, "bbox": [0.01, 0.01, 0.2, 0.08], "confidence": 0.91},
                    {"region_id": "tb2", "kind": "title_block", "text": "Site: Dallas Clinic", "page_index": 0, "bbox": [0.02, 0.1, 0.28, 0.18], "confidence": 0.9},
                    {"region_id": "rv1", "kind": "revision_block", "text": "Rev A: Added MDF escort restrictions", "page_index": 0, "bbox": [0.72, 0.05, 0.95, 0.13], "confidence": 0.86},
                    {"region_id": "n1", "kind": "note_block", "text": "Note 1: Escort required for after-hours access.", "page_index": 0, "bbox": [0.12, 0.25, 0.5, 0.34], "confidence": 0.84},
                    {"region_id": "n2", "kind": "note_block", "text": "Note 2: Install AP in MDF closet and patch to SW-1.", "page_index": 0, "bbox": [0.12, 0.35, 0.52, 0.44], "confidence": 0.84},
                    {"region_id": "c1", "kind": "callout", "text": "Callout 8", "page_index": 0, "bbox": [0.54, 0.36, 0.61, 0.41], "confidence": 0.82},
                    {"region_id": "z1", "kind": "room_label", "text": "MDF-01", "page_index": 0, "bbox": [0.61, 0.28, 0.7, 0.35], "confidence": 0.83},
                    {"region_id": "z2", "kind": "room_label", "text": "IDF-02", "page_index": 0, "bbox": [0.7, 0.28, 0.79, 0.35], "confidence": 0.82},
                    {"region_id": "e1", "kind": "equipment_label", "text": "AP-01", "page_index": 0, "bbox": [0.62, 0.39, 0.7, 0.45], "confidence": 0.8},
                    {"region_id": "e2", "kind": "equipment_label", "text": "SW-1", "page_index": 0, "bbox": [0.71, 0.39, 0.79, 0.45], "confidence": 0.8},
                    {"region_id": "e3", "kind": "equipment_label", "text": "RACK-1", "page_index": 0, "bbox": [0.8, 0.39, 0.9, 0.46], "confidence": 0.8},
                    {"region_id": "d1", "kind": "dimension_text", "text": "12 ft", "page_index": 0, "bbox": [0.61, 0.48, 0.68, 0.52], "confidence": 0.78},
                    {"region_id": "lg1", "kind": "legend", "text": "Legend: Symbol table", "page_index": 0, "bbox": [0.02, 0.75, 0.29, 0.9], "confidence": 0.89},
                ],
            },
        ),
        compiled_pack=compiled,
    )


def test_cad_packetizer_produces_anchor_first_packets_with_diagnostics() -> None:
    result = _rich_cad_result()
    assert result.packet_candidates
    packet = result.packet_candidates[0]
    diag = packet.metadata.get("packet_diagnostic", {})
    assert diag.get("anchor", {}).get("anchor_span_id") == packet.primary_span_id
    assert isinstance(diag.get("included"), list) and diag["included"]
    assert isinstance(diag.get("excluded"), list)
    assert isinstance(diag.get("score_contributions"), list)
    assert isinstance(packet.metadata.get("cad_packetizer", {}), dict)


def test_cad_packetizer_keeps_noise_regions_out_and_sets_packet_state() -> None:
    result = _rich_cad_result()
    noisy_ids = {
        span.span_id
        for span in result.document_parse.evidence_spans
        if bool(span.metadata.get("cad_noise_downgraded"))
    }
    assert noisy_ids
    for packet in result.packet_candidates:
        assert packet.primary_span_id not in noisy_ids
        assert "packet_state" in packet.metadata
        assert packet.metadata["packet_state"] in {"extract", "review_required", "parked"}


def test_cad_packetizer_families_cover_core_managed_service_neighborhoods() -> None:
    result = _rich_cad_result()
    families = {str(packet.metadata.get("packet_family")) for packet in result.packet_candidates}
    assert any(family in families for family in {"site_identity_packet", "network_room_or_closet_packet"})
    assert any(family in families for family in {"note_scope_packet", "constructability_packet", "equipment_reference_packet"})


def test_weak_cad_sheet_packets_are_review_or_parked() -> None:
    compiled = _compiled_pack_stub()
    weak = parse_and_packetize(
        router_input=RouterInput(
            doc_id="cad_packet_stage11_6_weak",
            filename="weak_photo.jpg",
            mime_type="image/jpeg",
            raw_text_preview="legend only",
            metadata={"cad_hint": True, "raw_text": "legend only", "cad_regions": [{"region_id": "n", "kind": "legend", "text": "Legend only", "page_index": 0, "confidence": 0.4}]},
        ),
        compiled_pack=compiled,
    )
    assert weak.packet_candidates
    states = {str(packet.metadata.get("packet_state")) for packet in weak.packet_candidates}
    assert states.intersection({"review_required", "parked"})


def test_cad_packetizer_keeps_room_and_equipment_packets_page_local() -> None:
    compiled = _compiled_pack_stub()
    raw_text = (
        "Sheet Number: A-500\n"
        "MDF-01\n"
        "AP-01\n"
        "Note 7: install AP and run to nearest IDF\n"
        "Sheet Number: A-900\n"
        "General legend and schedule\n"
    )
    result = parse_and_packetize(
        router_input=RouterInput(
            doc_id="cad_packet_stage11_6_locality",
            filename="site_multi_page.pdf",
            mime_type="application/pdf",
            raw_text_preview=raw_text,
            metadata={
                "cad_hint": True,
                "raw_text": raw_text,
                "cad_regions": [
                    {"region_id": "p0_room", "kind": "room_label", "text": "MDF-01", "page_index": 0, "confidence": 0.9},
                    {"region_id": "p0_ap", "kind": "equipment_label", "text": "AP-01", "page_index": 0, "confidence": 0.88},
                    {"region_id": "p0_note", "kind": "note_block", "text": "run to nearest IDF", "page_index": 0, "confidence": 0.82},
                    {"region_id": "p1_legend", "kind": "legend", "text": "LEGEND / SCHEDULE / NOT TO SCALE", "page_index": 1, "confidence": 0.91},
                    {"region_id": "p1_tb", "kind": "title_block", "text": "Sheet Number: A-900", "page_index": 1, "confidence": 0.9},
                ],
            },
        ),
        compiled_pack=compiled,
    )
    by_span_id = {span.span_id: span for span in result.document_parse.evidence_spans}
    local_families = {"network_room_or_closet_packet", "equipment_reference_packet"}
    for packet in result.packet_candidates:
        family = str(packet.metadata.get("packet_family"))
        if family not in local_families:
            continue
        primary = by_span_id.get(packet.primary_span_id)
        assert primary is not None
        primary_page = primary.metadata.get("page_index")
        for span_id in packet.span_ids:
            span = by_span_id.get(span_id)
            assert span is not None
            if primary_page is not None and span.metadata.get("page_index") is not None:
                assert span.metadata.get("page_index") == primary_page

