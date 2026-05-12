from __future__ import annotations

from orbitbrief_core.parser.adapters.pdf_common import PageArbitrationResult
from orbitbrief_core.parser.adapters.pdf_page_judge import HardPageJudge, run_hard_page_judge, should_run_hard_page_judge
from orbitbrief_core.parser.adapters.providers.vl_embedding_provider import VLEmbeddingProvider, candidate_from_block
from orbitbrief_core.parser.graph.scorers.region_relevance import RegionRelevanceRequest, RegionRelevanceScoringService


def test_region_relevance_is_bounded_and_fail_closed_when_provider_unavailable() -> None:
    candidates = (
        candidate_from_block(region_id="r1", page_index=0, bbox=None, text="Risk is permit delay"),
        candidate_from_block(region_id="r2", page_index=0, bbox=None, text="Deliverable is migration runbook"),
    )
    scorer = RegionRelevanceScoringService(backend=VLEmbeddingProvider(available=False).score_region_relevance, threshold=0.7, max_fanout=1)
    result = scorer.score(
        RegionRelevanceRequest(
            page_index=0,
            query_text="permit delay risk",
            candidate_regions=candidates,
        )
    )
    assert result
    assert result[0].abstained is True
    assert "backend_abstained" in result[0].reason_codes


def test_hard_page_judge_runs_only_on_dispute_and_is_bounded() -> None:
    arbitration = PageArbitrationResult(
        selected_blocks=(),
        selected_tables=(),
        hypothesis_scores={"h1": 10.0, "h2": 9.0},
        metadata={"winner_hypothesis_id": "h1", "winner": "fitz", "arbitration_reason_codes": ("reading_order_dispute",)},
    )
    assert should_run_hard_page_judge(arbitration) is True
    updated, decision = run_hard_page_judge(arbitration=arbitration, hypotheses=(), judge=HardPageJudge(available=False))
    assert decision is not None
    assert decision.abstained is True
    assert updated.metadata.get("winner_hypothesis_id") == "h1"


def test_hard_page_judge_not_invoked_when_no_material_dispute() -> None:
    arbitration = PageArbitrationResult(
        selected_blocks=(),
        selected_tables=(),
        hypothesis_scores={"h1": 8.0},
        metadata={"winner_hypothesis_id": "h1", "winner": "fitz", "arbitration_reason_codes": ("close_hypothesis_scores",)},
    )
    assert should_run_hard_page_judge(arbitration) is False
    updated, decision = run_hard_page_judge(arbitration=arbitration, hypotheses=(), judge=HardPageJudge(available=True))
    assert decision is None
    assert updated.metadata.get("winner_hypothesis_id") == "h1"
