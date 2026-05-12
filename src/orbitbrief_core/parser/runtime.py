from __future__ import annotations

from dataclasses import dataclass, replace
from time import perf_counter
from typing import Any, Mapping

from orbitbrief_core.parser.authority import apply_authority_scoring
from orbitbrief_core.parser.cue_tagger import apply_cue_tags
from orbitbrief_core.parser.graph_builder import build_graph
from orbitbrief_core.parser.intake_preview import hydrate_router_input
from orbitbrief_core.parser.packetizer import build_packets
from orbitbrief_core.parser.registry import (
    ParserRegistry,
    RegistryDispatchError,
    StrategyRegistry,
    build_default_strategy_registry,
    load_parser_registry,
)
from orbitbrief_core.parser.router import ParsePlan, ParserRouter, RouterInput
from orbitbrief_core.parser.shared.types import DocumentParse, PacketCandidate


class RuntimeSpineError(RuntimeError):
    """Raised when parser runtime spine orchestration fails."""


@dataclass(frozen=True, slots=True)
class ParseRuntimeResult:
    parse_plan: ParsePlan
    document_parse: DocumentParse
    packet_candidates: tuple[PacketCandidate, ...]
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RuntimeParseBundle:
    parse_plan: ParsePlan
    document_parse: DocumentParse
    packet_candidates: tuple[PacketCandidate, ...]
    routing_confidence: float
    diagnostics: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ParseExtractionResult:
    parse_runtime_result: ParseRuntimeResult
    extractor_id: str
    extractor_kind: str
    emits_business_claims: bool
    extraction_result: Mapping[str, Any]
    postprocess_result: Mapping[str, Any]
    pipeline_state: str
    reason_codes: tuple[str, ...]
    review_required: bool
    diagnostics: tuple[str, ...] = ()


def _get_registry(registry: ParserRegistry | None, *, strict: bool) -> ParserRegistry:
    if registry is not None:
        return registry
    return load_parser_registry()


def _get_strategy_registry(strategy_registry: StrategyRegistry | None, *, strict: bool) -> StrategyRegistry:
    if strategy_registry is not None:
        return strategy_registry
    return build_default_strategy_registry(allow_fallback=not strict)


def _route(*, router_input: RouterInput, compiled_pack: Any) -> ParsePlan:
    return ParserRouter(compiled_pack).route(router_input)


def _run_adapter(
    *,
    router_input: RouterInput,
    parse_plan: ParsePlan,
    compiled_pack: Any,
    registry: ParserRegistry,
    strict: bool,
) -> DocumentParse:
    registry.validate_plan(parse_plan)
    adapter = registry.get_adapter(parse_plan)
    return adapter.parse(router_input=router_input, parse_plan=parse_plan, compiled_pack=compiled_pack)


def get_adapter_for_plan(parse_plan: ParsePlan, *, registry: ParserRegistry | None = None, strict: bool = True):
    """Compatibility helper to inspect adapter dispatch."""
    active_registry = _get_registry(registry, strict=strict)
    active_registry.validate_plan(parse_plan)
    return active_registry.get_adapter(parse_plan)


def parse_with_plan(
    *,
    router_input: RouterInput,
    parse_plan: ParsePlan,
    compiled_pack: Any,
    registry: ParserRegistry | None = None,
    strict: bool = True,
) -> DocumentParse:
    """Compatibility entrypoint: route plan directly to adapter (no strategy/packetization)."""
    active_registry = _get_registry(registry, strict=strict)
    return _run_adapter(
        router_input=router_input,
        parse_plan=parse_plan,
        compiled_pack=compiled_pack,
        registry=active_registry,
        strict=strict,
    )


