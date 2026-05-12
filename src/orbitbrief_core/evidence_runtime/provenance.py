"""Provenance: replay an atom against original artifact bytes.

Bridges to ``parser_os.app.core.source_replay``, the per-format
verifier living in parser-os (PDF block matchers, spreadsheet row
matchers, line-range matchers, …). OrbitBrief itself never touches
the raw input file — this module reconstructs a minimal
:class:`SourceRef` and :class:`EvidenceAtom` from the envelope row
and hands them to parser-os.

The reconstruction is intentionally minimal because envelope rows are
*compact* (no normalized_text, no value, no entity_keys). For most
verifiers that's enough — they substring-match ``raw_text`` against
bytes pulled from the locator.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.core.schemas import (
    ArtifactType,
    AtomType,
    AuthorityClass,
    EvidenceAtom,
    ReviewStatus,
    SourceRef,
)
from app.core.source_replay import replay_source_ref


ReplayStatus = Literal["verified", "failed", "unsupported"]


@dataclass(frozen=True)
class ReplayResult:
    """Outcome of one provenance replay attempt.

    Attributes:
        atom_id: the envelope atom that was replayed.
        artifact_id: the artifact looked up against on disk.
        status: ``"verified"`` (bytes match), ``"failed"`` (bytes
            don't match → atom is stale or wrong), or
            ``"unsupported"`` (no verifier for this locator/format,
            or the artifact file isn't available).
        reason: human-readable explanation from parser-os.
        snippet: the exact bytes parser-os pulled from the artifact
            at the locator (or ``None`` if not extracted).
    """

    atom_id: str
    artifact_id: str
    status: ReplayStatus
    reason: str
    snippet: str | None


def replay_source(
    atom: dict[str, Any],
    *,
    document: dict[str, Any] | None,
    artifact_dir: Path | None,
) -> ReplayResult:
    """Re-verify ``atom`` against original bytes via parser-os.

    Args:
        atom: a compact envelope atom row (the dict shape stored
            under ``envelope.atoms[i]``).
        document: the matching envelope document row, used to
            resolve ``filename`` and ``artifact_type``. May be
            ``None`` if the document was pruned — replay will return
            ``unsupported``.
        artifact_dir: directory containing the original input file.
            ``None`` → replay returns ``unsupported`` (caller knows
            the source isn't on this machine).

    Returns:
        :class:`ReplayResult` — never raises for missing-file /
        unsupported cases; only schema-level reconstruction errors
        will propagate.
    """
    artifact_id = str(atom["artifact_id"])
    if document is None or artifact_dir is None:
        return ReplayResult(
            atom_id=str(atom["id"]),
            artifact_id=artifact_id,
            status="unsupported",
            reason="document or artifact_dir not available for replay",
            snippet=None,
        )

    artifact_path = Path(artifact_dir) / str(document.get("filename", ""))
    if not artifact_path.exists():
        return ReplayResult(
            atom_id=str(atom["id"]),
            artifact_id=artifact_id,
            status="unsupported",
            reason=f"original artifact not found at {artifact_path}",
            snippet=None,
        )

    artifact_type = _coerce_artifact_type(document.get("artifact_type"))
    source_ref = _build_source_ref(atom, document, artifact_type)
    minimal_atom = _build_minimal_atom(atom, source_ref)

    receipt = replay_source_ref(
        atom=minimal_atom,
        source_ref=source_ref,
        artifact_paths={artifact_id: artifact_path},
    )

    return ReplayResult(
        atom_id=str(atom["id"]),
        artifact_id=artifact_id,
        status=receipt.replay_status,  # type: ignore[arg-type]
        reason=receipt.reason,
        snippet=receipt.extracted_snippet,
    )


def _coerce_artifact_type(value: Any) -> ArtifactType:
    """Best-effort conversion of envelope ``artifact_type`` string → enum.

    Envelope rows always carry valid values (parser-os enforces it),
    but defensive coercion keeps replay robust against future
    producer drift.
    """
    if isinstance(value, ArtifactType):
        return value
    try:
        return ArtifactType(str(value))
    except ValueError:
        return ArtifactType.txt


def _build_source_ref(
    atom: dict[str, Any],
    document: dict[str, Any],
    artifact_type: ArtifactType,
) -> SourceRef:
    """Reconstruct a SourceRef sufficient for parser-os to replay.

    Envelope rows give us locator + artifact_id + filename — exactly
    what the per-format verifiers need. The ``parser_version`` and
    ``extraction_method`` fields are required by the schema but not
    used by the verifier; we fill in placeholders.
    """
    artifact_id = str(atom["artifact_id"])
    return SourceRef(
        id=f"src_replay_{atom['id']}",
        artifact_id=artifact_id,
        artifact_type=artifact_type,
        filename=str(document.get("filename", "")),
        locator=dict(atom.get("locator") or {}),
        extraction_method="orbitbrief_runtime_replay",
        parser_version=str(document.get("parser_version", "envelope_v2")),
    )


def _build_minimal_atom(atom: dict[str, Any], source_ref: SourceRef) -> EvidenceAtom:
    """Build the smallest valid EvidenceAtom that satisfies replay_source_ref.

    The verifier only reads ``id`` / ``artifact_id`` / ``raw_text``
    off the atom (for receipt construction + substring check), so
    the rest of the required schema fields get conservative
    placeholders.
    """
    return EvidenceAtom(
        id=str(atom["id"]),
        project_id="orbitbrief_runtime",
        artifact_id=str(atom["artifact_id"]),
        atom_type=_coerce_atom_type(atom.get("atom_type")),
        raw_text=str(atom.get("text", "")),
        normalized_text=str(atom.get("text", "")),
        value={"text": str(atom.get("text", ""))},
        entity_keys=[],
        source_refs=[source_ref],
        receipts=[],
        authority_class=_coerce_authority_class(atom.get("authority_class")),
        confidence=float(atom.get("confidence", 0.0)),
        review_status=ReviewStatus.auto_accepted,
        parser_version="envelope_v2",
    )


def _coerce_atom_type(value: Any) -> AtomType:
    if isinstance(value, AtomType):
        return value
    try:
        return AtomType(str(value))
    except ValueError:
        return AtomType.entity


def _coerce_authority_class(value: Any) -> AuthorityClass:
    if isinstance(value, AuthorityClass):
        return value
    try:
        return AuthorityClass(str(value))
    except ValueError:
        return AuthorityClass.machine_extractor
