from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from orbitbrief_core.parser.registry import ParserRegistry, StrategyRegistry
from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.runtime import (
    ParseExtractionResult,
    ParseRuntimeResult,
    run_parser_runtime,
)
from orbitbrief_core.runtime_spine.extractors import (
    ExtractorRegistry,
    ExtractorSpec,
    load_extractor_registry,
    postprocess_extractor_output,
    resolve_extractor_entrypoint,
)
from orbitbrief_core.runtime_spine.fallback import decide_pipeline_state
from orbitbrief_core.runtime_spine.postprocess import PostprocessPolicy


def parse_extract_and_postprocess(
    *,
    router_input: RouterInput,
    compiled_pack: Any,
    registry: ParserRegistry | None = None,
    strategy_registry: StrategyRegistry | None = None,
    extractor_registry: ExtractorRegistry | None = None,
    target_role_id: str | None = None,
    min_extract_confidence: float = 0.0,
    min_packet_count: int = 0,
    strict: bool = True,
) -> ParseExtractionResult:
    """Official production orchestration path after artifact intake."""
    parse_bundle = run_parser_runtime(
        router_input=router_input,
        compiled_pack=compiled_pack,
        registry=registry,
        strategy_registry=strategy_registry,
        strict=strict,
    )
    runtime_result = ParseRuntimeResult(
        parse_plan=parse_bundle.parse_plan,
        document_parse=parse_bundle.document_parse,
        packet_candidates=parse_bundle.packet_candidates,
        diagnostics=tuple(parse_bundle.diagnostics.get("events", ())),
    )
    diagnostics = list(runtime_result.diagnostics)

    active_extractor_registry = extractor_registry or load_extractor_registry()
    diagnostics.append("phase:extractor_registry.load")

    parse_plan = parse_bundle.parse_plan
    document_parse = parse_bundle.document_parse
    role_id = target_role_id or document_parse.role_id
    modality = str(parse_plan.metadata.get("modality", document_parse.modality))
    discourse_type = parse_plan.discourse_type.value

    decision = decide_pipeline_state(
        extractor_registry=active_extractor_registry,
        role_id=role_id,
        modality=modality,
        discourse_type=discourse_type,
        routing_confidence=float(parse_plan.routing_confidence),
        packet_count=len(parse_bundle.packet_candidates),
        weak_ocr=(
            modality == "pdf_ocr"
            and isinstance(router_input.metadata.get("ocr_confidence"), (int, float))
            and float(router_input.metadata.get("ocr_confidence")) < 0.55
        ),
        min_extract_confidence=min_extract_confidence,
        min_packet_count=min_packet_count,
    )
    diagnostics.append(f"phase:fallback.state:{decision.state}")
    for code in decision.reason_codes:
        diagnostics.append(f"fallback_reason:{code}")

    extractor_spec = decision.extractor_spec or _select_intake_only_spec(active_extractor_registry)
    diagnostics.append(
        "phase:extractor_registry.resolve:none"
        if extractor_spec is None
        else f"phase:extractor_registry.resolve:{extractor_spec.extractor_id}"
    )

    entrypoint = resolve_extractor_entrypoint(extractor_spec.entrypoint) if extractor_spec is not None else None
    packet_payload = [packet.to_dict() for packet in runtime_result.packet_candidates]
    if decision.state == "extract" and entrypoint is not None:
        extraction_result = entrypoint(
            role_id=role_id,
            modality=modality,
            packet_candidates=packet_payload,
        )
    elif decision.state in {"intake_only", "parked"} and entrypoint is not None:
        extraction_result = entrypoint(
            role_id=role_id,
            modality=modality,
            reason=f"fallback_to_{decision.state}",
            reason_codes=decision.reason_codes,
            pipeline_state=decision.state,
            packet_count=len(packet_payload),
        )
    else:
        extraction_result = {
            "role_id": role_id,
            "modality": modality,
            "lane": decision.state,
            "reason_codes": list(decision.reason_codes),
            "field_claims": [],
            "emits_business_claims": False,
            "review_required": True,
            "packet_count": len(packet_payload),
        }
    diagnostics.append("phase:extractor.run")

    policy = _build_postprocess_policy(extractor_spec=extractor_spec, compiled_pack=compiled_pack)
    diagnostics.append("phase:postprocess.policy")
    postprocess_result = postprocess_extractor_output(
        extractor_spec=extractor_spec,
        extraction_output=extraction_result if isinstance(extraction_result, Mapping) else {"result": extraction_result},
        policy=policy,
    )
    diagnostics.append("phase:postprocess")

    return ParseExtractionResult(
        parse_runtime_result=runtime_result,
        extractor_id=extractor_spec.extractor_id if extractor_spec is not None else "none",
        extractor_kind=extractor_spec.kind if extractor_spec is not None else "none",
        emits_business_claims=decision.emits_business_claims,
        extraction_result=extraction_result if isinstance(extraction_result, Mapping) else {"result": extraction_result},
        postprocess_result=postprocess_result,
        pipeline_state=decision.state,
        reason_codes=decision.reason_codes,
        review_required=decision.review_required,
        diagnostics=tuple(diagnostics),
    )


