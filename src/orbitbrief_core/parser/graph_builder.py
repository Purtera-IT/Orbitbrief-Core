from __future__ import annotations

from dataclasses import replace
from typing import Any, Sequence

from orbitbrief_core.parser.graph.base import GraphBuildConfig, GraphBuildResult, GraphContext as PassContext
from orbitbrief_core.parser.graph.cad_passes import CadStructuralPass
from orbitbrief_core.parser.graph.indices import GraphIndices
from orbitbrief_core.parser.graph.neural_hooks import GraphNeuralHooks
from orbitbrief_core.parser.graph.signals import GraphSignals
from orbitbrief_core.parser.graph.passes import (
    AuthorityPass,
    ChronologyPass,
    PacketNeighborhoodPass,
    SemanticCuePass,
    StructuralPass,
    ThreadConversationPass,
)
from orbitbrief_core.parser.router import ParsePlan
from orbitbrief_core.parser.shared.types import DocumentParse


class GraphBuilder:
    """Multi-pass deterministic-first evidence graph compiler."""

    def __init__(
        self,
        *,
        config: GraphBuildConfig | None = None,
        hooks: GraphNeuralHooks | None = None,
        passes: Sequence[Any] | None = None,
    ) -> None:
        self._config = config or GraphBuildConfig()
        self._hooks = hooks
        self._passes = tuple(passes) if passes is not None else (
            StructuralPass(),
            ThreadConversationPass(),
            ChronologyPass(),
            AuthorityPass(),
            SemanticCuePass(),
            PacketNeighborhoodPass(),
        )
        self._cad_pass = CadStructuralPass()

    def build(
        self,
        *,
        document_parse: DocumentParse,
        parse_plan: ParsePlan,
        compiled_pack: Any,
    ) -> GraphBuildResult:
        context = PassContext(parse_plan=parse_plan, compiled_pack=compiled_pack, config=self._config, hooks=self._hooks)
        current = document_parse
        effective_passes: tuple[Any, ...]
        if document_parse.modality in {"cad_sheet", "schematic", "floorplan", "drawing_packet", "site_schematic_pdf", "site_schematic_image"}:
            if self._passes and isinstance(self._passes[0], StructuralPass):
                effective_passes = (self._passes[0], self._cad_pass, *self._passes[1:])
            else:
                effective_passes = (*self._passes, self._cad_pass)
        else:
            effective_passes = self._passes
        for graph_pass in effective_passes:
            indices = GraphIndices.from_parse(current)
            signals = GraphSignals(parse=current, indices=indices)
            current, stat = graph_pass.run(document_parse=current, context=context, indices=indices, signals=signals)
            context.record_stat(stat)
        current = self._normalize_edge_metadata(current)
        metadata = dict(current.metadata)
        metadata["graph_diagnostics"] = list(dict.fromkeys(context.diagnostics))
        metadata["graph_pass_stats"] = [stat.to_dict() for stat in context.pass_stats]
        metadata["packet_seed_hints"] = [hint.to_dict() for hint in context.packet_seed_hints]
        metadata["graph_builder"] = {
            "strict_mode": self._config.strict_mode,
            "pass_names": [stat.pass_name for stat in context.pass_stats],
            "packet_seed_count": len(context.packet_seed_hints),
            "scorer_diagnostics_count": len(context.scorer_diagnostics),
        }
        if context.scorer_diagnostics:
            metadata["graph_scorer_diagnostics"] = [item.to_dict() for item in context.scorer_diagnostics]
            metadata["graph_scorer_summary"] = {
                "total_scored_candidates": len(context.scorer_diagnostics),
                "abstained_candidates": sum(1 for item in context.scorer_diagnostics if item.abstained),
                "accepted_candidates": sum(1 for item in context.scorer_diagnostics if item.accepted),
                "rejected_candidates": sum(1 for item in context.scorer_diagnostics if not item.accepted and not item.abstained),
                "fanout_trimmed_candidates": sum(1 for item in context.scorer_diagnostics if item.fanout_limited),
            }
        current = current.__class__(
            doc_id=current.doc_id,
            pack_id=current.pack_id,
            role_id=current.role_id,
            modality=current.modality,
            container_type=current.container_type,
            discourse_type=current.discourse_type,
            source_layer=current.source_layer,
            evidence_spans=current.evidence_spans,
            review_flags=current.review_flags,
            actor_graph=current.actor_graph,
            section_tree=current.section_tree,
            thread_graph=current.thread_graph,
            chronology_graph=current.chronology_graph,
            evidence_graph=current.evidence_graph,
            packet_candidates=current.packet_candidates,
            metadata=metadata,
        )
        return GraphBuildResult(
            document_parse=current,
            packet_seed_hints=tuple(context.packet_seed_hints),
            diagnostics=tuple(dict.fromkeys(context.diagnostics)),
            pass_stats=tuple(context.pass_stats),
            scorer_diagnostics=tuple(context.scorer_diagnostics),
        )

    @staticmethod
    def _normalize_edge_metadata(document_parse: DocumentParse) -> DocumentParse:
        def _normalized(meta: dict) -> dict:
            payload = dict(meta)
            payload.setdefault("edge_family", "unspecified")
            payload.setdefault("source_pass", "preexisting")
            payload.setdefault("reason_codes", ["preexisting_edge"])
            payload.setdefault("graph_pass", payload.get("source_pass"))
            return payload

        evidence_edges = tuple(replace(edge, metadata=_normalized(dict(edge.metadata))) for edge in document_parse.evidence_graph.edges)
        actor_edges = tuple(replace(edge, metadata=_normalized(dict(edge.metadata))) for edge in document_parse.actor_graph.edges)
        chrono_edges = tuple(replace(edge, metadata=_normalized(dict(edge.metadata))) for edge in document_parse.chronology_graph.edges)
        thread_graph = document_parse.thread_graph
        if thread_graph is not None:
            thread_edges = tuple(replace(edge, metadata=_normalized(dict(edge.metadata))) for edge in thread_graph.edges)
            thread_graph = replace(thread_graph, edges=thread_edges)
        return replace(
            document_parse,
            evidence_graph=replace(document_parse.evidence_graph, edges=evidence_edges),
            actor_graph=replace(document_parse.actor_graph, edges=actor_edges),
            chronology_graph=replace(document_parse.chronology_graph, edges=chrono_edges),
            thread_graph=thread_graph,
        )


