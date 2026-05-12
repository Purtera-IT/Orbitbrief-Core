from __future__ import annotations

from typing import Any, Mapping


def parser_metrics(result: Any) -> dict[str, float]:
    parse = result.document_parse
    spans = len(parse.evidence_spans)
    sections = len(parse.section_tree.nodes)
    packets = len(result.packet_candidates)
    graph_edges = len(parse.evidence_graph.edges)
    page_refs = sum(1 for span in parse.evidence_spans if span.page_ref is not None)
    return {
        "span_count": float(spans),
        "section_count": float(sections),
        "packet_count": float(packets),
        "graph_edge_count": float(graph_edges),
        "page_provenance_coverage": float(page_refs / max(1, spans)),
    }


def extraction_metrics(result: Any) -> dict[str, float]:
    post = result.postprocess_result
    accepted = post.get("accepted_claims", ())
    rejected = post.get("rejected_claims", ())
    review_flags = post.get("review_flags", ())
    return {
        "accepted_claim_count": float(len(accepted)),
        "rejected_claim_count": float(len(rejected)),
        "review_flag_count": float(len(review_flags)),
        "fallback_review_required": 1.0 if result.review_required else 0.0,
    }


def aggregate_metric_rows(rows: list[Mapping[str, float]]) -> dict[str, float]:
    keys = {key for row in rows for key in row.keys()}
    return {key: sum(float(row.get(key, 0.0)) for row in rows) / max(1, len(rows)) for key in sorted(keys)}