def route_and_parse(
    *,
    router_input: RouterInput,
    compiled_pack: Any,
    registry: ParserRegistry | None = None,
    strict: bool = True,
) -> tuple[ParsePlan, DocumentParse]:
    """Compatibility entrypoint: route then adapter parse only."""
    parse_plan = _route(router_input=router_input, compiled_pack=compiled_pack)
    document_parse = parse_with_plan(
        router_input=router_input,
        parse_plan=parse_plan,
        compiled_pack=compiled_pack,
        registry=registry,
        strict=strict,
    )
    return parse_plan, document_parse


def parse_artifact(
    *,
    router_input: RouterInput,
    compiled_pack: Any,
    registry: ParserRegistry | None = None,
    strict: bool = True,
) -> DocumentParse:
    """Runtime spine: router -> adapter -> strategy -> cue -> authority -> graph."""
    result = parse_and_packetize(
        router_input=router_input,
        compiled_pack=compiled_pack,
        registry=registry,
        strict=strict,
    )
    return result.document_parse


def _run_strategy(
    *,
    document_parse: DocumentParse,
    parse_plan: ParsePlan,
    compiled_pack: Any,
    parser_registry: ParserRegistry,
    strategy_registry: StrategyRegistry,
    strict: bool,
    diagnostics: list[str],
) -> DocumentParse:
    modality = parser_registry.plan_modality(parse_plan)
    strategy_names = parse_plan.strategy_chain
    if not strategy_names:
        strategy_names = parser_registry.get_by_modality(modality).strategy_defaults
    strategy_chain = strategy_registry.strategy_chain(modality=modality, strategy_names=strategy_names, strict=strict)

    enriched = document_parse
    for strategy in strategy_chain:
        if strategy.name == "noop":
            diagnostics.append("phase:strategy:noop_fallback")
            continue
        enriched = strategy.apply(
            document_parse=enriched,
            parse_plan=parse_plan,
            compiled_pack=compiled_pack,
        )
        diagnostics.append(f"phase:strategy:{strategy.name}")
    return enriched


def _run_graph_builder(
    *,
    document_parse: DocumentParse,
    parse_plan: ParsePlan,
    compiled_pack: Any,
    diagnostics: list[str],
) -> DocumentParse:
    hooks = None
    try:
        from orbitbrief_core.parser.graph.qwen_pilot import build_qwen_graph_hooks_from_env

        hooks = build_qwen_graph_hooks_from_env()
    except Exception:
        hooks = None
    graph_result = build_graph(document_parse=document_parse, parse_plan=parse_plan, compiled_pack=compiled_pack, hooks=hooks)
    diagnostics.extend(graph_result.diagnostics)
    diagnostics.append(f"graph:pass_count={len(graph_result.pass_stats)}")
    diagnostics.append(f"graph:packet_seed_count={len(graph_result.packet_seed_hints)}")
    diagnostics.append("phase:graph_builder")
    return graph_result.document_parse


def _run_packetizer(document_parse: DocumentParse, compiled_pack: Any, diagnostics: list[str]) -> tuple[DocumentParse, tuple[PacketCandidate, ...]]:
    packetizer_result = build_packets(document_parse, compiled_pack=compiled_pack)
    diagnostics.extend(packetizer_result.diagnostics)
    diagnostics.append("phase:packetizer")
    final_parse = replace(document_parse, packet_candidates=packetizer_result.packets)
    return final_parse, packetizer_result.packets


def parse_and_packetize(
    *,
    router_input: RouterInput,
    compiled_pack: Any,
    registry: ParserRegistry | None = None,
    strategy_registry: StrategyRegistry | None = None,
    strict: bool = True,
) -> ParseRuntimeResult:
    """Parse-side runtime entrypoint: route -> adapter -> strategy -> cue/authority -> graph -> packetizer."""
    bundle = run_parser_runtime(
        router_input=router_input,
        compiled_pack=compiled_pack,
        registry=registry,
        strategy_registry=strategy_registry,
        strict=strict,
    )
    return ParseRuntimeResult(
        parse_plan=bundle.parse_plan,
        document_parse=bundle.document_parse,
        packet_candidates=bundle.packet_candidates,
        diagnostics=tuple(bundle.diagnostics.get("events", ())),
    )


