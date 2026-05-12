from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from typing import Callable

from orbitbrief_core.parser.graph.neural_hooks import ScoreResult, SupportRequest


@dataclass(slots=True)
class SupportScoringService:
    """Optional backend scorer for anchor/support candidates."""

    model_name: str = "support:heuristic"
    backend: Callable[[SupportRequest], float | None] | None = None
    enabled: bool = True
    timeout_ms: int = 350
    max_context_chars: int = 640

    def score(self, request: SupportRequest) -> ScoreResult:
        if not self.enabled:
            return ScoreResult(score=None, model_name=self.model_name, abstained=True, raw_metadata={"reason": "policy_disabled"})
        if self.backend is None:
            return ScoreResult(score=None, model_name=self.model_name, abstained=True, raw_metadata={"reason": "backend_unavailable"})
        bounded = SupportRequest(
            anchor_span_id=request.anchor_span_id,
            candidate_span_id=request.candidate_span_id,
            anchor_text=str(request.anchor_text or "")[: max(32, self.max_context_chars)],
            candidate_text=str(request.candidate_text or "")[: max(32, self.max_context_chars)],
            signals=request.signals,
            metadata=dict(request.metadata),
        )
        timeout_s = max(0.05, float(self.timeout_ms) / 1000.0)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.backend, bounded)
                value = future.result(timeout=timeout_s)
        except FuturesTimeoutError:
            return ScoreResult(score=None, model_name=self.model_name, abstained=True, raw_metadata={"reason": "backend_timeout"})
        except Exception:
            return ScoreResult(score=None, model_name=self.model_name, abstained=True, raw_metadata={"reason": "backend_error"})
        if value is None:
            return ScoreResult(score=None, model_name=self.model_name, abstained=True, raw_metadata={"reason": "backend_abstained"})
        score = max(0.0, min(1.0, float(value)))
        return ScoreResult(score=score, model_name=self.model_name, abstained=False, raw_metadata={"reason": "score_produced"})
