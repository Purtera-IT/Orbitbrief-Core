from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

from orbitbrief_core.compiler.packs.professional_services_text.compiler_runner import (
    load_compiled_pack as load_compiled_pack_artifact,
)
from orbitbrief_core.parser.registry import ParserRegistry, StrategyRegistry
from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.runtime import (
    ParseExtractionResult,
    ParseRuntimeResult,
    run_parser_runtime,
)
from orbitbrief_core.runtime_spine.compat.legacy_output_adapter import (
    adapt_parse_extraction_result,
)
from orbitbrief_core.runtime_spine.extractors import (
    ExtractorRegistry,
    ExtractorSpec,
    load_extractor_registry,
    postprocess_extractor_output,
    resolve_extractor_entrypoint,
)
from orbitbrief_core.runtime_spine.fallback import decide_pipeline_state
from orbitbrief_core.runtime_spine.compiled_pack_runtime import CompiledPackRuntimePolicy, load_compiled_pack_runtime_policy
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
    runtime_policy = load_compiled_pack_runtime_policy(compiled_pack=compiled_pack)
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
        weak_ocr=_is_weak_ocr(router_input, modality=modality),
        template_schema_artifact=bool(parse_plan.metadata.get("template_schema_artifact")),
        meta_reference_artifact=bool(parse_plan.metadata.get("meta_reference_artifact")),
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
    packet_payload = _build_packet_payload(runtime_result.document_parse, runtime_result.packet_candidates)
    compiled_policy_audit = dict(runtime_policy.consumption_audit)
    if decision.state == "extract" and entrypoint is not None:
        extraction_result = _invoke_extractor_entrypoint(
            entrypoint,
            role_id=role_id,
            modality=modality,
            packet_candidates=packet_payload,
            compiled_runtime_policy=runtime_policy,
        )
    elif decision.state in {"intake_only", "parked"} and entrypoint is not None:
        extraction_result = _invoke_extractor_entrypoint(
            entrypoint,
            role_id=role_id,
            modality=modality,
            reason=f"fallback_to_{decision.state}",
            reason_codes=decision.reason_codes,
            pipeline_state=decision.state,
            packet_count=len(packet_payload),
            compiled_runtime_policy=runtime_policy,
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
            "compiled_policy_used": True,
        }
    diagnostics.append("phase:extractor.run")
    if isinstance(extraction_result, dict):
        extraction_result.setdefault("compiled_policy_consumption_audit", compiled_policy_audit)

    policy = _build_postprocess_policy(extractor_spec=extractor_spec, runtime_policy=runtime_policy)
    diagnostics.append("phase:postprocess.policy")
    diagnostics.append(f"phase:compiled_pack_runtime.audit:{runtime_policy.consumption_audit.get('consumed_artifacts', ())}")
    postprocess_result = postprocess_extractor_output(
        extractor_spec=extractor_spec,
        extraction_output=extraction_result if isinstance(extraction_result, Mapping) else {"result": extraction_result},
        policy=policy,
    )
    diagnostics.append("phase:postprocess")

    extraction_payload = extraction_result if isinstance(extraction_result, Mapping) else {"result": extraction_result}
    extraction_review_flags = extraction_payload.get("review_flags") if isinstance(extraction_payload, Mapping) else ()
    postprocess_review_flags = postprocess_result.get("review_flags") if isinstance(postprocess_result, Mapping) else ()
    final_review_required = bool(
        decision.review_required
        or getattr(parse_plan, "review_flags", ())
        or extraction_review_flags
        or postprocess_review_flags
    )

    return ParseExtractionResult(
        parse_runtime_result=runtime_result,
        extractor_id=extractor_spec.extractor_id if extractor_spec is not None else "none",
        extractor_kind=extractor_spec.kind if extractor_spec is not None else "none",
        emits_business_claims=decision.emits_business_claims,
        extraction_result=extraction_payload,
        postprocess_result=postprocess_result,
        pipeline_state=decision.state,
        reason_codes=decision.reason_codes,
        review_required=final_review_required,
        diagnostics=tuple(diagnostics),
    )


