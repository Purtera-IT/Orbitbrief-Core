from __future__ import annotations

from dataclasses import dataclass

import pytest

from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.runtime import parse_and_packetize
from orbitbrief_core.runtime_spine.pipeline import parse_extract_and_postprocess


@dataclass(frozen=True, slots=True)
class _ManifestStub:
    pack_id: str = "professional_services_text"
    role_id: str = "transcript_or_notes"


@dataclass(frozen=True, slots=True)
class _CompiledPackStub:
    manifest: _ManifestStub
    parser_profiles: dict
    claim_family_table: dict
    field_table: dict
    review_rules: dict
    projection_rules: dict
    retrieval_exemplars: dict
    negative_examples: dict


@pytest.fixture
def compiled_pack_eval_stub() -> _CompiledPackStub:
    parser_rows = [
        {"modality": "txt", "parser_profile_id": "parser:professional_services_text:txt"},
        {"modality": "md", "parser_profile_id": "parser:professional_services_text:md"},
        {"modality": "email_export", "parser_profile_id": "parser:professional_services_text:email_export"},
        {"modality": "pdf_text", "parser_profile_id": "parser:professional_services_text:pdf_text"},
        {"modality": "pdf_ocr", "parser_profile_id": "parser:professional_services_text:pdf_ocr"},
    ]
    claim_rows = [{"claim_family_name": name} for name in ("scope_included_claim", "risk_claim", "open_question_claim", "deliverable_claim")]
    field_rows = [{"field_path": path} for path in ("scope_included", "risks", "open_questions", "deliverables_required")]
    return _CompiledPackStub(
        manifest=_ManifestStub(),
        parser_profiles={"rows": parser_rows},
        claim_family_table={"rows": claim_rows},
        field_table={"rows": field_rows},
        review_rules={"rows": [{"rule_key": "verification_confidence_threshold", "rule_value": 0.55}]},
        projection_rules={"rows": []},
        retrieval_exemplars={"rows": []},
        negative_examples={"rows": []},
    )


@pytest.fixture
def nasty_eval_cases() -> list[dict[str, str]]:
    return [
        {"case_id": "ocr_ugly_001", "filename": "scan.pdf", "text": "", "native_text_ratio": "0.04", "ocr_confidence": "0.21"},
        {
            "case_id": "email_chain_001",
            "filename": "thread.eml",
            "text": "From: lead@example.com\nSubject: scope\n\nDeliverable Friday.\n> old reply\n> legal disclaimer",
            "native_text_ratio": "1.0",
            "ocr_confidence": "1.0",
        },
        {
            "case_id": "hybrid_notes_001",
            "filename": "notes.txt",
            "text": "Scope includes migration\nRisk permit delay\nOpen question site count",
            "native_text_ratio": "1.0",
            "ocr_confidence": "1.0",
        },
        {
            "case_id": "contradictory_001",
            "filename": "memo.md",
            "text": "# Schedule\nGo live Friday\nGo live next month\nRisk permit delay",
            "native_text_ratio": "1.0",
            "ocr_confidence": "1.0",
        },
    ]


def run_eval_parser(*, case: dict[str, str], compiled_pack: _CompiledPackStub):
    router_input = RouterInput(
        doc_id=case["case_id"],
        filename=case["filename"],
        raw_text_preview=case["text"],
        metadata={
            "raw_text": case["text"],
            "native_text_ratio": float(case["native_text_ratio"]),
            "ocr_confidence": float(case["ocr_confidence"]),
        },
    )
    return parse_and_packetize(router_input=router_input, compiled_pack=compiled_pack)


def run_eval_runtime(*, case: dict[str, str], compiled_pack: _CompiledPackStub):
    router_input = RouterInput(
        doc_id=case["case_id"],
        filename=case["filename"],
        raw_text_preview=case["text"],
        metadata={
            "raw_text": case["text"],
            "native_text_ratio": float(case["native_text_ratio"]),
            "ocr_confidence": float(case["ocr_confidence"]),
        },
    )
    return parse_extract_and_postprocess(router_input=router_input, compiled_pack=compiled_pack)