def build_graph(
    *,
    document_parse: DocumentParse,
    parse_plan: ParsePlan,
    compiled_pack: Any,
    config: GraphBuildConfig | None = None,
    hooks: GraphNeuralHooks | None = None,
) -> GraphBuildResult:
    return GraphBuilder(config=config, hooks=hooks).build(
        document_parse=document_parse,
        parse_plan=parse_plan,
        compiled_pack=compiled_pack,
    )


def enrich_document_parse(
    *,
    document_parse: DocumentParse,
    parse_plan: ParsePlan,
    compiled_pack: Any,
    config: GraphBuildConfig | None = None,
    hooks: GraphNeuralHooks | None = None,
) -> DocumentParse:
    return build_graph(
        document_parse=document_parse,
        parse_plan=parse_plan,
        compiled_pack=compiled_pack,
        config=config,
        hooks=hooks,
    ).document_parse


def enrich_graphs(document_parse: DocumentParse, *, parse_plan: ParsePlan | None = None, compiled_pack: Any | None = None) -> tuple[DocumentParse, tuple[str, ...]]:
    """Compatibility wrapper used by runtime/tests."""
    if parse_plan is None:
        # fallback synthetic plan for compatibility callers
        from orbitbrief_core.parser.router import ParsePlan, RouteEvidence, RouteScore

        parse_plan = ParsePlan(
            doc_id=document_parse.doc_id,
            container_type=document_parse.container_type,
            discourse_type=document_parse.discourse_type,
            parser_profile_id=f"parser:{document_parse.pack_id}:{document_parse.modality}",
            adapter_chain=(document_parse.modality,),
            strategy_chain=(),
            quality_mode="standard",
            authority_mode="compat",
            packet_policy="compat",
            routing_confidence=1.0,
            route_scores=(RouteScore(label=document_parse.discourse_type.value, score=1.0),),
            route_evidence=(RouteEvidence(signal_id="compat", signal_type="compat", score=1.0, value="compat", source="graph_builder"),),
            metadata={"modality": document_parse.modality},
        )
    result = build_graph(document_parse=document_parse, parse_plan=parse_plan, compiled_pack=compiled_pack)
    return result.document_parse, result.diagnostics
