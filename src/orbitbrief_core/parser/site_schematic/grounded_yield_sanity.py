from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class YieldSanity:
    grounded_yield_ok: bool
    unresolved_ratio_ok: bool
    reasons: tuple[str, ...]


def check_yield_sanity(
    *,
    grounded_symbol_yield_rate: float,
    unresolved_symbol_ratio: float,
) -> YieldSanity:
    grounded_ok = float(grounded_symbol_yield_rate) >= 0.0
    unresolved_ok = float(unresolved_symbol_ratio) <= 1.0
    reasons: list[str] = []
    if not grounded_ok:
        reasons.append("grounded_yield_too_low")
    if not unresolved_ok:
        reasons.append("unresolved_ratio_too_high")
    return YieldSanity(grounded_ok, unresolved_ok, tuple(reasons))
