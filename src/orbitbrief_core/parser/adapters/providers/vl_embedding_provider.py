from __future__ import annotations

from dataclasses import dataclass

from orbitbrief_core.parser.graph.scorers.region_relevance import RegionCandidate, RegionRelevanceRequest


def _tokenize(value: str) -> set[str]:
    return {token.lower() for token in value.split() if len(token.strip()) > 1}


@dataclass(slots=True)
class VLEmbeddingProvider:
    """Optional multimodal embedding provider wrapper.

    This default implementation is a deterministic lexical proxy. It exists as a
    fail-closed adapter boundary for future VLM/embedding backends.
    """

    available: bool = False

    def score_region_relevance(self, request: RegionRelevanceRequest) -> list[tuple[str, float]] | None:
        if not self.available:
            return None
        query_tokens = _tokenize(request.query_text)
        if not query_tokens:
            return None
        scored: list[tuple[str, float]] = []
        for region in request.candidate_regions:
            text_tokens = _tokenize(region.text)
            if not text_tokens:
                continue
            overlap = len(query_tokens & text_tokens) / max(1, len(query_tokens | text_tokens))
            scored.append((region.region_id, overlap))
        return scored


def candidate_from_block(*, region_id: str, page_index: int, bbox: tuple[float, float, float, float] | None, text: str) -> RegionCandidate:
    return RegionCandidate(
        region_id=region_id,
        page_index=page_index,
        bbox=bbox,
        text=text,
        metadata={},
    )
