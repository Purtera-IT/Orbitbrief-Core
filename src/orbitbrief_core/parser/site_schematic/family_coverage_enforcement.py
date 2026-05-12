from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FamilyCoverage:
    expected_family_grounded_coverage_rate: float
    hardpage_family_grounded_coverage_rate: float
    grounded_families: set[str]
    hardpage_grounded_families: set[str]


def compute_family_coverage(
    *,
    expected_families: list[str],
    grounded_families: list[str],
    hardpage_grounded_families: list[str],
) -> FamilyCoverage:
    expected = set(expected_families)
    grounded = set(grounded_families)
    hardpage_grounded = set(hardpage_grounded_families)
    expected_rate = (len(expected & grounded) / len(expected)) if expected else 1.0
    hardpage_rate = (len(expected & hardpage_grounded) / len(expected)) if expected else 1.0
    return FamilyCoverage(
        expected_family_grounded_coverage_rate=expected_rate,
        hardpage_family_grounded_coverage_rate=hardpage_rate,
        grounded_families=grounded,
        hardpage_grounded_families=hardpage_grounded,
    )