def run_parser_runtime(
    *,
    router_input: RouterInput,
    compiled_pack: Any,
    registry: ParserRegistry | None = None,
    strategy_registry: StrategyRegistry | None = None,
    strict: bool = True,
) -> RuntimeParseBundle:
    """Canonical parser-only runtime orchestration.

    Order:
    route -> adapter -> strategy -> cue tag -> authority score -> graph build -> packetize
    """
    active_registry = _get_registry(registry, strict=strict)
    active_strategy_registry = _get_strategy_registry(strategy_registry, strict=strict)
    hydrated_router_input = hydrate_router_input(router_input)
    diagnostics: list[str] = []
    stage_start = perf_counter()
    parse_plan = _route(router_input=hydrated_router_input, compiled_pack=compiled_pack)
    diagnostics.append("phase:route")
    diagnostics.append(f"timing:route_ms={int((perf_counter() - stage_start) * 1000)}")

    try:
        stage_start = perf_counter()
        document_parse = _run_adapter(
            router_input=hydrated_router_input,
            parse_plan=parse_plan,
            compiled_pack=compiled_pack,
            registry=active_registry,
            strict=strict,
        )
        diagnostics.append(f"timing:adapter_ms={int((perf_counter() - stage_start) * 1000)}")
    except RegistryDispatchError as exc:
        raise RuntimeSpineError(str(exc)) from exc
    diagnostics.append("phase:adapt")

    stage_start = perf_counter()
    document_parse = _run_strategy(
        document_parse=document_parse,
        parse_plan=parse_plan,
        compiled_pack=compiled_pack,
        parser_registry=active_registry,
        strategy_registry=active_strategy_registry,
        strict=strict,
        diagnostics=diagnostics,
    )
    diagnostics.append(f"timing:strategy_ms={int((perf_counter() - stage_start) * 1000)}")

    stage_start = perf_counter()
    document_parse, cue_diag = apply_cue_tags(document_parse)
    diagnostics.extend(cue_diag)
    diagnostics.append("phase:cue_tagger")
    diagnostics.append(f"timing:cue_tagger_ms={int((perf_counter() - stage_start) * 1000)}")

    stage_start = perf_counter()
    document_parse, authority_diag = apply_authority_scoring(document_parse)
    diagnostics.extend(authority_diag)
    diagnostics.append("phase:authority")
    diagnostics.append(f"timing:authority_ms={int((perf_counter() - stage_start) * 1000)}")

    stage_start = perf_counter()
    document_parse = _run_graph_builder(
        document_parse=document_parse,
        parse_plan=parse_plan,
        compiled_pack=compiled_pack,
        diagnostics=diagnostics,
    )
    diagnostics.append(f"timing:graph_builder_ms={int((perf_counter() - stage_start) * 1000)}")

    stage_start = perf_counter()
    final_parse, packets = _run_packetizer(document_parse, compiled_pack, diagnostics)
    diagnostics.append(f"timing:packetizer_ms={int((perf_counter() - stage_start) * 1000)}")
    return RuntimeParseBundle(
        parse_plan=parse_plan,
        document_parse=final_parse,
        packet_candidates=packets,
        routing_confidence=parse_plan.routing_confidence,
        diagnostics={
            "events": tuple(diagnostics),
            "routing_confidence": parse_plan.routing_confidence,
            "modality": parse_plan.metadata.get("modality"),
        },
    )


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
    """Compatibility facade that delegates to the official runtime_spine orchestration."""
    from orbitbrief_core.runtime_spine.pipeline import parse_extract_and_postprocess as _official_hot_path

    return _official_hot_path(
        router_input=router_input,
        compiled_pack=compiled_pack,
        registry=registry,
        strategy_registry=strategy_registry,
        extractor_registry=extractor_registry,
        target_role_id=target_role_id,
        min_extract_confidence=min_extract_confidence,
        min_packet_count=min_packet_count,
        strict=strict,
    )
