from __future__ import annotations

from dataclasses import dataclass

from orbitbrief_core.parser.adapters.mail_common import parse_email_artifact
from orbitbrief_core.parser.adapters.providers.talon_provider import TalonBoundarySuggestion
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
    rows = [{"modality": "email_export", "parser_profile_id": "parser:professional_services_text:email_export"}]
    return _CompiledPackStub(manifest=_ManifestStub(), parser_profiles={"rows": rows})


def test_email_adapter_segments_boundary_classes_and_authority() -> None:
    compiled_pack = _compiled_pack_stub()
    text = (
        "From: lead@example.com\n"
        "To: team@example.com\n"
        "Subject: Managed services scope\n"
        "Date: Fri, 12 Jan 2024 10:00:00 +0000\n\n"
        "Current ask: confirm site access and schedule.\n"
        "On Thu, 11 Jan 2024 09:00:00 +0000 wrote:\n"
        "> Old quoted line one\n"
        "> Old quoted line two\n"
        "-----Forwarded message-----\n"
        "From: vendor@example.com\n"
        "Subject: BOM details\n"
        "Qty table attached.\n"
        "-- \n"
        "Best,\n"
        "Lead Engineer\n"
        "This email and attachments are confidential and intended solely for the recipient.\n"
    )
    router_input = RouterInput(doc_id="email_stage3_4_001", filename="thread.eml", raw_text_preview=text, metadata={"raw_text": text})
    plan, parsed = route_and_parse(router_input=router_input, compiled_pack=compiled_pack)
    assert plan.adapter_chain[0] == "email_export"
    assert parsed.modality == "email_export"
    assert parsed.evidence_spans

    boundary_classes = {str(span.metadata.get("boundary_class", "")) for span in parsed.evidence_spans}
    assert "current_authored" in boundary_classes
    assert "quoted_context" in boundary_classes
    assert "forwarded_context" in boundary_classes
    assert "signature" in boundary_classes or "disclaimer" in boundary_classes

    by_class = {str(span.metadata.get("boundary_class")): span.authority_score for span in parsed.evidence_spans}
    assert by_class.get("current_authored", 0.0) >= 0.9
    assert by_class.get("quoted_context", 1.0) <= 0.45
    assert by_class.get("forwarded_context", 1.0) <= 0.35


def test_parse_email_artifact_fallback_when_talon_unavailable(monkeypatch) -> None:
    monkeypatch.setattr("orbitbrief_core.parser.adapters.mail_common.suggest_talon_boundaries", lambda _text: None)
    text = (
        "Current ask: confirm site access.\n"
        "On Thu, 11 Jan 2024 09:00:00 +0000 wrote:\n"
        "> historical line\n"
    )
    result = parse_email_artifact(text)
    assert result.messages
    message = result.messages[0]
    assert message.boundary_segments
    assert message.boundary_review_needed is False


def test_parse_email_artifact_talon_reconcile_marks_review_needed(monkeypatch) -> None:
    text = (
        "Current ask: confirm site access.\n"
        "Follow up details.\n"
        "Historical block starts here.\n"
        "Thanks,\n"
        "Lead\n"
    )
    quoted_start = text.find("Historical block starts here.")
    signature_start = text.find("Thanks,")
    monkeypatch.setattr(
        "orbitbrief_core.parser.adapters.mail_common.suggest_talon_boundaries",
        lambda _text: TalonBoundarySuggestion(
            quoted_start=quoted_start,
            signature_start=signature_start,
            confidence=0.82,
            metadata={"provider": "talon"},
        ),
    )
    result = parse_email_artifact(text)
    assert result.messages
    message = result.messages[0]
    assert message.boundary_review_needed is True
    classes = {segment.boundary_class for segment in message.boundary_segments}
    assert "quoted_context" in classes
    assert "signature" in classes
