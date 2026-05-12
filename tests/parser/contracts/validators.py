from __future__ import annotations

from orbitbrief_core.parser.shared.types import (
    DocumentParse,
    PacketCandidate,
    ReviewSeverity,
    validate_document_parse,
)


def assert_valid_packet_candidate(packet: PacketCandidate) -> None:
    assert packet.packet_id
    assert 0.0 <= float(packet.confidence) <= 1.0
    assert isinstance(packet.span_ids, tuple)
    if packet.primary_span_id is not None:
        assert packet.primary_span_id in packet.span_ids


def assert_valid_document_parse(parse: DocumentParse, *, require_spans: bool = False) -> None:
    assert parse.doc_id
    assert parse.pack_id
    assert parse.role_id
    assert parse.modality
    assert parse.container_type is not None
    assert parse.discourse_type is not None
    assert parse.source_layer is not None
    assert isinstance(parse.metadata, dict)
    assert isinstance(parse.evidence_spans, tuple)
    assert isinstance(parse.review_flags, tuple)
    assert isinstance(parse.packet_candidates, tuple)
    if require_spans:
        assert len(parse.evidence_spans) > 0

    for span in parse.evidence_spans:
        assert span.span_id
        assert isinstance(span.text, str)
        assert isinstance(span.normalized_text, str)
        assert span.doc_id == parse.doc_id
        assert 0.0 <= float(span.authority_score) <= 1.0

    issues = validate_document_parse(parse)
    high = [item for item in issues if item.severity == ReviewSeverity.HIGH]
    assert not high, f"DocumentParse invariant violations: {[item.message for item in high]}"

    for packet in parse.packet_candidates:
        assert_valid_packet_candidate(packet)


def assert_page_provenance(parse: DocumentParse) -> None:
    if parse.modality not in {"pdf_text", "pdf_ocr"}:
        return
    for span in parse.evidence_spans:
        # PDF lanes are expected to carry page references for traceability.
        assert span.page_ref is not None, f"Missing page_ref for span {span.span_id}"
