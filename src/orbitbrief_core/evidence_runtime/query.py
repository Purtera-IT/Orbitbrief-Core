"""Convenience query functions over an :class:`EvidenceStore`.

These are *thin* wrappers that the high-level :class:`EvidenceRuntime`
uses internally, exposed at module level so future tools can query the
store without instantiating the full runtime (e.g. CI scripts that
just want a count).

If your code is calling several of these in sequence, prefer the
runtime — it handles the default key, lifecycle, and caching.
"""
from __future__ import annotations

from typing import Any, Iterator

from orbitbrief_core.evidence_runtime.store import (
    EnvelopeKey,
    EvidenceStore,
)


def get_atom(
    store: EvidenceStore, key: EnvelopeKey, atom_id: str
) -> dict[str, Any] | None:
    """One atom row by id, or ``None``."""
    return store.fetch_atom(key, atom_id)


def get_entity(
    store: EvidenceStore, key: EnvelopeKey, entity_id: str
) -> dict[str, Any] | None:
    """One entity row by id, or ``None``."""
    return store.fetch_entity(key, entity_id)


def packets_for(
    store: EvidenceStore,
    key: EnvelopeKey,
    *,
    family: str | None = None,
    anchor: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Materialize packets matching ``(family, anchor, status)``.

    Caller-provided ``anchor`` maps to the store's ``anchor_key``
    column (the envelope's stable identifier; ``anchor_type`` is
    always inferable from family).
    """
    return list(
        store.iter_packets(key, family=family, anchor_key=anchor, status=status)
    )


def edges_from(
    store: EvidenceStore,
    key: EnvelopeKey,
    atom_id: str,
    *,
    edge_type: str | None = None,
) -> Iterator[dict[str, Any]]:
    """All edges originating at ``atom_id``, optionally filtered by type."""
    return store.iter_edges(key, edge_type=edge_type, from_atom_id=atom_id)


def edges_to(
    store: EvidenceStore,
    key: EnvelopeKey,
    atom_id: str,
    *,
    edge_type: str | None = None,
) -> Iterator[dict[str, Any]]:
    """All edges terminating at ``atom_id``, optionally filtered by type."""
    return store.iter_edges(key, edge_type=edge_type, to_atom_id=atom_id)


def atoms_for_entity_key(
    store: EvidenceStore, key: EnvelopeKey, entity_key: str
) -> Iterator[dict[str, Any]]:
    """Atoms whose entity_keys list contains ``entity_key``.

    This relies on the side index populated by
    :meth:`EvidenceStore.ingest_atom_entity_keys_index` from the
    envelope's ``indexes.atoms_by_entity_key`` block.
    """
    return store.iter_atoms_for_entity_key(key, entity_key)