def run_pipeline(
    path: str | Path,
    *,
    compiled_pack: Any | None = None,
    include_runtime_result: bool = False,
) -> dict[str, Any]:
    """Legacy facade that delegates to the official orchestration path.

    This compatibility entrypoint preserves the legacy pipeline envelope while
    routing through the parser-first runtime core.
    """
    artifact_path = Path(path).resolve()
    text_preview = ""
    if artifact_path.suffix.lower() in {".txt", ".md", ".eml"} and artifact_path.exists():
        text_preview = artifact_path.read_text(encoding="utf-8", errors="replace")
    active_compiled_pack = compiled_pack or _load_default_compiled_pack()
    target_role_id = _infer_target_role_id(artifact_path)
    router_input = RouterInput(
        doc_id=artifact_path.stem or "runtime_doc",
        filename=str(artifact_path),
        raw_text_preview=text_preview,
        metadata={"path": str(artifact_path), "raw_text": text_preview},
    )
    result = parse_extract_and_postprocess(
        router_input=router_input,
        compiled_pack=active_compiled_pack,
        target_role_id=target_role_id,
    )
    return adapt_parse_extraction_result(
        result,
        artifact_path=artifact_path,
        target_role_id=target_role_id,
        include_runtime_result=include_runtime_result,
    )


def run_package_pipeline(
    paths: list[str | Path] | tuple[str | Path, ...],
    *,
    compiled_pack: Any | None = None,
):
    from orbitbrief_core.runtime_spine.package_pipeline import run_package_pipeline as _run_package_pipeline

    return _run_package_pipeline(paths, compiled_pack=compiled_pack)


def _is_weak_ocr(router_input: RouterInput, *, modality: str) -> bool:
    if modality != "pdf_ocr":
        return False
    value = router_input.metadata.get("ocr_confidence")
    if not isinstance(value, (int, float)):
        return False
    ocr_confidence = float(value)
    if ocr_confidence < 0.45:
        return True
    preview = str(router_input.raw_text_preview or "")
    token_count = len([token for token in preview.split() if token.strip()])
    return ocr_confidence < 0.55 and token_count < 60


def _serialize_span_for_extractor(span: Any) -> dict[str, Any]:
    def _enum_value(value: Any) -> Any:
        return getattr(value, "value", value)

    metadata = dict(span.metadata) if isinstance(getattr(span, "metadata", None), Mapping) else {}
    parser_cues = metadata.get("parser_cues", ())
    if not isinstance(parser_cues, (list, tuple)):
        parser_cues = ()
    packet_families = metadata.get("packet_families", ())
    if not isinstance(packet_families, (list, tuple)):
        packet_families = ()
    return {
        "span_id": str(span.span_id),
        "text": str(span.text),
        "normalized_text": str(span.normalized_text),
        "section_path": [str(part) for part in getattr(span, "section_path", ())],
        "speaker_id": getattr(span, "speaker_id", None),
        "author_id": getattr(span, "author_id", None),
        "message_id": getattr(span, "message_id", None),
        "time_anchor_id": getattr(span, "time_anchor_id", None),
        "authority_score": float(getattr(span, "authority_score", 0.0) or 0.0),
        "authority_class": _enum_value(getattr(span, "authority_class", None)),
        "cue_kinds": [str(_enum_value(item)) for item in getattr(span, "cue_kinds", ())],
        "parser_cues": [str(item) for item in parser_cues],
        "packet_families": [str(item) for item in packet_families],
        "metadata": metadata,
    }



def _build_packet_payload(document_parse: Any, packet_candidates: tuple[Any, ...]) -> list[dict[str, Any]]:
    span_by_id = {str(span.span_id): span for span in getattr(document_parse, "evidence_spans", ())}
    payload: list[dict[str, Any]] = []
    for packet in packet_candidates:
        row = packet.to_dict()
        evidence_rows = [
            _serialize_span_for_extractor(span_by_id[span_id])
            for span_id in row.get("span_ids", ())
            if str(span_id) in span_by_id
        ]
        row["evidence_rows"] = evidence_rows
        payload.append(row)
    return payload



