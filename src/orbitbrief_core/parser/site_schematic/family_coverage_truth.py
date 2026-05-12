from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FamilyCoverageTruth:
    packet_expected_families: set[str]
    grounded_families: set[str]
    hardpage_expected_families: set[str]
    hardpage_grounded_families: set[str]
    expected_family_grounded_coverage_rate: float
    hardpage_family_grounded_coverage_rate: float


def compute_family_coverage_truth(
    *,
    packet_expected_families: list[str],
    grounded_families: list[str],
    hardpage_expected_families: list[str],
    hardpage_grounded_families: list[str],
) -> FamilyCoverageTruth:
    packet_expected = set(packet_expected_families)
    grounded = set(grounded_families)
    hardpage_expected = set(hardpage_expected_families)
    hardpage_grounded = set(hardpage_grounded_families)
    expected_rate = (len(packet_expected & grounded) / len(packet_expected)) if packet_expected else 1.0
    hardpage_rate = (len(hardpage_expected & hardpage_grounded) / len(hardpage_expected)) if hardpage_expected else 1.0
    return FamilyCoverageTruth(
        packet_expected_families=packet_expected,
        grounded_families=grounded,
        hardpage_expected_families=hardpage_expected,
        hardpage_grounded_families=hardpage_grounded,
        expected_family_grounded_coverage_rate=expected_rate,
        hardpage_family_grounded_coverage_rate=hardpage_rate,
    )
