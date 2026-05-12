from __future__ import annotations

from dataclasses import dataclass

from orbitbrief_core.parser.adapters.cad_pdf import CadPdfAdapter
from orbitbrief_core.parser.adapters.site_schematic_pdf import SiteSchematicPdfAdapter
from orbitbrief_core.parser.registry import load_parser_registry
from orbitbrief_core.parser.router import ContainerType, DiscourseType, ParsePlan, RouteEvidence, RouteScore, RouterInput
from orbitbrief_core.runtime_spine.extractors.registry import load_extractor_registry


@dataclass(frozen=True, slots=True)
class _ManifestStub:
    pack_id: str = "professional_services_text"
    role_id: str = "transcript_or_notes"


@dataclass(frozen=True, slots=True)
class _CompiledPackStub:
    manifest: _ManifestStub


SAMPLE_TEXT = """
<PARSED TEXT FOR PAGE: 1 / 2>
TC001 TELECOMM SYMBOL LIST
IDF - INTERMEDIATE DISTRIBUTION FRAME
2. ALL CABLES SHALL BE LABELED AT BOTH ENDS, 6" FROM THE POINT OF TERMINATION.
3. PROVIDE 20' OF CABLE SLACK FOR WIRELESS ACCESS POINTS. TERMINATE WAP CABLES ON DEDICATED PATCH PANEL.
<PARSED TEXT FOR PAGE: 2 / 2>
TC301 TELECOMM RISER DIAGRAM
A/V CLOSET 031C
AP
PATCH PANEL A
""".strip()


def _compiled_pack_stub() -> _CompiledPackStub:
    return _CompiledPackStub(manifest=_ManifestStub())


def _parse_plan(modality: str, adapter_key: str) -> ParsePlan:
    return ParsePlan(
        doc_id="site-schematic-half",
        container_type=ContainerType.PDF,
        discourse_type=DiscourseType.PROJECT_MEMO,
        parser_profile_id=f"parser:professional_services_text:{modality}",
        adapter_chain=(adapter_key,),
        strategy_chain=("site_package",),
        quality_mode="cad_hardened",
        authority_mode="diagram_weighted",
        packet_policy="drawing_packets",
        routing_confidence=0.9,
        route_scores=(RouteScore(label="project_memo", score=0.9),),
        route_evidence=(RouteEvidence(signal_id="site", signal_type="pdf_mode", score=0.9, value=modality, source="metadata"),),
        metadata={"modality": modality, "role_id": "drawing_packet"},
    )


def _router_input() -> RouterInput:
    return RouterInput(
        doc_id="site-schematic-half",
        filename="drawing_packet.pdf",
        mime_type="application/pdf",
        metadata={"full_text": SAMPLE_TEXT},
    )


def test_site_schematic_pdf_adapter_attaches_bundle_and_alias() -> None:
    result = SiteSchematicPdfAdapter().parse(
        router_input=_router_input(),
        parse_plan=_parse_plan("site_schematic_pdf", "site_schematic_pdf"),
        compiled_pack=_compiled_pack_stub(),
    )
    summary = result.metadata.get("site_schematic_summary", {})
    assert result.metadata.get("site_schematic_alias") == "site_schematic_pdf"
    assert summary.get("page_count") == 2
    assert summary.get("typed_pages") == 2
    assert summary.get("legend_entries", 0) >= 1


def test_cad_pdf_adapter_still_emits_site_schematic_metadata_for_backcompat() -> None:
    result = CadPdfAdapter().parse(
        router_input=_router_input(),
        parse_plan=_parse_plan("cad_sheet", "cad_sheet"),
        compiled_pack=_compiled_pack_stub(),
    )
    summary = result.metadata.get("site_schematic_summary", {})
    assert summary.get("page_count") == 2
    assert summary.get("typed_pages") == 2
    assert "site_schematic_bundle" in result.metadata


def test_registry_and_extractor_support_site_schematic_aliases() -> None:
    parser_registry = load_parser_registry()
    assert parser_registry.get_by_modality("site_schematic_pdf").adapter.endswith("SiteSchematicPdfAdapter")
    assert parser_registry.get_by_modality("site_schematic_image").adapter.endswith("SiteSchematicImageAdapter")

    extractor_registry = load_extractor_registry()
    resolved = extractor_registry.resolve(role_id="drawing_packet", modality="site_schematic_pdf", discourse_type="project_memo")
    assert resolved.extractor_id == "ps_site_schematic_v1"