def _build_postprocess_policy(*, extractor_spec: ExtractorSpec | None, runtime_policy: CompiledPackRuntimePolicy) -> PostprocessPolicy:
    if extractor_spec is None:
        return PostprocessPolicy(
            emits_business_claims=False,
            allowed_claim_families=frozenset(),
            allowed_field_paths=frozenset(),
            require_evidence_refs=True,
            review_rules={},
        )
    compiled_allowed_claim_families = runtime_policy.allowed_claim_families_for_role(extractor_spec.role_id)
    allowed_claim_families = frozenset(extractor_spec.allowed_claim_families)
    if compiled_allowed_claim_families:
        allowed_claim_families = frozenset(set(allowed_claim_families) | set(compiled_allowed_claim_families)) if allowed_claim_families else compiled_allowed_claim_families

    has_structured_runtime_policy = bool(
        runtime_policy.field_table or runtime_policy.projection_rule_table or runtime_policy.claim_family_table
    )

    # Compiled pack policy is the runtime source of truth for field legality,
    # but only when the pack actually ships structured field/projection policy.
    # Stub packs used in hot-path tests often contain only parser profiles; in
    # that case we must fall back to the extractor registry instead of letting
    # minimal runtime overrides collapse legality to a single field path.
    allowed_field_paths = (
        runtime_policy.projection_targets_for_claim_families(allowed_claim_families)
        if has_structured_runtime_policy
        else frozenset()
    )
    if not allowed_field_paths:
        allowed_field_paths = runtime_policy.allowed_field_paths_for_role(extractor_spec.role_id)
    if not allowed_field_paths:
        canonicalized = runtime_policy.canonicalize_requested_field_paths(
            extractor_spec.allowed_field_paths,
            candidate_pool=runtime_policy.allowed_field_paths_for_role(extractor_spec.role_id),
        )
        allowed_field_paths = canonicalized or frozenset(extractor_spec.allowed_field_paths)

    if extractor_spec.role_id != runtime_policy.role_id and extractor_spec.allowed_field_paths:
        allowed_field_paths = frozenset(set(allowed_field_paths) | set(extractor_spec.allowed_field_paths))

    return PostprocessPolicy(
        emits_business_claims=bool(extractor_spec.emits_business_claims),
        allowed_claim_families=allowed_claim_families,
        allowed_field_paths=allowed_field_paths,
        require_evidence_refs=bool(extractor_spec.require_evidence_refs),
        review_rules=dict(extractor_spec.review_rules) or dict(runtime_policy.review_rules),
    )


def _invoke_extractor_entrypoint(entrypoint: Any, **kwargs: Any) -> Any:
    try:
        return entrypoint(**kwargs)
    except TypeError:
        # Backward compatibility with extractors that do not accept policy injection.
        legacy_kwargs = dict(kwargs)
        legacy_kwargs.pop("compiled_runtime_policy", None)
        return entrypoint(**legacy_kwargs)


def _select_intake_only_spec(extractor_registry: ExtractorRegistry) -> ExtractorSpec | None:
    candidates = [spec for spec in extractor_registry.all_enabled() if spec.kind == "intake_only"]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _infer_target_role_id(artifact_path: Path) -> str:
    stem = artifact_path.stem.lower()
    if "audit" in stem:
        return "audit_site_review"
    if "roster" in stem or "site" in stem:
        return "site_roster_spreadsheet"
    if "drawing" in stem or "plan" in stem:
        return "drawing_packet"
    return "transcript_or_notes"


def _load_default_compiled_pack() -> Any:
    try:
        return load_compiled_pack_artifact(
            "professional_services_text",
            compiled_root=Path.cwd() / "compiled_artifacts",
        )
    except Exception:
        modalities = ("txt", "md", "docx", "email_export", "pasted_notes", "pdf_text", "pdf_ocr")
        parser_rows = [
            {
                "parser_profile_id": f"parser:professional_services_text:{modality}",
                "modality": modality,
            }
            for modality in modalities
        ]
        return SimpleNamespace(
            manifest=SimpleNamespace(
                pack_id="professional_services_text",
                role_id="transcript_or_notes",
                artifact_family="managed_services_text",
            ),
            parser_profiles={"rows": parser_rows},
            claim_family_table={"rows": []},
            field_table={"rows": []},
        )
