from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from orbitbrief_core.compiler.packs.professional_services_text.load_compiled_pack import load_compiled_pack
from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.runtime import parse_extract_and_postprocess
from orbitbrief_core.runtime_spine.extractors.registry import load_extractor_registry


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


def test_parse_extract_and_postprocess_uses_primary_extractor() -> None:
    compiled_pack = _compiled_pack_stub()
    text = "Scope includes parser runtime delivery.\nAssumption: customer provides access."
    router_input = RouterInput(
        doc_id="extractor_hot_path_001",
        filename="notes.txt",
        raw_text_preview=text,
        metadata={"raw_text": text},
    )
    result = parse_extract_and_postprocess(router_input=router_input, compiled_pack=compiled_pack)
    assert result.extractor_id == "ps_text_narrative_v1"
    assert result.emits_business_claims is True
    assert result.pipeline_state == "extract"
    assert result.reason_codes == ()
    assert result.postprocess_result["summary"]["business_claims_allowed"] is True
    assert result.postprocess_result["summary"]["claims_emitted_count"] >= 1
    assert isinstance(result.extraction_result.get("field_claims"), list)
    assert any(diag.startswith("phase:extractor_registry.resolve:") for diag in result.diagnostics)


def test_parse_extract_and_postprocess_falls_back_to_intake_only_for_unknown_role() -> None:
    compiled_pack = _compiled_pack_stub()
    text = "Scope includes parser runtime delivery."
    router_input = RouterInput(
        doc_id="extractor_hot_path_002",
        filename="notes.txt",
        raw_text_preview=text,
        metadata={"raw_text": text},
    )
    result = parse_extract_and_postprocess(
        router_input=router_input,
        compiled_pack=compiled_pack,
        target_role_id="unsupported_role",
    )
    assert result.extractor_id == "intake_only_v1"
    assert result.emits_business_claims is False
    assert result.pipeline_state == "intake_only"
    assert "unsupported_role" in result.reason_codes
    assert result.extraction_result.get("lane") == "intake_only"
    assert result.postprocess_result["summary"]["business_claims_allowed"] is False


def test_parse_extract_and_postprocess_low_confidence_path_cannot_emit_business_claims() -> None:
    compiled_pack = _compiled_pack_stub()
    router_input = RouterInput(
        doc_id="extractor_hot_path_003",
        filename="unknown.bin",
        raw_text_preview="x",
        metadata={"raw_text": "x"},
    )
    result = parse_extract_and_postprocess(
        router_input=router_input,
        compiled_pack=compiled_pack,
        min_extract_confidence=0.95,
    )
    assert result.pipeline_state == "parked"
    assert "parse_confidence_too_low" in result.reason_codes
    assert result.emits_business_claims is False
    assert result.postprocess_result["summary"]["claims_emitted_count"] == 0


def test_parse_extract_and_postprocess_weak_ocr_path_is_parked() -> None:
    compiled_pack = _compiled_pack_stub()
    router_input = RouterInput(
        doc_id="extractor_hot_path_005",
        filename="scan.pdf",
        raw_text_preview="",
        metadata={"ocr_confidence": 0.20, "native_text_ratio": 0.05},
    )
    result = parse_extract_and_postprocess(
        router_input=router_input,
        compiled_pack=compiled_pack,
        min_extract_confidence=0.0,
    )
    assert result.pipeline_state == "parked"
    assert "weak_ocr" in result.reason_codes
    assert result.emits_business_claims is False


def test_parse_extract_and_postprocess_insufficient_packet_evidence_is_parked() -> None:
    compiled_pack = _compiled_pack_stub()
    router_input = RouterInput(
        doc_id="extractor_hot_path_006",
        filename="notes.txt",
        raw_text_preview="Short note with little semantic content.",
        metadata={"raw_text": "Short note with little semantic content."},
    )
    result = parse_extract_and_postprocess(
        router_input=router_input,
        compiled_pack=compiled_pack,
        min_extract_confidence=0.0,
        min_packet_count=2,
    )
    assert result.pipeline_state == "parked"
    assert "insufficient_evidence" in result.reason_codes
    assert result.emits_business_claims is False


def test_parse_extract_and_postprocess_ambiguous_fallback_fails_closed(tmp_path: Path) -> None:
    cfg = tmp_path / "extractor_registry.yaml"
    cfg.write_text(
        """
id: runtime.extractors.registry
version: 1.0.0
status: active
extractors:
  - extractor_id: intake_only_a
    role_id: intake_only_a
    kind: intake_only
    entrypoint: orbitbrief_core.runtime_spine.extractors.runtime_impl:run_intake_only_extractor
    supports_modalities: [txt]
    supports_discourse_types: [meeting_notes]
    packet_profile: minimal
    emits_business_claims: false
    enabled: true
  - extractor_id: intake_only_b
    role_id: intake_only_b
    kind: intake_only
    entrypoint: orbitbrief_core.runtime_spine.extractors.runtime_impl:run_intake_only_extractor
    supports_modalities: [txt]
    supports_discourse_types: [meeting_notes]
    packet_profile: minimal
    emits_business_claims: false
    enabled: true
""".strip(),
        encoding="utf-8",
    )
    registry = load_extractor_registry(cfg)
    compiled_pack = _compiled_pack_stub()
    text = "- notes style line\n- another line"
    router_input = RouterInput(
        doc_id="extractor_hot_path_004",
        filename="notes.txt",
        raw_text_preview=text,
        metadata={"raw_text": text},
    )
    result = parse_extract_and_postprocess(
        router_input=router_input,
        compiled_pack=compiled_pack,
        extractor_registry=registry,
        target_role_id="unknown_role",
    )
    assert result.pipeline_state == "unsupported"
    assert "ambiguous_extractor_resolution" in result.reason_codes
    assert result.emits_business_claims is False
    assert result.postprocess_result["summary"]["claims_emitted_count"] == 0



def test_parse_extract_and_postprocess_real_compiled_pack_accepts_canonical_field_paths() -> None:
    compiled_pack = load_compiled_pack(
        "professional_services_text",
        compiled_root=Path(__file__).resolve().parents[2] / "compiled_artifacts",
    )
    text = (
        "Alice: Scope includes AP installation at Dallas HQ and Austin branch.\n"
        "Alice: Assumption is customer will provide after-hours access.\n"
        "Bob: Risk is permit delay for rooftop work.\n"
        "Alice: Deliverable is a migration runbook."
    )
    router_input = RouterInput(
        doc_id="extractor_hot_path_real_pack_001",
        filename="notes.txt",
        raw_text_preview=text,
        metadata={"raw_text": text},
    )
    result = parse_extract_and_postprocess(router_input=router_input, compiled_pack=compiled_pack)
    summary = result.postprocess_result["summary"]
    rejected_reason_codes = {row["reason_code"] for row in result.postprocess_result["rejected_claims"]}
    emitted_values = [str(row["candidate_value"]) for row in result.postprocess_result["normalized_output"]["field_claims"]]

    assert result.pipeline_state == "extract"
    assert summary["claims_emitted_count"] >= 4
    assert "illegal_field_path" not in rejected_reason_codes
    assert all("anchor=" not in value for value in emitted_values)
    assert any("after-hours access" in value for value in emitted_values)
    assert any("migration runbook" in value for value in emitted_values)
