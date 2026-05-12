from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from orbitbrief_core.parser.adapters.common import build_context
from orbitbrief_core.parser.intake_preview import hydrate_router_input
from orbitbrief_core.parser.router import ContainerType, DiscourseType, ParsePlan, RouteEvidence, RouteScore, RouterInput
from orbitbrief_core.runtime_spine.compiled_pack_runtime import load_compiled_pack_runtime_policy
from orbitbrief_core.runtime_spine.extractors.registry import ExtractorSpec, load_extractor_registry
from orbitbrief_core.runtime_spine.pipeline import _build_postprocess_policy


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
    projection_rule_table: dict
    review_rule_table: dict


def _compiled_pack_stub() -> _CompiledPackStub:
    return _CompiledPackStub(
        manifest=_ManifestStub(),
        parser_profiles={"rows": [{"modality": "cad_sheet", "parser_profile_id": "parser:professional_services_text:cad_sheet"}]},
        claim_family_table={"rows": []},
        field_table={"rows": []},
        projection_rule_table={"rows": []},
        review_rule_table={"rows": []},
    )


def _cad_parse_plan() -> ParsePlan:
    return ParsePlan(
        doc_id="cad-role-binding",
        container_type=ContainerType.PDF,
        discourse_type=DiscourseType.PROJECT_MEMO,
        parser_profile_id="parser:professional_services_text:cad_sheet",
        adapter_chain=("cad_sheet",),
        strategy_chain=("site_package",),
        quality_mode="cad_hardened",
        authority_mode="diagram_weighted",
        packet_policy="drawing_packets",
        routing_confidence=0.9,
        route_scores=(RouteScore(label="project_memo", score=0.9),),
        route_evidence=(RouteEvidence(signal_id="cad", signal_type="pdf_mode", score=0.9, value="cad_sheet", source="metadata"),),
        metadata={"modality": "cad_sheet", "role_id": "drawing_packet"},
    )


def test_cad_adapter_context_binds_role_to_drawing_packet() -> None:
    ctx = build_context(
        router_input=RouterInput(doc_id="cad-role-binding", filename="drawing.pdf", mime_type="application/pdf", metadata={}),
        parse_plan=_cad_parse_plan(),
        compiled_pack=_compiled_pack_stub(),
    )
    assert ctx.modality == "cad_sheet"
    assert ctx.role_id == "drawing_packet"


def test_site_schematic_extractor_registry_resolves_dedicated_spec() -> None:
    registry = load_extractor_registry()
    resolved = registry.resolve(role_id="drawing_packet", modality="cad_sheet", discourse_type="project_memo")
    assert resolved.extractor_id == "ps_site_schematic_v1"


def test_auxiliary_role_policy_preserves_extractor_allowed_field_paths() -> None:
    runtime_policy = load_compiled_pack_runtime_policy(compiled_pack=_compiled_pack_stub())
    spec = ExtractorSpec(
        extractor_id="aux-cad",
        role_id="drawing_packet",
        kind="narrative",
        entrypoint="orbitbrief_core.runtime_spine.extractors.runtime_impl:run_narrative_extractor",
        supports_modalities=("cad_sheet",),
        supports_discourse_types=("project_memo",),
        packet_profile="professional_services_site_schematics_v1",
        emits_business_claims=True,
        enabled=True,
        allowed_claim_families=("drawing_metadata_claim",),
        allowed_field_paths=("drawing_packet_metadata", "site_profile_from_drawings"),
        require_evidence_refs=True,
        review_rules={},
    )
    policy = _build_postprocess_policy(extractor_spec=spec, runtime_policy=runtime_policy)
    assert "drawing_packet_metadata" in policy.allowed_field_paths
    assert "site_profile_from_drawings" in policy.allowed_field_paths


def test_cad_hint_pdf_hydration_uses_full_document(monkeypatch, tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def _fake_pdf_preview_text(path: Path, *, full_document: bool = False) -> str:
        seen["full_document"] = full_document
        return "p0 text\np1 text\np2 text\np3 text"

    from orbitbrief_core.parser import intake_preview as module

    monkeypatch.setattr(module, "_pdf_preview_text", _fake_pdf_preview_text)
    pdf_path = tmp_path / "drawing.pdf"
    pdf_path.write_bytes(b"%PDF-1.5\n")
    hydrated = hydrate_router_input(
        RouterInput(
            doc_id="cad-hydrate",
            filename=str(pdf_path),
            mime_type="application/pdf",
            metadata={"cad_hint": True},
        )
    )
    assert seen.get("full_document") is True
    assert "p3 text" in hydrated.metadata.get("full_text", "")

