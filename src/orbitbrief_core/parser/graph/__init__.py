from orbitbrief_core.parser.graph.base import (
    GraphBuildConfig,
    GraphBuildResult,
    GraphContext,
    GraphPassStat,
    PacketSeedHint,
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
    "GraphNeuralHooks",
    "GraphBuilder",
    "build_graph",
    "enrich_document_parse",
]