def run_pipeline(path: str | Path, *, compiled_pack: Any) -> dict[str, Any]:
    """Legacy facade that delegates to the official orchestration path."""
    artifact_path = Path(path).resolve()
    text_preview = ""
    if artifact_path.suffix.lower() in {".txt", ".md", ".eml"} and artifact_path.exists():
        text_preview = artifact_path.read_text(encoding="utf-8", errors="replace")
    router_input = RouterInput(
        doc_id=artifact_path.stem or "runtime_doc",
        filename=str(artifact_path),
        raw_text_preview=text_preview,
        metadata={"path": str(artifact_path), "raw_text": text_preview},
    )
    result = parse_extract_and_postprocess(router_input=router_input, compiled_pack=compiled_pack)
    return {
        "pipeline_state": result.pipeline_state,
        "reason_codes": list(result.reason_codes),
        "runtime_result": result,
    }


def _extract_claim_families_from_compiled_pack(compiled_pack: Any) -> frozenset[str]:
    payload = getattr(compiled_pack, "claim_family_table", None)
    if isinstance(payload, Mapping):
        rows = payload.get("rows")
        if isinstance(rows, list):
            out: set[str] = set()
            for row in rows:
                if isinstance(row, Mapping):
                    for key in ("claim_family_name", "claim_family_id", "name"):
                        value = row.get(key)
                        if isinstance(value, str) and value.strip():
                            out.add(value.strip())
                            break
            return frozenset(out)
    return frozenset()


def _extract_field_paths_from_compiled_pack(compiled_pack: Any) -> frozenset[str]:
    payload = getattr(compiled_pack, "field_table", None)
    if isinstance(payload, Mapping):
        rows = payload.get("rows")
        if isinstance(rows, list):
            out: set[str] = set()
            for row in rows:
                if isinstance(row, Mapping):
                    for key in ("field_path", "path", "field_id"):
                        value = row.get(key)
                        if isinstance(value, str) and value.strip():
                            out.add(value.strip())
                            break
            return frozenset(out)
    return frozenset()


def _build_postprocess_policy(*, extractor_spec: ExtractorSpec | None, compiled_pack: Any) -> PostprocessPolicy:
    if extractor_spec is None:
        return PostprocessPolicy(
            emits_business_claims=False,
            allowed_claim_families=frozenset(),
            allowed_field_paths=frozenset(),
            require_evidence_refs=True,
            review_rules={},
        )
    allowed_claim_families = frozenset(extractor_spec.allowed_claim_families)
    if not allowed_claim_families:
        allowed_claim_families = _extract_claim_families_from_compiled_pack(compiled_pack)

    allowed_field_paths = frozenset(extractor_spec.allowed_field_paths)
    if not allowed_field_paths:
        allowed_field_paths = _extract_field_paths_from_compiled_pack(compiled_pack)

    return PostprocessPolicy(
        emits_business_claims=bool(extractor_spec.emits_business_claims),
        allowed_claim_families=allowed_claim_families,
        allowed_field_paths=allowed_field_paths,
        require_evidence_refs=bool(extractor_spec.require_evidence_refs),
        review_rules=dict(extractor_spec.review_rules),
    )


def _select_intake_only_spec(extractor_registry: ExtractorRegistry) -> ExtractorSpec | None:
    candidates = [spec for spec in extractor_registry.all_enabled() if spec.kind == "intake_only"]
    if len(candidates) == 1:
        return candidates[0]
    return None
