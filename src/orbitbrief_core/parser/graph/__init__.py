from orbitbrief_core.parser.graph.base import (
    ConflictDiagnostic,
    EdgeProvenance,
    GraphInspectionBundle,
    GraphBuildConfig,
    GraphBuildResult,
    GraphContext,
    GraphPassStat,
    GraphSummary,
    NodeProvenance,
    PacketSeedHint,
    PacketSeedDiagnostic,
    ScoreDecision,
    ScoreResult,
    ScorerDiagnostic,
    build_graph_inspection_bundle,
    get_conflict_diagnostics,
    get_edge_provenance,
    get_node_provenance,
    get_packet_seed_diagnostics,
    summarize_graph,
)
from orbitbrief_core.parser.graph.neural_hooks import GraphNeuralHooks


def build_graph(*args, **kwargs):
    from orbitbrief_core.parser.graph_builder import build_graph as _build_graph

    return _build_graph(*args, **kwargs)


def enrich_document_parse(*args, **kwargs):
    from orbitbrief_core.parser.graph_builder import enrich_document_parse as _enrich_document_parse

    return _enrich_document_parse(*args, **kwargs)


class GraphBuilder:
    def __new__(cls, *args, **kwargs):
        from orbitbrief_core.parser.graph_builder import GraphBuilder as _GraphBuilder

        return _GraphBuilder(*args, **kwargs)

__all__ = [
    "GraphBuildConfig",
    "GraphBuildResult",
    "GraphPassStat",
    "GraphContext",
    "PacketSeedHint",
    "GraphSummary",
    "PacketSeedDiagnostic",
    "ConflictDiagnostic",
    "NodeProvenance",
    "EdgeProvenance",
    "GraphInspectionBundle",
    "ScoreResult",
    "ScoreDecision",
    "ScorerDiagnostic",
    "summarize_graph",
    "get_packet_seed_diagnostics",
    "get_conflict_diagnostics",
    "get_node_provenance",
    "get_edge_provenance",
    "build_graph_inspection_bundle",
    "GraphNeuralHooks",
    "GraphBuilder",
    "build_graph",
    "enrich_document_parse",
]
