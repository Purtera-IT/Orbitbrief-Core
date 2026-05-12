from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from typing import Callable, Mapping


@dataclass(frozen=True, slots=True)
class RegionCandidate:
    region_id: str
    page_index: int
    bbox: tuple[float, float, float, float] | None
    text: str
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RegionRelevanceRequest:
    page_index: int
    query_text: str
    candidate_regions: tuple[RegionCandidate, ...]
    packet_family_hint: str | None = None
    anchor_span_id: str | None = None
    source_span_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RegionRelevanceResult:
    region_id: str
    score: float | None
    model_name: str | None
    abstained: bool
    reason_codes: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class RegionRelevanceScoringService:
    """Optional late-stage visual region relevance scorer for hard PDF ambiguity."""

    model_name: str = "region_relevance:heuristic"
    backend: Callable[[RegionRelevanceRequest], list[tuple[str, float]] | tuple[tuple[str, float], ...] | None] | None = None
    threshold: float = 0.70
    max_fanout: int = 3
    enabled: bool = True
    timeout_ms: int = 450
    max_candidate_count: int = 8
    max_context_chars: int = 700

    def score(self, request: RegionRelevanceRequest) -> tuple[RegionRelevanceResult, ...]:
        if not self.enabled:
            return (
                RegionRelevanceResult(
                    region_id="none",
                    score=None,
                    model_name=self.model_name,
                    abstained=True,
                    reason_codes=("policy_disabled",),
                ),
            )
        if self.backend is None:
            return (
                RegionRelevanceResult(
                    region_id="none",
                    score=None,
                    model_name=self.model_name,
                    abstained=True,
                    reason_codes=("backend_unavailable",),
                ),
            )
        bounded_candidates = tuple(
            RegionCandidate(
                region_id=item.region_id,
                page_index=item.page_index,
                bbox=item.bbox,
                text=str(item.text or "")[: max(32, self.max_context_chars)],
                metadata=dict(item.metadata),
            )
            for item in tuple(request.candidate_regions)[: max(1, self.max_candidate_count)]
        )
        bounded_request = RegionRelevanceRequest(
            page_index=request.page_index,
            query_text=str(request.query_text or "")[: max(32, self.max_context_chars)],
            candidate_regions=bounded_candidates,
            packet_family_hint=request.packet_family_hint,
            anchor_span_id=request.anchor_span_id,
            source_span_ids=tuple(request.source_span_ids),
        )
        timeout_s = max(0.05, float(self.timeout_ms) / 1000.0)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.backend, bounded_request)
                raw = future.result(timeout=timeout_s)
        except FuturesTimeoutError:
            return (
                RegionRelevanceResult(
                    region_id="none",
                    score=None,
                    model_name=self.model_name,
                    abstained=True,
                    reason_codes=("backend_timeout",),
                ),
            )
        except Exception:
            return (
                RegionRelevanceResult(
                    region_id="none",
                    score=None,
                    model_name=self.model_name,
                    abstained=True,
                    reason_codes=("backend_error",),
                ),
            )
        if raw is None:
            return (
                RegionRelevanceResult(
                    region_id="none",
                    score=None,
                    model_name=self.model_name,
                    abstained=True,
                    reason_codes=("backend_abstained",),
                ),
            )
        accepted: list[RegionRelevanceResult] = []
        for region_id, score in raw:
            safe = max(0.0, min(1.0, float(score)))
            if safe < self.threshold:
                continue
            accepted.append(
                RegionRelevanceResult(
                    region_id=str(region_id),
                    score=safe,
                    model_name=self.model_name,
                    abstained=False,
                    reason_codes=("above_threshold",),
                    metadata={"bounded_candidate_count": len(bounded_candidates)},
                )
            )
        accepted = sorted(accepted, key=lambda item: float(item.score or 0.0), reverse=True)[: max(0, self.max_fanout)]
        if accepted:
            return tuple(accepted)
        return (
            RegionRelevanceResult(
                region_id="none",
                score=None,
                model_name=self.model_name,
                abstained=True,
                reason_codes=("no_region_above_threshold",),
            ),
        )
