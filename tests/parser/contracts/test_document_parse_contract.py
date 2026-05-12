from __future__ import annotations

from dataclasses import dataclass

from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.runtime import route_and_parse
from tests.parser.contracts.validators import assert_page_provenance, assert_valid_document_parse


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
    ]
    return _CompiledPackStub(manifest=_ManifestStub(), parser_profiles={"rows": rows})


def test_document_parse_contract_for_textual_adapters() -> None:
    compiled_pack = _compiled_pack_stub()
    cases = [
        ("contract_txt_001", "call.txt", "Alice: deliverable by Friday\nBob: risk is permit delay"),
        ("contract_md_001", "memo.md", "# Scope\n- deliverable\n- risk"),
        ("contract_docx_001", "memo.docx", "Scope and assumptions"),
        (
            "contract_email_001",
            "thread.eml",
            "From: lead@example.com\nTo: team@example.com\nSubject: Scope\n\nScope includes migration.\n> quoted",
        ),
    ]
    for doc_id, filename, text in cases:
        _, parse = route_and_parse(
            router_input=RouterInput(doc_id=doc_id, filename=filename, raw_text_preview=text, metadata={"raw_text": text}),
            compiled_pack=compiled_pack,
        )
        assert_valid_document_parse(parse, require_spans=True)


def test_document_parse_contract_for_pdf_modalities() -> None:
    compiled_pack = _compiled_pack_stub()
    pdf_inputs = [
        RouterInput(
            doc_id="contract_pdf_text_001",
            filename="memo.pdf",
            mime_type="application/pdf",
            raw_text_preview="native text pdf",
            metadata={"native_text_ratio": 0.95, "ocr_confidence": 0.95},
        ),
        RouterInput(
            doc_id="contract_pdf_ocr_001",
            filename="scan.pdf",
            mime_type="application/pdf",
            raw_text_preview="",
            metadata={"native_text_ratio": 0.05, "ocr_confidence": 0.20},
        ),
    ]
    for router_input in pdf_inputs:
        _, parse = route_and_parse(router_input=router_input, compiled_pack=compiled_pack)
        assert_valid_document_parse(parse, require_spans=False)
        assert_page_provenance(parse)
