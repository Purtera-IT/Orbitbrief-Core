from __future__ import annotations

from .conftest import run_eval_parser


def test_eval_packet_quality_has_diagnostics(compiled_pack_eval_stub, nasty_eval_cases) -> None:
    for case in nasty_eval_cases:
        result = run_eval_parser(case=case, compiled_pack=compiled_pack_eval_stub)
        for packet in result.packet_candidates:
            diagnostic = packet.metadata.get("packet_diagnostic", {})
            if diagnostic:
                assert isinstance(diagnostic.get("anchor"), dict)
                assert isinstance(diagnostic.get("score_contributions", []), list)
