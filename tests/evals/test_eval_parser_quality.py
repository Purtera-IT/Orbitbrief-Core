from __future__ import annotations

from .conftest import run_eval_parser
from .metrics import aggregate_metric_rows, parser_metrics


def test_eval_parser_quality_smoke(compiled_pack_eval_stub, nasty_eval_cases) -> None:
    rows: list[dict[str, float]] = []
    for case in nasty_eval_cases:
        result = run_eval_parser(case=case, compiled_pack=compiled_pack_eval_stub)
        row = parser_metrics(result)
        rows.append(row)
        assert row["span_count"] >= 0.0
        assert row["packet_count"] >= 0.0
    summary = aggregate_metric_rows(rows)
    assert "span_count" in summary
    assert "graph_edge_count" in summary
