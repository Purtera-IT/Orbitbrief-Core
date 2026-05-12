from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HardpageGateResult:
    hardpage_requirement_truth_ok: bool
    reasons: tuple[str, ...]


def enforce_hardpage_truth(
    *,
    required_page_types: list[str],
    satisfied_page_types: list[str],
    hardpage_grounded_symbol_yield_rate: float,
    hardpage_family_grounded_coverage_rate: float,
) -> HardpageGateResult:
    reasons: list[str] = []
    ok = True
    if not required_page_types:
        ok = False
        reasons.append("empty_required_page_types")
    if required_page_types and not set(satisfied_page_types):
        ok = False
        reasons.append("no_satisfied_required_pages")
    if float(hardpage_grounded_symbol_yield_rate) < 0.65:
        ok = False
        reasons.append("hardpage_grounded_yield_too_low")
    if float(hardpage_family_grounded_coverage_rate) < 0.8:
        ok = False
        reasons.append("hardpage_family_coverage_too_low")
    return HardpageGateResult(hardpage_requirement_truth_ok=ok, reasons=tuple(reasons))
