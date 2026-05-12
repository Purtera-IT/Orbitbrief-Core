"""Deterministic OrbitBrief-side summary built from the envelope.

This is the *first real consumer* of the parser-os ↔ OrbitBrief
seam. It proves the contract works end-to-end: parser-os emits an
``orbitbrief.input.v2`` envelope, OrbitBrief loads it via
:func:`orbitbrief_core.seam.loader.load_envelope`, and this module
turns it into a report-ready summary that downstream layers
(retrieval, brains, composers) can build on.

Determinism is non-negotiable:

* All counts go through ``Counter`` and serialize as ``dict``
  ordered by ``(-count, key)`` so ties break alphabetically.
* All "top-N" lists are sorted by their primary key first
  (e.g. confidence, atom count) and then by ID, so two runs over
  the same envelope produce byte-identical summaries.
* No timestamps, no random sampling, no environment lookups.

If you add a field, keep this property — Phase 2 retrieval and
calibration depend on it for replay equality.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from orbitbrief_core.seam.envelope import (
    EnvelopeAtom,
    EnvelopeEdge,
    EnvelopeEntity,
    EnvelopePacket,
    EnvelopeV2,
)


# ────────────────────────────── output shape ───────────────────────────


class TopAtom(BaseModel):
    """Atom singled out for visibility in the summary (e.g. high-confidence)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    artifact_id: str
    atom_type: str
    authority_class: str
    confidence: float
    text: str
    section_path: list[str]
    verified: str


class TopEntity(BaseModel):
    """Entity ranked by how many atoms across how many artifacts mention it."""

    model_config = ConfigDict(extra="forbid")

    id: str
    entity_type: str
    canonical_name: str
    canonical_key: str
    review_status: str
    atom_count: int
    artifact_count: int


