from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from orbitbrief_core.parser.graph.base import ScoreDecision, ScoreResult, ScorerDiagnostic
from orbitbrief_core.parser.graph.scorers.config import ScorerPolicy


def evaluate_score_result(
    *,
    scorer_name: str,
    candidate_id: str,
    result: ScoreResult,
    policy: ScorerPolicy,
    reason_codes: Iterable[str],
) -> tuple[ScoreDecision, ScorerDiagnostic]:
    reasons = tuple(dict.fromkeys(str(code) for code in reason_codes if str(code)))
    if not policy.enabled:
        decision = ScoreDecision(
            accepted=False,
            score=result.score,
            threshold=policy.threshold,
            reason_codes=("policy_disabled",),
            model_name=result.model_name,
            candidate_rank=None,
            fanout_limited=False,
            abstained=False,
        )
        diagnostic = ScorerDiagnostic(
            scorer_name=scorer_name,
            candidate_id=candidate_id,
            accepted=False,
            score=result.score,
            threshold=policy.threshold,
            reason_codes=decision.reason_codes,
            abstained=False,
            fanout_limited=False,
            model_name=result.model_name,
            metadata=dict(result.raw_metadata),
        )
        return decision, diagnostic

    if result.abstained or result.score is None:
        reason = str(result.raw_metadata.get("reason", "score_not_produced"))
        decision = ScoreDecision(
            accepted=False,
            score=None,
            threshold=policy.threshold,
            reason_codes=(reason,),
            model_name=result.model_name,
            candidate_rank=None,
            fanout_limited=False,
            abstained=True,
        )
        diagnostic = ScorerDiagnostic(
            scorer_name=scorer_name,
            candidate_id=candidate_id,
            accepted=False,
            score=None,
            threshold=policy.threshold,
            reason_codes=decision.reason_codes,
            abstained=True,
            fanout_limited=False,
            model_name=result.model_name,
            metadata=dict(result.raw_metadata),
        )
        return decision, diagnostic

    score = max(0.0, min(1.0, float(result.score)))
    if policy.abstain_below is not None and score < policy.abstain_below:
        decision = ScoreDecision(
            accepted=False,
            score=score,
            threshold=policy.threshold,
            reason_codes=("signal_too_weak",),
            model_name=result.model_name,
            candidate_rank=None,
            fanout_limited=False,
            abstained=True,
        )
        diagnostic = ScorerDiagnostic(
            scorer_name=scorer_name,
            candidate_id=candidate_id,
            accepted=False,
            score=score,
            threshold=policy.threshold,
            reason_codes=decision.reason_codes,
            abstained=True,
            fanout_limited=False,
            model_name=result.model_name,
            metadata=dict(result.raw_metadata),
        )
        return decision, diagnostic

    if score < policy.threshold:
        decision = ScoreDecision(
            accepted=False,
            score=score,
            threshold=policy.threshold,
            reason_codes=("below_threshold",),
            model_name=result.model_name,
            candidate_rank=None,
            fanout_limited=False,
            abstained=False,
        )
        diagnostic = ScorerDiagnostic(
            scorer_name=scorer_name,
            candidate_id=candidate_id,
            accepted=False,
            score=score,
            threshold=policy.threshold,
            reason_codes=decision.reason_codes,
            abstained=False,
            fanout_limited=False,
            model_name=result.model_name,
            metadata=dict(result.raw_metadata),
        )
        return decision, diagnostic

    decision = ScoreDecision(
        accepted=True,
        score=score,
        threshold=policy.threshold,
        reason_codes=(*reasons, "above_threshold"),
        model_name=result.model_name,
        candidate_rank=None,
        fanout_limited=False,
        abstained=False,
    )
    diagnostic = ScorerDiagnostic(
        scorer_name=scorer_name,
        candidate_id=candidate_id,
        accepted=True,
        score=score,
        threshold=policy.threshold,
        reason_codes=decision.reason_codes,
        abstained=False,
        fanout_limited=False,
        model_name=result.model_name,
        metadata=dict(result.raw_metadata),
    )
    return decision, diagnostic


def apply_fanout(
    *,
    accepted: list[tuple[ScoreDecision, ScorerDiagnostic]],
    policy: ScorerPolicy,
) -> tuple[list[tuple[ScoreDecision, ScorerDiagnostic]], list[tuple[ScoreDecision, ScorerDiagnostic]]]:
    ranked = sorted(accepted, key=lambda row: float(row[0].score or 0.0), reverse=True)
    kept: list[tuple[ScoreDecision, ScorerDiagnostic]] = []
    trimmed: list[tuple[ScoreDecision, ScorerDiagnostic]] = []
    for idx, (decision, diagnostic) in enumerate(ranked, start=1):
        ranked_decision = replace(decision, candidate_rank=idx)
        ranked_diagnostic = replace(diagnostic, metadata={**dict(diagnostic.metadata), "candidate_rank": idx})
        if idx <= policy.max_fanout:
            kept.append((ranked_decision, ranked_diagnostic))
        else:
            trimmed_decision = replace(
                ranked_decision,
                accepted=False,
                fanout_limited=True,
                reason_codes=("fanout_limited", "rank_below_top_k"),
            )
            trimmed_diagnostic = replace(
                ranked_diagnostic,
                accepted=False,
                fanout_limited=True,
                reason_codes=trimmed_decision.reason_codes,
            )
            trimmed.append((trimmed_decision, trimmed_diagnostic))
    return kept, trimmed
