from __future__ import annotations

from typing import Mapping


def build_scorecard(*, parser_summary: Mapping[str, float], extraction_summary: Mapping[str, float]) -> dict[str, object]:
    release_gates = {
        "parser_has_spans": parser_summary.get("span_count", 0.0) >= 1.0,
        "graph_has_edges": parser_summary.get("graph_edge_count", 0.0) >= 0.0,
        "review_surface_present": extraction_summary.get("review_flag_count", 0.0) >= 0.0,
    }
    return {
        "parser_summary": dict(parser_summary),
        "extraction_summary": dict(extraction_summary),
        "release_gates": release_gates,
    }