class TopPacket(BaseModel):
    """Packet singled out for visibility (highest-confidence active findings)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    family: str
    status: str
    confidence: float
    anchor_key: str
    governing_atom_count: int
    supporting_atom_count: int
    contradicting_atom_count: int
    reason: str


class VerificationBreakdown(BaseModel):
    """Distribution of atom replay states (verified / failed / partial / unsupported / unverified)."""

    model_config = ConfigDict(extra="forbid")

    verified: int = 0
    failed: int = 0
    partial: int = 0
    unsupported: int = 0
    unverified: int = 0


class ConsumerSummary(BaseModel):
    """Deterministic OrbitBrief-side summary of one envelope.

    Bytes-equal across re-runs of the same envelope. Safe to diff
    in CI to detect upstream parser-os drift.
    """

    model_config = ConfigDict(extra="forbid")

    # Identity / provenance — straight from the envelope so the
    # summary is self-describing for archival.
    schema_version: str
    project_id: str
    compile_id: str
    generated_at: str

    # Counts
    artifact_count: int
    atom_count: int
    packet_count: int
    entity_count: int
    edge_count: int
    cross_artifact_edge_count: int

    # Breakdowns (counts ordered by -count, key)
    by_artifact_type: dict[str, int]
    by_atom_type: dict[str, int]
    by_authority_class: dict[str, int]
    by_edge_type: dict[str, int]
    by_entity_type: dict[str, int]
    by_packet_family: dict[str, int]
    by_packet_status: dict[str, int]

    # Verification health (atom-level replay states)
    verification: VerificationBreakdown

    # Highlight reels — bounded length so the summary stays small
    # even on large projects. Tune via ``consume_envelope`` kwargs.
    top_entities: list[TopEntity]
    top_atoms_by_confidence: list[TopAtom]
    top_packets_by_confidence: list[TopPacket]


# ────────────────────────────── helpers ────────────────────────────────


def _ordered_count(counter: Counter[str]) -> dict[str, int]:
    """Counter → dict ordered by ``(-count, key)`` for deterministic JSON output."""
    return {
        key: count
        for key, count in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    }


def _atoms_per_entity(
    entities: list[EnvelopeEntity],
) -> dict[str, tuple[int, int]]:
    """Map entity_id → (atom_count, artifact_count) for ranking.

    The envelope already carries ``source_atom_ids`` and
    ``artifact_ids`` per entity, so this is a pure projection — no
    cross-referencing needed against the atoms list.
    """
    out: dict[str, tuple[int, int]] = {}
    for entity in entities:
        out[entity.id] = (
            len(entity.source_atom_ids),
            len(entity.artifact_ids),
        )
    return out


def _verification_breakdown(atoms: list[EnvelopeAtom]) -> VerificationBreakdown:
    """Bucket atoms by their replay-receipt verification state."""
    bucket = Counter(a.verified for a in atoms)
    return VerificationBreakdown(
        verified=bucket.get("verified", 0),
        failed=bucket.get("failed", 0),
        partial=bucket.get("partial", 0),
        unsupported=bucket.get("unsupported", 0),
        unverified=bucket.get("unverified", 0),
    )


def _top_entities(
    entities: list[EnvelopeEntity],
    *,
    limit: int,
) -> list[TopEntity]:
    """Rank entities by atom_count desc, then artifact_count desc, then id asc."""
    counts = _atoms_per_entity(entities)
    ranked = sorted(
        entities,
        key=lambda e: (
            -counts.get(e.id, (0, 0))[0],
            -counts.get(e.id, (0, 0))[1],
            e.id,
        ),
    )
    out: list[TopEntity] = []
    for entity in ranked[:limit]:
        atom_count, artifact_count = counts.get(entity.id, (0, 0))
        out.append(
            TopEntity(
                id=entity.id,
                entity_type=entity.entity_type,
                canonical_name=entity.canonical_name,
                canonical_key=entity.canonical_key,
                review_status=entity.review_status.value,
                atom_count=atom_count,
                artifact_count=artifact_count,
            )
        )
    return out


def _top_atoms_by_confidence(
    atoms: list[EnvelopeAtom],
    *,
    limit: int,
) -> list[TopAtom]:
    """Rank atoms by confidence desc, then id asc — deterministic on ties."""
    ranked = sorted(atoms, key=lambda a: (-a.confidence, a.id))
    return [
        TopAtom(
            id=a.id,
            artifact_id=a.artifact_id,
            atom_type=a.atom_type.value,
            authority_class=a.authority_class.value,
            confidence=a.confidence,
            text=a.text,
            section_path=list(a.section_path),
            verified=a.verified,
        )
        for a in ranked[:limit]
    ]


def _top_packets_by_confidence(
    packets: list[EnvelopePacket],
    *,
    limit: int,
) -> list[TopPacket]:
    """Rank packets by confidence desc, then id asc."""
    ranked = sorted(packets, key=lambda p: (-p.confidence, p.id))
    return [
        TopPacket(
            id=p.id,
            family=p.family.value,
            status=p.status.value,
            confidence=p.confidence,
            anchor_key=p.anchor_key,
            governing_atom_count=len(p.governing_atom_ids),
            supporting_atom_count=len(p.supporting_atom_ids),
            contradicting_atom_count=len(p.contradicting_atom_ids),
            reason=p.reason,
        )
        for p in ranked[:limit]
    ]


def _cross_artifact_edge_count(edges: list[EnvelopeEdge]) -> int:
    """Count edges flagged as crossing artifact boundaries.

    Trust the envelope's pre-computed ``cross_artifact`` flag — but
    if it's missing for a row (older producer), fall back to the
    metadata bag so we never undercount.
    """
    n = 0
    for edge in edges:
        if edge.cross_artifact or edge.metadata.get("cross_artifact"):
            n += 1
    return n


# ────────────────────────────── public API ─────────────────────────────


def consume_envelope(
    envelope: EnvelopeV2,
    *,
    top_n_entities: int = 10,
    top_n_atoms: int = 10,
    top_n_packets: int = 10,
) -> ConsumerSummary:
    """Build the OrbitBrief summary from a validated v2 envelope.

    Args:
        envelope: parsed :class:`EnvelopeV2` (use
            :func:`orbitbrief_core.seam.loader.load_envelope` to
            build one from JSON).
        top_n_entities, top_n_atoms, top_n_packets: cap the
            highlight reels. Defaults to 10 each — small enough to
            review at a glance, large enough for sanity checks.

    Returns:
        :class:`ConsumerSummary` — deterministic; identical envelopes
        produce byte-identical summaries.
    """
    by_packet_family: Counter[str] = Counter(p.family.value for p in envelope.packets)
    by_packet_status: Counter[str] = Counter(p.status.value for p in envelope.packets)

    return ConsumerSummary(
        schema_version=envelope.schema_version,
        project_id=envelope.project_id,
        compile_id=envelope.compile_id,
        generated_at=envelope.generated_at,
        artifact_count=envelope.summary.artifact_count,
        atom_count=envelope.summary.atom_count,
        packet_count=envelope.summary.packet_count,
        entity_count=envelope.summary.entity_count,
        edge_count=envelope.summary.edge_count,
        cross_artifact_edge_count=(
            envelope.summary.cross_artifact_edge_count
            or _cross_artifact_edge_count(envelope.edges)
        ),
        by_artifact_type=_ordered_count(Counter(envelope.summary.by_artifact_type)),
        by_atom_type=_ordered_count(Counter(envelope.summary.by_atom_type)),
        by_authority_class=_ordered_count(Counter(envelope.summary.by_authority_class)),
        by_edge_type=_ordered_count(Counter(envelope.summary.by_edge_type)),
        by_entity_type=_ordered_count(Counter(envelope.summary.by_entity_type)),
        by_packet_family=_ordered_count(by_packet_family),
        by_packet_status=_ordered_count(by_packet_status),
        verification=_verification_breakdown(envelope.atoms),
        top_entities=_top_entities(envelope.entities, limit=top_n_entities),
        top_atoms_by_confidence=_top_atoms_by_confidence(
            envelope.atoms, limit=top_n_atoms
        ),
        top_packets_by_confidence=_top_packets_by_confidence(
            envelope.packets, limit=top_n_packets
        ),
    )
