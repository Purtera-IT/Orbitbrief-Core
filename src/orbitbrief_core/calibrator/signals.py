"""Signal extraction: brain item + context → typed :class:`SignalVector`.

Every value lives in [0, 1] so the linear combiner doesn't need
per-feature normalization. Where a raw input is unbounded (token
counts, atom counts) we squash with explicit, documented
formulas so a debugger can reason about the score.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from orbitbrief_core.brains._briefing import BriefingState
from orbitbrief_core.brains._retrieval_bundle import RetrievalBundle
from orbitbrief_core.brains.managed_services.schema import (
    ManagedServicesScopeState,
)
from orbitbrief_core.validator.report import (
    ItemValidation,
    ValidationSeverity,
)
from orbitbrief_core.world_model.planner.schema import BriefState


@dataclass(frozen=True)
class SignalVector:
    """All signals fed to :class:`CalibrationModel`."""

    parser_confidence: float = 0.0  # mean of cited atoms' parser confidence
    graph_confidence: float = 0.0  # placeholder for edge-quality signal
    packet_confidence: float = 0.0  # mean of cited packets' confidence
    claim_confidence: float = 0.0  # the brain's self-reported confidence
    contradiction_density: float = 0.0  # 1 - normalized contradictions
    retrieval_coverage: float = 0.0  # fraction of bundle a section uses
    ambiguity: float = 0.0  # 1 - PackPriorState margin
    example_similarity: float = 0.0  # placeholder; needs example_index hits
    validator_pass: float = 1.0  # 1.0 if no blocker, 0.0 if blocker
    validator_warning: float = 0.0  # 1.0 if any warning fired

    def as_features(self) -> dict[str, float]:
        return asdict(self)


def extract_signals(
    *,
    item,
    section: str,
    state: ManagedServicesScopeState | BriefingState,
    bundle: RetrievalBundle,
    brief: BriefState,
    item_validation: ItemValidation | None,
    parser_confidence_by_atom: dict[str, float] | None = None,
) -> SignalVector:
    """Build a :class:`SignalVector` for one brain-emitted item."""
    cited_packets = [
        p for p in bundle.all_packets if p.packet_id in item.supporting_packet_ids
    ]
    parser_confs = []
    if parser_confidence_by_atom is not None:
        for aid in item.supporting_atom_ids:
            if aid in parser_confidence_by_atom:
                parser_confs.append(float(parser_confidence_by_atom[aid]))

    parser_confidence = sum(parser_confs) / len(parser_confs) if parser_confs else 0.6
    packet_confidence = (
        sum(p.confidence for p in cited_packets) / len(cited_packets)
        if cited_packets
        else 0.5
    )
    claim_confidence = float(getattr(item, "confidence", 0.0))

    # Contradiction density: brief.contradictions per cited packet, squashed.
    cd_count = len(brief.contradictions)
    contradiction_density = 1.0 - _squash(cd_count, half_at=8)

    # Retrieval coverage: how much of the bundle does THIS section use,
    # relative to the bundle's family share for this section.
    section_packet_ids = set()
    for it in getattr(state, section):
        section_packet_ids.update(it.supporting_packet_ids)
    bundle_total = max(len(bundle.all_packets), 1)
    retrieval_coverage = min(1.0, len(section_packet_ids) / bundle_total)

    # Ambiguity: derived from BriefState's own escalation log if present.
    pack_margin = 0.5
    if isinstance(brief.escalation_log, dict):
        metrics = brief.escalation_log.get("metrics") or {}
        if "pack_margin" in metrics:
            pack_margin = max(0.0, min(1.0, float(metrics["pack_margin"])))
    ambiguity = 1.0 - pack_margin

    # Validator outputs.
    validator_pass = 1.0
    validator_warning = 0.0
    if item_validation is not None:
        if item_validation.has_blocker:
            validator_pass = 0.0
        if any(
            f.severity is ValidationSeverity.WARNING
            for f in item_validation.failures
        ):
            validator_warning = 1.0

    return SignalVector(
        parser_confidence=_clip(parser_confidence),
        graph_confidence=0.6,  # placeholder until edge confidences land
        packet_confidence=_clip(packet_confidence),
        claim_confidence=_clip(claim_confidence),
        contradiction_density=_clip(contradiction_density),
        retrieval_coverage=_clip(retrieval_coverage),
        ambiguity=_clip(ambiguity),
        example_similarity=0.5,  # placeholder until example index is wired
        validator_pass=validator_pass,
        validator_warning=validator_warning,
    )


# ────────────────────────────── helpers ────────────────────────────────


def _clip(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _squash(n: int, *, half_at: int) -> float:
    """1 - exp(-n/half_at) — smooth squashing of unbounded counts into [0, 1)."""
    if n <= 0:
        return 0.0
    return 1.0 - math.exp(-n / max(half_at, 1))
