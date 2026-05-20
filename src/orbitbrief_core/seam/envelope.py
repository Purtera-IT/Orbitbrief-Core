"""Pydantic schema for the ``orbitbrief.input.v2`` envelope.

Mirrors the dict shape emitted by
``app.core.orbitbrief_envelope.build_orbitbrief_envelope`` in
parser-os. This is the *consumer-side* contract: OrbitBrief asserts
that any payload it accepts is shaped this way, refuses anything
else, and uses the typed objects (not raw dicts) in downstream code.

Why mirror in OrbitBrief instead of importing from parser-os?

* Parser-os builds envelopes as ``dict[str, Any]`` today; introducing
  a Pydantic shape on the producer side would be a separate
  refactor. We can hoist these models into parser-os as a future
  hardening step.
* Even when models live in parser-os, the boundary needs *consumer*
  validation — producers can drift, and the consumer must fail loud.

Forward compatibility:

* ``schema_version`` is a ``Literal["orbitbrief.input.v2"]``. A v3
  envelope will fail validation immediately at the boundary instead
  of silently being misinterpreted. Bump the literal in lockstep
  with intentional schema changes in parser-os.
* All non-leaf models allow extra fields (``extra="allow"``) so a
  future v2.1 producer that adds non-breaking fields doesn't crash
  this consumer.
"""
from __future__ import annotations

from typing import Any, Literal

from app.core.schemas import (
    ArtifactType,
    AtomType,
    AuthorityClass,
    EdgeType,
    PacketFamily,
    PacketStatus,
    ReviewStatus,
)
from pydantic import BaseModel, ConfigDict, Field


ENVELOPE_SCHEMA_VERSION: Literal["orbitbrief.input.v2"] = "orbitbrief.input.v2"


