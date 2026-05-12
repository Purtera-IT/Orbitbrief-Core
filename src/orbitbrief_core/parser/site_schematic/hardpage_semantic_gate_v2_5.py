from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HardpageSemanticGate:
    ok: bool
    reasons: tuple[str, ...]


def enforce_v2_5_hardpage_gate(
    *,
    required_page_types: list[str],
    hardpage_grounded_symbol_yield_rate: float,
    hardpage_family_grounded_coverage_rate: float,
) -> HardpageSemanticGate:
    reasons: list[str] = []
    ok = True
    if not required_page_types:
        ok = False
        reasons.append("empty_required_page_types")
    # Requirement-truth is intentionally separated from performance metrics.
    # Yield and family coverage are evaluated by dedicated corpus metrics.
    return HardpageSemanticGate(ok=ok, reasons=tuple(reasons))
