from __future__ import annotations

from dataclasses import dataclass


@dataclass
class YieldSanity:
    grounded_yield_ok: bool
    unresolved_ratio_ok: bool
    reasons: list[str]


def check_yield_sanity(
    *,
    grounded_symbol_yield_rate: float,
    unresolved_symbol_ratio: float,
) -> YieldSanity:
    reasons = []
    grounded_ok = grounded_symbol_yield_rate >= 0.35
    unresolved_ok = unresolved_symbol_ratio <= 0.65
    if not grounded_ok:
        reasons.append("grounded_yield_too_low")
    if not unresolved_ok:
        reasons.append("unresolved_ratio_too_high")
    return YieldSanity(grounded_ok, unresolved_ok, reasons)
