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


def _cad_text_with_strategy_signals() -> str:
    return (
        "Sheet Number: A-201\n"
        "Sheet Title: Access and Network Plan\n"
        "Customer: Example Health\n"
        "Site: Dallas Clinic - South Wing\n"
        "Drawn By: Ops Drafting\n"
        "Rev A: Added AP closet details\n"
        "Rev B: Updated rack clearance dimensions\n"
        "Note 1: Escort required for after-hours access.\n"
        "Note 2: Install switch in MDF closet.\n"
        "Callout 3 near AP-01\n"
        "Room 102\n"
        "MDF-01\n"
        "IDF-02\n"
        "RACK-1\n"
        "SW-1\n"
        "AP-01\n"
        "12 ft service path\n"
        "Legend: Symbol table for reference only\n"
        "Stamp: Issued for permit review\n"
        "Boilerplate: Not for construction\n"
    )


def _run() -> tuple:
    compiled = _compiled_pack_stub()
    result = parse_and_packetize(
        router_input=RouterInput(
            doc_id="cad_strategy_11_4_001",
            filename="site_package_plan.pdf",
            mime_type="application/pdf",
            raw_text_preview=_cad_text_with_strategy_signals(),
            metadata={
                "cad_hint": True,
                "raw_text": _cad_text_with_strategy_signals(),
                "cad_regions": [
                    {"region_id": "r1", "kind": "title_block", "text": "Sheet Number: A-201", "page_index": 0, "confidence": 0.92},
                    {"region_id": "r2", "kind": "title_block", "text": "Customer: Example Health", "page_index": 0, "confidence": 0.9},
                    {"region_id": "r3", "kind": "revision_block", "text": "Rev B: Updated rack clearance dimensions", "page_index": 0, "confidence": 0.86},
                    {"region_id": "r4", "kind": "note_block", "text": "Note 1: Escort required for after-hours access.", "page_index": 0, "confidence": 0.84},
                    {"region_id": "r5", "kind": "callout", "text": "Callout 3", "page_index": 0, "confidence": 0.8},
                    {"region_id": "r6", "kind": "room_label", "text": "MDF-01", "page_index": 0, "confidence": 0.82},
                    {"region_id": "r7", "kind": "equipment_label", "text": "AP-01", "page_index": 0, "confidence": 0.8},
                    {"region_id": "r8", "kind": "dimension_text", "text": "12 ft", "page_index": 0, "confidence": 0.79},
                    {"region_id": "r9", "kind": "legend", "text": "Legend: Symbol table for reference only", "page_index": 0, "confidence": 0.88},
                ],
            },
        ),
        compiled_pack=compiled,
    )
    return result.document_parse, result.packet_candidates


def test_site_package_strategy_emits_expected_enrichment_bundles() -> None:
    parsed, _ = _run()
    metadata = parsed.metadata
    assert metadata.get("title_block_bundle")
    assert metadata.get("revision_bundle")
    assert metadata.get("note_clusters")
    assert metadata.get("room_or_closet_clusters")
    assert metadata.get("equipment_clusters")
    assert metadata.get("likely_callout_attachments")
    assert metadata.get("likely_zone_associations")


def test_site_package_revision_and_note_clusters_are_separated() -> None:
    parsed, _ = _run()
    revision_entries = parsed.metadata.get("revision_bundle", [])
    note_clusters = parsed.metadata.get("note_clusters", [])
    revision_ids = {
        str(item.get("span_id"))
        for bundle in revision_entries
        for item in bundle.get("entries", [])
        if isinstance(item, dict)
    }
    note_ids = {
        str(item.get("span_id"))
        for cluster in note_clusters
        for item in cluster.get("items", [])
        if isinstance(item, dict)
    }
    assert revision_ids
    assert note_ids
    assert revision_ids.isdisjoint(note_ids)


def test_site_package_downgrades_legend_border_noise() -> None:
    parsed, _ = _run()
    downgraded = parsed.metadata.get("downgraded_noise_regions", [])
    assert downgraded
    downgraded_ids = {str(item.get("span_id")) for item in downgraded}
    noisy_spans = [span for span in parsed.evidence_spans if span.span_id in downgraded_ids]
    assert noisy_spans
    assert all(bool(span.metadata.get("cad_noise_downgraded")) for span in noisy_spans)

