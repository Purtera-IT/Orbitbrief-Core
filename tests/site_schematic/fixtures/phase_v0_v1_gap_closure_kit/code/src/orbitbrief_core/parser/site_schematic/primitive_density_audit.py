from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PrimitiveDensityAudit:
    raw_count: int
    deduped_count: int
    validated_count: int
    dedup_effectiveness: float
    sparse_graph: bool
    overly_dense_graph: bool
    sanity_ok: bool


def audit_primitive_density(
    *,
    raw_count: int,
    deduped_count: int,
    validated_count: int,
) -> PrimitiveDensityAudit:
    dedup_effectiveness = 1.0 if raw_count == 0 else deduped_count / max(1.0, raw_count)
    sparse_graph = deduped_count == 0 or validated_count == 0
    overly_dense_graph = raw_count > 200000 and dedup_effectiveness > 0.95
    sanity_ok = (not sparse_graph) and (not overly_dense_graph)
    return PrimitiveDensityAudit(
        raw_count=raw_count,
        deduped_count=deduped_count,
        validated_count=validated_count,
        dedup_effectiveness=dedup_effectiveness,
        sparse_graph=sparse_graph,
        overly_dense_graph=overly_dense_graph,
        sanity_ok=sanity_ok,
    )
