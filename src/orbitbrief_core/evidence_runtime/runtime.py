"""High-level :class:`EvidenceRuntime` facade for the Phase-1 substrate.

Wraps an :class:`EvidenceStore` with an opinionated, typed read API
that downstream layers (retrieval, brains, validator) should use
exclusively. The store underneath is an implementation detail.

Construction:
    EvidenceRuntime.from_envelope(envelope: EnvelopeV2 | dict, db_path=None)
    EvidenceRuntime.from_envelope_path(path: Path, db_path=None)

The runtime keeps the most-recently-loaded envelope's
:class:`RuntimeKey` (``project_id`` + ``compile_id``) as a default
context so caller-supplied keys are optional in the common single-
project case.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from orbitbrief_core.evidence_runtime.contradictions import (
    ContradictionPair,
    contradictions_for,
)
from orbitbrief_core.evidence_runtime.provenance import (
    ReplayResult,
    replay_source,
)
from orbitbrief_core.evidence_runtime.store import (
    EnvelopeKey,
    EvidenceStore,
)
from orbitbrief_core.seam.envelope import EnvelopeV2
from orbitbrief_core.seam.loader import load_envelope, load_envelope_dict


@dataclass(frozen=True)
class RuntimeKey:
    """Stable identifier for one compile within the runtime."""

    project_id: str
    compile_id: str

    def to_envelope_key(self) -> EnvelopeKey:
        return EnvelopeKey(project_id=self.project_id, compile_id=self.compile_id)


class EvidenceRuntime:
    """Facade over :class:`EvidenceStore` with the Phase-1 read API."""

    def __init__(self, store: EvidenceStore, *, default_key: RuntimeKey | None = None) -> None:
        self._store = store
        self._default_key = default_key

    # ───── construction ─────

    @classmethod
    def from_envelope(
        cls,
        envelope: EnvelopeV2 | dict[str, Any],
        *,
        db_path: Path | str | None = None,
        artifact_dir: Path | str | None = None,
    ) -> "EvidenceRuntime":
        """Validate, ingest, and return a runtime backed by a fresh store.

        Args:
            envelope: parsed :class:`EnvelopeV2` or a raw dict (the
                dict will be re-validated).
            db_path: where to persist DuckDB; ``None`` → in-memory.
            artifact_dir: directory holding the original input files
                (PDFs, DOCX, …) for provenance replay. ``None`` →
                replay returns ``unsupported``.
        """
        if isinstance(envelope, EnvelopeV2):
            # Validate via Pydantic dump → dict so the lossless blob
            # persisted by the store reflects exactly what the
            # consumer would see.
            envelope_dict: dict[str, Any] = envelope.model_dump(mode="json")
        else:
            # Re-validate raw dicts at the boundary; rejects v3,
            # missing required fields, etc.
            envelope_dict = load_envelope_dict(envelope).model_dump(mode="json")
            # Use the original dict (not the Pydantic-roundtripped
            # one) for storage so producer-side field ordering is
            # preserved for byte-identical re-emit.
            envelope_dict = envelope

        store = EvidenceStore.connect(db_path)
        key = store.ingest_envelope(envelope_dict)
        # Populate the entity-key side index from the envelope's
        # pre-built indexes block.
        indexes = envelope_dict.get("indexes") or {}
        store.ingest_atom_entity_keys_index(
            key, indexes.get("atoms_by_entity_key") or {}
        )
        runtime_key = RuntimeKey(project_id=key.project_id, compile_id=key.compile_id)
        runtime = cls(store, default_key=runtime_key)
        if artifact_dir is not None:
            runtime._artifact_dir = Path(artifact_dir)  # type: ignore[attr-defined]
        return runtime

    @classmethod
    def from_envelope_path(
        cls,
        path: Path | str,
        *,
        db_path: Path | str | None = None,
        artifact_dir: Path | str | None = None,
    ) -> "EvidenceRuntime":
        """Read a JSON envelope file (the Phase-0 seam) and ingest it."""
        envelope = load_envelope(path)
        return cls.from_envelope(
            envelope,
            db_path=db_path,
            artifact_dir=artifact_dir,
        )

    # ───── lifecycle ─────

    def close(self) -> None:
        self._store.close()

    def __enter__(self) -> "EvidenceRuntime":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    # ───── identity ─────

    @property
    def store(self) -> EvidenceStore:
        return self._store

    @property
    def default_key(self) -> RuntimeKey | None:
        return self._default_key

    @property
    def artifact_dir(self) -> Path | None:
        return getattr(self, "_artifact_dir", None)

    def list_keys(self) -> list[RuntimeKey]:
        return [
            RuntimeKey(project_id=k.project_id, compile_id=k.compile_id)
            for k in self._store.list_envelopes()
        ]

    def _resolve_key(self, key: RuntimeKey | None) -> RuntimeKey:
        if key is not None:
            return key
        if self._default_key is None:
            raise ValueError(
                "no default RuntimeKey set; pass key= explicitly or load an envelope first"
            )
        return self._default_key

    # ───── round-trip (for tests + Phase-1 invariant) ─────

    def to_envelope_dict(self, key: RuntimeKey | None = None) -> dict[str, Any]:
        """Re-emit the original envelope dict for ``key`` (lossless)."""
        rk = self._resolve_key(key)
        out = self._store.fetch_envelope_dict(rk.to_envelope_key())
        if out is None:
            raise KeyError(f"no envelope stored for {rk}")
        return out

    def to_envelope_text(self, key: RuntimeKey | None = None) -> str:
        """Same as :meth:`to_envelope_dict` but returns the canonical JSON text."""
        rk = self._resolve_key(key)
        out = self._store.fetch_envelope_text(rk.to_envelope_key())
        if out is None:
            raise KeyError(f"no envelope stored for {rk}")
        return out

    # ───── primary read API (spec §4) ─────

    def get_atom(
        self, atom_id: str, *, key: RuntimeKey | None = None
    ) -> dict[str, Any] | None:
        """Look up one compact atom row by id; ``None`` if missing."""
        rk = self._resolve_key(key)
        return self._store.fetch_atom(rk.to_envelope_key(), atom_id)

    def get_entity(
        self, entity_id: str, *, key: RuntimeKey | None = None
    ) -> dict[str, Any] | None:
        """Look up one compact entity row by id; ``None`` if missing."""
        rk = self._resolve_key(key)
        return self._store.fetch_entity(rk.to_envelope_key(), entity_id)

    def packets_for(
        self,
        *,
        family: str | None = None,
        anchor: str | None = None,
        status: str | None = None,
        key: RuntimeKey | None = None,
    ) -> list[dict[str, Any]]:
        """Stream packets matching the spec's ``(family, anchor)`` filter.

        Returned in deterministic ``(family, anchor_key, packet_id)``
        order so two calls with the same args produce identical lists.
        """
        rk = self._resolve_key(key)
        return list(
            self._store.iter_packets(
                rk.to_envelope_key(),
                family=family,
                anchor_key=anchor,
                status=status,
            )
        )

    def contradictions_for(
        self,
        *,
        entity: str | None = None,
        atom_id: str | None = None,
        key: RuntimeKey | None = None,
    ) -> list[ContradictionPair]:
        """All ``contradicts`` edges touching ``entity`` or ``atom_id``.

        Pass exactly one of ``entity`` (canonical_key) or ``atom_id``.
        See :func:`orbitbrief_core.evidence_runtime.contradictions.contradictions_for`.
        """
        rk = self._resolve_key(key)
        return contradictions_for(
            self._store,
            rk.to_envelope_key(),
            entity=entity,
            atom_id=atom_id,
        )

    def replay_source(
        self,
        atom_id: str,
        *,
        artifact_dir: Path | str | None = None,
        key: RuntimeKey | None = None,
    ) -> ReplayResult:
        """Re-verify ``atom_id`` against original artifact bytes.

        Bridges to :func:`parser_os.app.core.source_replay.replay_source_ref`.
        ``artifact_dir`` defaults to the one supplied at runtime
        construction; pass an explicit one to override (handy for
        long-running runtimes whose source moved on disk).
        """
        rk = self._resolve_key(key)
        atom_dict = self.get_atom(atom_id, key=rk)
        if atom_dict is None:
            raise KeyError(f"unknown atom_id {atom_id!r} for {rk}")
        document = self._lookup_document(rk, atom_dict["artifact_id"])
        adir = (
            Path(artifact_dir)
            if artifact_dir is not None
            else self.artifact_dir
        )
        return replay_source(atom_dict, document=document, artifact_dir=adir)

    def _lookup_document(
        self, key: RuntimeKey, artifact_id: str
    ) -> dict[str, Any] | None:
        row = self._store.connection.execute(
            "SELECT data FROM documents WHERE project_id=? AND compile_id=? AND artifact_id=?",
            [key.project_id, key.compile_id, artifact_id],
        ).fetchone()
        if row is None:
            return None
        import json

        return json.loads(row[0])

    # ───── secondary helpers ─────

    def iter_atoms_for_entity_key(
        self, entity_key: str, *, key: RuntimeKey | None = None
    ) -> Iterator[dict[str, Any]]:
        rk = self._resolve_key(key)
        return self._store.iter_atoms_for_entity_key(rk.to_envelope_key(), entity_key)