class _Lenient(BaseModel):
    """Base for envelope shapes that should tolerate forward-compatible extras."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


# ────────────────────────────── summary ────────────────────────────────


class EnvelopeSummary(_Lenient):
    """Top-level rollup counts emitted by parser-os.

    The breakdowns (``by_*``) are open dicts because parser-os may
    grow new enum members. We type the keys as ``str`` and the
    values as ``int`` and validate enum membership downstream where
    we actually care about it.
    """

    artifact_count: int = Field(ge=0)
    page_count: int = Field(ge=0)
    atom_count: int = Field(ge=0)
    packet_count: int = Field(ge=0)
    entity_count: int = Field(default=0, ge=0)
    edge_count: int = Field(default=0, ge=0)
    cross_artifact_edge_count: int = Field(default=0, ge=0)
    by_artifact_type: dict[str, int] = Field(default_factory=dict)
    by_atom_type: dict[str, int] = Field(default_factory=dict)
    by_authority_class: dict[str, int] = Field(default_factory=dict)
    by_edge_type: dict[str, int] = Field(default_factory=dict)
    by_entity_type: dict[str, int] = Field(default_factory=dict)


# ────────────────────────────── document ───────────────────────────────


class EnvelopeDocument(_Lenient):
    """One artifact (PDF / DOCX / XLSX / transcript / email / …) inside the envelope."""

    artifact_id: str
    filename: str
    artifact_type: ArtifactType
    sha256: str
    size_bytes: int = Field(ge=0)
    parser_name: str
    parser_version: str
    # The full structured projection produced by the artifact's parser.
    # Shape varies by parser (PDF emits ``orbitbrief.structured.v1``,
    # non-PDFs emit ``orbitbrief.atom_projection.v1``). We keep this
    # as a free-form dict because re-validating per-parser shapes is
    # the parser's job — parser-os already does it before emitting.
    structured: dict[str, Any] = Field(default_factory=dict)
    atom_ids: list[str] = Field(default_factory=list)


# ────────────────────────────── atoms ──────────────────────────────────


class EnvelopeAtom(_Lenient):
    """Compact atom row (full ``EvidenceAtom`` lives in the parser-os compile result)."""

    id: str
    artifact_id: str
    atom_type: AtomType
    authority_class: AuthorityClass
    confidence: float = Field(ge=0.0, le=1.0)
    text: str
    section_path: list[str] = Field(default_factory=list)
    locator: dict[str, Any] = Field(default_factory=dict)
    # Replay state: ``verified`` / ``failed`` / ``partial`` /
    # ``unsupported`` / ``unverified``. Kept open as a string so a
    # future verifier state doesn't break the consumer.
    verified: str = "unverified"
    # A5: parser-os now surfaces ``entity_keys`` and the parser's
    # structured value on every compact atom so consumers can group
    # atoms by logical entity (e.g. ``money:total_contract_value``)
    # and detect cross-doc value contradictions, build risk register
    # tables, roll up per-site pricing, etc.
    entity_keys: list[str] = Field(default_factory=list)
    structured: dict[str, Any] = Field(default_factory=dict)


# ────────────────────────────── entities ───────────────────────────────


class EnvelopeEntity(_Lenient):
    """Compact entity row with cross-artifact provenance."""

    id: str
    entity_type: str
    canonical_key: str
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    source_atom_ids: list[str] = Field(default_factory=list)
    review_status: ReviewStatus
    confidence: float = Field(ge=0.0, le=1.0)


# ────────────────────────────── edges ──────────────────────────────────


class EnvelopeEdge(_Lenient):
    """Compact edge row."""

    id: str
    edge_type: EdgeType
    from_atom_id: str
    to_atom_id: str
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    cross_artifact: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


# ────────────────────────────── packets ────────────────────────────────


class EnvelopePacket(_Lenient):
    """Compact packet row (the OrbitBrief-facing finding unit)."""

    id: str
    family: PacketFamily
    anchor_type: str
    anchor_key: str
    status: PacketStatus
    confidence: float = Field(ge=0.0, le=1.0)
    governing_atom_ids: list[str] = Field(default_factory=list)
    supporting_atom_ids: list[str] = Field(default_factory=list)
    contradicting_atom_ids: list[str] = Field(default_factory=list)
    reason: str = ""


# ────────────────────────────── indexes ────────────────────────────────


class EnvelopeIndexes(_Lenient):
    """Pre-computed lookup indexes built by parser-os.

    All values are sorted lists for determinism; preserve that in any
    OrbitBrief-side rebuilds.
    """

    atoms_by_section_path: dict[str, list[str]] = Field(default_factory=dict)
    atoms_by_atom_type: dict[str, list[str]] = Field(default_factory=dict)
    atoms_by_authority: dict[str, list[str]] = Field(default_factory=dict)
    atoms_by_artifact: dict[str, list[str]] = Field(default_factory=dict)
    atoms_by_entity_key: dict[str, list[str]] = Field(default_factory=dict)
    edges_by_atom: dict[str, list[str]] = Field(default_factory=dict)
    entity_id_by_canonical_key: dict[str, str] = Field(default_factory=dict)


# ────────────────────────────── envelope ───────────────────────────────


class EnvelopeV2(_Lenient):
    """The ``orbitbrief.input.v2`` envelope as a typed object.

    Use :func:`orbitbrief_core.seam.loader.load_envelope` to build
    this from a JSON file path; downstream code should consume the
    typed object, never the raw dict.
    """

    schema_version: Literal["orbitbrief.input.v2"] = ENVELOPE_SCHEMA_VERSION
    project_id: str
    compile_id: str
    generated_at: str
    summary: EnvelopeSummary
    documents: list[EnvelopeDocument] = Field(default_factory=list)
    atoms: list[EnvelopeAtom] = Field(default_factory=list)
    entities: list[EnvelopeEntity] = Field(default_factory=list)
    edges: list[EnvelopeEdge] = Field(default_factory=list)
    packets: list[EnvelopePacket] = Field(default_factory=list)
    indexes: EnvelopeIndexes = Field(default_factory=EnvelopeIndexes)
