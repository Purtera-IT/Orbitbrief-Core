from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass
class GroundedYieldMetrics:
    grounded_symbol_yield_rate: float
    hardpage_grounded_symbol_yield_rate: float
    unresolved_symbol_ratio: float
    expected_family_grounded_coverage_rate: float


def compute_grounded_yield_metrics(
    *,
    total_candidates: int,
    grounded_symbols: int,
    unresolved_symbols: int,
    hardpage_candidates: int,
    hardpage_grounded: int,
    expected_family_total: int,
    expected_family_grounded: int,
) -> GroundedYieldMetrics:
    return GroundedYieldMetrics(
        grounded_symbol_yield_rate=(grounded_symbols / total_candidates) if total_candidates else 1.0,
        hardpage_grounded_symbol_yield_rate=(hardpage_grounded / hardpage_candidates) if hardpage_candidates else 1.0,
        unresolved_symbol_ratio=(unresolved_symbols / total_candidates) if total_candidates else 0.0,
        expected_family_grounded_coverage_rate=(expected_family_grounded / expected_family_total) if expected_family_total else 1.0,
    )
