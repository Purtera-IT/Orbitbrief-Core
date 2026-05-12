from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from orbitbrief_core.parser.adapters.pdf_common import PageArbitrationResult


@dataclass(frozen=True, slots=True)
class PageJudgeRequest:
    dispute_type: str
    winner_hypothesis_id: str
    winner_source: str
    hypothesis_scores: Mapping[str, float]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PageJudgeDecision:
    winner_hypothesis_id: str | None
    confidence: float
    abstained: bool
    reason_codes: tuple[str, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class HardPageJudge:
    """Bounded dispute resolver for hard-page PDF arbitration."""

    available: bool = False

    def judge(self, request: PageJudgeRequest) -> PageJudgeDecision:
        if not self.available:
            return PageJudgeDecision(
                winner_hypothesis_id=None,
                confidence=0.0,
                abstained=True,
                reason_codes=("backend_unavailable",),
            )
        # Conservative: choose highest-scoring existing candidate only.
        if not request.hypothesis_scores:
            return PageJudgeDecision(
                winner_hypothesis_id=None,
                confidence=0.0,
                abstained=True,
                reason_codes=("score_not_produced",),
            )
        winner = sorted(request.hypothesis_scores.items(), key=lambda item: item[1], reverse=True)[0]
        return PageJudgeDecision(
            winner_hypothesis_id=winner[0],
            confidence=0.75,
            abstained=False,
            reason_codes=("bounded_hypothesis_selection", "hard_page_judge"),
            metadata={"winner_score": winner[1]},
        )


_DISPUTE_REASON_CODES = {
    "reading_order_dispute",
    "heading_body_dispute",
    "section_boundary_dispute",
    "table_attachment_dispute",
}


def should_run_hard_page_judge(arbitration: PageArbitrationResult) -> bool:
    reason_codes = set(str(code) for code in arbitration.metadata.get("arbitration_reason_codes", ()))
    return bool(reason_codes & _DISPUTE_REASON_CODES)


def run_hard_page_judge(
    *,
    arbitration: PageArbitrationResult,
    hypotheses: Sequence[Any],
    judge: HardPageJudge | None = None,
) -> tuple[PageArbitrationResult, PageJudgeDecision | None]:
    if not should_run_hard_page_judge(arbitration):
        return arbitration, None
    active_judge = judge or HardPageJudge(available=False)
    request = PageJudgeRequest(
        dispute_type="hard_page_dispute",
        winner_hypothesis_id=str(arbitration.metadata.get("winner_hypothesis_id", "unknown")),
        winner_source=str(arbitration.metadata.get("winner", "unknown")),
        hypothesis_scores={str(key): float(value) for key, value in arbitration.hypothesis_scores.items()},
        reason_codes=tuple(str(code) for code in arbitration.metadata.get("arbitration_reason_codes", ())),
    )
    decision = active_judge.judge(request)
    if decision.abstained or not decision.winner_hypothesis_id:
        return arbitration, decision
    selected = next((hypothesis for hypothesis in hypotheses if str(getattr(hypothesis, "hypothesis_id", "")) == decision.winner_hypothesis_id), None)
    if selected is None:
        return arbitration, decision
    metadata = dict(arbitration.metadata)
    metadata["hard_page_judge_applied"] = True
    metadata["hard_page_judge_reason_codes"] = list(decision.reason_codes)
    metadata["hard_page_judge_winner_hypothesis_id"] = decision.winner_hypothesis_id
    metadata["winner_hypothesis_id"] = str(getattr(selected, "hypothesis_id", metadata.get("winner_hypothesis_id", "unknown")))
    metadata["winner"] = str(getattr(selected, "source", metadata.get("winner", "unknown")))
    replaced = PageArbitrationResult(
        selected_blocks=tuple(getattr(selected, "page_blocks", arbitration.selected_blocks)),
        selected_tables=tuple(getattr(selected, "table_regions", arbitration.selected_tables)),
        hypothesis_scores=arbitration.hypothesis_scores,
        repeated_header_texts=arbitration.repeated_header_texts,
        repeated_footer_texts=arbitration.repeated_footer_texts,
        disagreements=arbitration.disagreements,
        metadata=metadata,
    )
    return replaced, decision
