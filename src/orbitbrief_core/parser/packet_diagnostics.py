from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class PacketAnchorDiagnostic:
    anchor_span_id: str
    reason_codes: tuple[str, ...]
    family_hints: tuple[str, ...]
    authority_class: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "anchor_span_id": self.anchor_span_id,
            "reason_codes": list(self.reason_codes),
            "family_hints": list(self.family_hints),
            "authority_class": self.authority_class,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class PacketInclusionDiagnostic:
    span_id: str
    inclusion_reason_codes: tuple[str, ...]
    graph_edges_used: tuple[str, ...]
    authority_class: str
    confidence: float
    role: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "inclusion_reason_codes": list(self.inclusion_reason_codes),
            "graph_edges_used": list(self.graph_edges_used),
            "authority_class": self.authority_class,
            "confidence": self.confidence,
            "role": self.role,
        }


@dataclass(frozen=True, slots=True)
class PacketExclusionDiagnostic:
    span_id: str
    exclusion_reason_codes: tuple[str, ...]
    graph_edges_considered: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "exclusion_reason_codes": list(self.exclusion_reason_codes),
            "graph_edges_considered": list(self.graph_edges_considered),
        }


@dataclass(frozen=True, slots=True)
class PacketFamilyDiagnostic:
    assigned_family: str
    rationale_codes: tuple[str, ...]
    competing_family_hints: tuple[str, ...]
    family_confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "assigned_family": self.assigned_family,
            "rationale_codes": list(self.rationale_codes),
            "competing_family_hints": list(self.competing_family_hints),
            "family_confidence": self.family_confidence,
        }


@dataclass(frozen=True, slots=True)
class PacketScoreContribution:
    component: str
    value: float
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "value": self.value,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True, slots=True)
class PacketDiagnostic:
    packet_id: str
    anchor: PacketAnchorDiagnostic
    included: tuple[PacketInclusionDiagnostic, ...]
    excluded: tuple[PacketExclusionDiagnostic, ...]
    family: PacketFamilyDiagnostic
    score_contributions: tuple[PacketScoreContribution, ...]
    graph_edges_used: tuple[str, ...]
    uncertainty_markers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "anchor": self.anchor.to_dict(),
            "included": [item.to_dict() for item in self.included],
            "excluded": [item.to_dict() for item in self.excluded],
            "family": self.family.to_dict(),
            "score_contributions": [item.to_dict() for item in self.score_contributions],
            "graph_edges_used": list(self.graph_edges_used),
            "uncertainty_markers": list(self.uncertainty_markers),
        }

    def debug_summary(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "family": self.family.assigned_family,
            "anchor_span_id": self.anchor.anchor_span_id,
            "included_count": len(self.included),
            "excluded_count": len(self.excluded),
            "uncertainty_markers": list(self.uncertainty_markers),
            "score_total": round(sum(item.value for item in self.score_contributions), 6),
        }


@dataclass(frozen=True, slots=True)
class PacketDebugBundle:
    packet_diagnostics: tuple[PacketDiagnostic, ...]
    counts_by_family: Mapping[str, int] = field(default_factory=dict)
    counts_by_uncertainty: Mapping[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_diagnostics": [item.to_dict() for item in self.packet_diagnostics],
            "counts_by_family": dict(self.counts_by_family),
            "counts_by_uncertainty": dict(self.counts_by_uncertainty),
        }


def build_packet_debug_bundle(packet_diagnostics: list[PacketDiagnostic] | tuple[PacketDiagnostic, ...]) -> PacketDebugBundle:
    family_counts: dict[str, int] = {}
    uncertainty_counts: dict[str, int] = {}
    for diagnostic in packet_diagnostics:
        family = diagnostic.family.assigned_family
        family_counts[family] = family_counts.get(family, 0) + 1
        for marker in diagnostic.uncertainty_markers:
            uncertainty_counts[marker] = uncertainty_counts.get(marker, 0) + 1
    return PacketDebugBundle(
        packet_diagnostics=tuple(packet_diagnostics),
        counts_by_family=family_counts,
        counts_by_uncertainty=uncertainty_counts,
    )


def render_packet_diagnostic(packet_diagnostic: PacketDiagnostic) -> dict[str, Any]:
    return packet_diagnostic.debug_summary()
