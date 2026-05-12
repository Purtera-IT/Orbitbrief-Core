from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from typing import Callable

from orbitbrief_core.parser.graph.neural_hooks import PacketSeedRequest, ScoreResult


@dataclass(slots=True)
class PacketSeedScoringService:
    """Optional backend scorer for packet-seed anchor quality."""

    model_name: str = "packet_seed:heuristic"
    backend: Callable[[PacketSeedRequest], float | None] | None = None
    enabled: bool = True
    timeout_ms: int = 350
    max_context_chars: int = 640

    def score(self, request: PacketSeedRequest) -> ScoreResult:
        if not self.enabled:
            return ScoreResult(score=None, model_name=self.model_name, abstained=True, raw_metadata={"reason": "policy_disabled"})
        if self.backend is None:
            return ScoreResult(score=None, model_name=self.model_name, abstained=True, raw_metadata={"reason": "backend_unavailable"})
        bounded = PacketSeedRequest(
            span_id=request.span_id,
            text=str(request.text or "")[: max(32, self.max_context_chars)],
            family_hints=tuple(request.family_hints),
            authority_class=request.authority_class,
            authority_score=float(request.authority_score),
            local_support_density=float(request.local_support_density),
            cue_strength=float(request.cue_strength),
            signals=dict(request.signals),
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
