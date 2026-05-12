from __future__ import annotations

from .conftest import run_eval_runtime
from .metrics import aggregate_metric_rows, extraction_metrics
from .scorecards import build_scorecard


def test_eval_extraction_quality_and_scorecard(compiled_pack_eval_stub, nasty_eval_cases) -> None:
    parser_rows: list[dict[str, float]] = []
    extraction_rows: list[dict[str, float]] = []
    for case in nasty_eval_cases:
        result = run_eval_runtime(case=case, compiled_pack=compiled_pack_eval_stub)
        parser_rows.append(
            {
                "span_count": float(len(result.parse_runtime_result.document_parse.evidence_spans)),
                "packet_count": float(len(result.parse_runtime_result.packet_candidates)),
                "graph_edge_count": float(len(result.parse_runtime_result.document_parse.evidence_graph.edges)),
            }
        )
        extraction_rows.append(extraction_metrics(result))
        assert result.pipeline_state in {"extract", "intake_only", "parked", "unsupported"}
    card = build_scorecard(
        parser_summary=aggregate_metric_rows(parser_rows),
        extraction_summary=aggregate_metric_rows(extraction_rows),
    )
    assert "release_gates" in card
    assert isinstance(card["release_gates"], dict)
