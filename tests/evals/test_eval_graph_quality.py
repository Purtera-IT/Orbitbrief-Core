from __future__ import annotations

from .conftest import run_eval_parser


def test_eval_graph_edges_have_reason_codes(compiled_pack_eval_stub, nasty_eval_cases) -> None:
    for case in nasty_eval_cases:
        result = run_eval_parser(case=case, compiled_pack=compiled_pack_eval_stub)
        for edge in result.document_parse.evidence_graph.edges:
            reason_codes = edge.metadata.get("reason_codes", ())
            if reason_codes:
                assert isinstance(reason_codes, (list, tuple))
