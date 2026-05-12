"""Contradiction lookups over edges in the evidence runtime.

A *contradiction* in the parser-os graph is an edge with
``edge_type == "contradicts"``. The Phase-1 spec calls for a
``contradictions_for(entity=)`` accessor; in practice callers also
need to ask "what contradicts atom X" so we accept either anchor.

This module is pure SQL + dict transforms — no LLM, no inference.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from orbitbrief_core.evidence_runtime.store import (
    EnvelopeKey,
    EvidenceStore,
)


CONTRADICTS_EDGE_TYPE = "contradicts"


@dataclass(frozen=True)
class ContradictionPair:
    """One ``contradicts`` edge with the two atoms it connects.

    ``edge`` is the raw envelope edge dict; ``from_atom`` /
    ``to_atom`` are the resolved compact atom rows on either end.
    Either side may be ``None`` if the atom row is missing — that's
    a graph-integrity bug in the producer, but we return it instead
    of raising so the caller can flag it.
    """

    edge: dict[str, Any]
    from_atom: dict[str, Any] | None
    to_atom: dict[str, Any] | None


def contradictions_for(
    store: EvidenceStore,
    key: EnvelopeKey,
    *,
    entity: str | None = None,
    atom_id: str | None = None,
) -> list[ContradictionPair]:
    """All contradiction pairs touching ``entity`` or ``atom_id``.

    Exactly one of ``entity`` (canonical_key) or ``atom_id`` must be
    provided. Results are deterministic, ordered by the underlying
    edge id.

    For ``entity``: we first resolve to the set of atom_ids that
    carry that entity_key (via the side index), then collect every
    ``contradicts`` edge whose endpoint is in that set.

    For ``atom_id``: every contradiction edge with this atom on
    either end.
    """
    if (entity is None) == (atom_id is None):
        raise ValueError("contradictions_for: pass exactly one of entity= or atom_id=")

    atom_ids: set[str]
    if entity is not None:
        atom_ids = {
            str(a["id"])
            for a in store.iter_atoms_for_entity_key(key, entity)
        }
    else:
        assert atom_id is not None
        atom_ids = {atom_id}

    if not atom_ids:
        return []

    seen_edge_ids: set[str] = set()
    pairs: list[ContradictionPair] = []

    # We pull the contradiction edges in two passes (from / to) and
    # de-dupe by edge id. DuckDB IN-list with a placeholder requires
    # generating SQL with the right number of ?s; for small atom_id
    # sets that's fine, and Phase-1 entity contradictions are
    # typically a handful of atoms.
    placeholders = ",".join("?" for _ in atom_ids)
    base_params: list[Any] = [key.project_id, key.compile_id, CONTRADICTS_EDGE_TYPE]

    # FROM-side
    sql_from = (
        f"SELECT data FROM edges "
        f"WHERE project_id=? AND compile_id=? AND edge_type=? "
        f"AND from_atom_id IN ({placeholders}) "
        f"ORDER BY edge_id"
    )
    for (blob,) in store.connection.execute(
        sql_from, base_params + list(atom_ids)
    ).fetchall():
        edge = _decode_edge(blob)
        if edge["id"] in seen_edge_ids:
            continue
        seen_edge_ids.add(edge["id"])
        pairs.append(_resolve_pair(store, key, edge))

    # TO-side
    sql_to = (
        f"SELECT data FROM edges "
        f"WHERE project_id=? AND compile_id=? AND edge_type=? "
        f"AND to_atom_id IN ({placeholders}) "
        f"ORDER BY edge_id"
    )
    for (blob,) in store.connection.execute(
        sql_to, base_params + list(atom_ids)
    ).fetchall():
        edge = _decode_edge(blob)
        if edge["id"] in seen_edge_ids:
            continue
        seen_edge_ids.add(edge["id"])
        pairs.append(_resolve_pair(store, key, edge))

    pairs.sort(key=lambda p: p.edge["id"])
    return pairs


def _decode_edge(blob: Any) -> dict[str, Any]:
    import json

    return json.loads(blob)


def _resolve_pair(
    store: EvidenceStore, key: EnvelopeKey, edge: dict[str, Any]
) -> ContradictionPair:
    return ContradictionPair(
        edge=edge,
        from_atom=store.fetch_atom(key, str(edge["from_atom_id"])),
        to_atom=store.fetch_atom(key, str(edge["to_atom_id"])),
    )
