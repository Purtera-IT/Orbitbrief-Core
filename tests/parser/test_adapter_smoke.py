from __future__ import annotations

from dataclasses import dataclass

from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.runtime import route_and_parse


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


def test_txt_transcript_smoke() -> None:
    compiled_pack = _compiled_pack_stub()
    text = "Alice: Kickoff at 09:30\nBob: Scope is managed services text lane."
    router_input = RouterInput(doc_id="doc_txt_001", filename="call.txt", raw_text_preview=text, metadata={"raw_text": text})
    plan, parsed = route_and_parse(router_input=router_input, compiled_pack=compiled_pack)
    assert plan.adapter_chain[0] == "txt"
    assert parsed.modality == "txt"
    assert len(parsed.evidence_spans) >= 1


def test_markdown_memo_smoke() -> None:
    compiled_pack = _compiled_pack_stub()
    text = "# Scope\n- Build parser adapters\n## Deliverables\n- Txt, md, docx lanes"
    router_input = RouterInput(doc_id="doc_md_001", filename="memo.md", raw_text_preview=text, metadata={"raw_text": text})
    plan, parsed = route_and_parse(router_input=router_input, compiled_pack=compiled_pack)
    assert plan.adapter_chain[0] == "md"
    assert parsed.modality == "md"
    assert len(parsed.section_tree.nodes) >= 1


def test_docx_fallback_smoke() -> None:
    compiled_pack = _compiled_pack_stub()
    text = "Scope\nProfessional services parser migration plan."
    router_input = RouterInput(doc_id="doc_docx_001", filename="memo.docx", raw_text_preview=text, metadata={"raw_text": text})
    plan, parsed = route_and_parse(router_input=router_input, compiled_pack=compiled_pack)
    assert plan.adapter_chain[0] == "docx"
    assert parsed.modality == "docx"
    assert len(parsed.evidence_spans) >= 1


def test_email_export_smoke() -> None:
    compiled_pack = _compiled_pack_stub()
    text = (
        "From: lead@example.com\nTo: team@example.com\nSubject: Managed services\nDate: Fri, 12 Jan 2024 10:00:00 +0000\n\n"
        "Please capture exclusions and deliverables.\n\n"
        "On Thu, 11 Jan 2024 09:00:00 +0000 wrote:\n> prior context"
    )
    router_input = RouterInput(doc_id="doc_email_001", filename="thread.eml", raw_text_preview=text, metadata={"raw_text": text})
    plan, parsed = route_and_parse(router_input=router_input, compiled_pack=compiled_pack)
    assert plan.adapter_chain[0] == "email_export"
    assert parsed.modality == "email_export"
    assert parsed.thread_graph is not None


def test_pdf_text_smoke() -> None:
    compiled_pack = _compiled_pack_stub()
    router_input = RouterInput(
        doc_id="doc_pdf_text_001",
        filename="memo.pdf",
        mime_type="application/pdf",
        raw_text_preview="Scope and assumptions",
        metadata={"native_text_ratio": 0.95, "ocr_confidence": 0.95},
    )
    plan, parsed = route_and_parse(router_input=router_input, compiled_pack=compiled_pack)
    assert plan.adapter_chain[0] == "pdf_text"
    assert parsed.modality == "pdf_text"
    assert parsed.section_tree.root_section_id is not None


def test_pdf_ocr_smoke() -> None:
    compiled_pack = _compiled_pack_stub()
    router_input = RouterInput(
        doc_id="doc_pdf_ocr_001",
        filename="scan.pdf",
        mime_type="application/pdf",
        raw_text_preview="",
        metadata={"native_text_ratio": 0.05, "ocr_confidence": 0.2},
    )
    plan, parsed = route_and_parse(router_input=router_input, compiled_pack=compiled_pack)
    assert plan.adapter_chain[0] == "pdf_ocr"
    assert parsed.modality == "pdf_ocr"
    assert parsed.section_tree.root_section_id is not None
