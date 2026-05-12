"""Atom-level retrieval index.

One row per atom in the envelope. Use this when callers want to
find raw evidence (any atom) similar to a query — typically for
"explain why packet X says Y" exploration.

For *claim-level* retrieval (assertable atoms only — scope_item,
quantity, constraint, exclusion, compliance) use
:class:`ClaimIndex` instead.
"""
from __future__ import annotations

from typing import Iterator

from orbitbrief_core.evidence_runtime import EvidenceRuntime, RuntimeKey
from orbitbrief_core.retrieval._index_base import _BaseIndex, _SourceRow
from orbitbrief_core.retrieval.base import INDEX_KIND_EVIDENCE, RetrievalHit


class EvidenceIndex(_BaseIndex):
    """Vector index over every atom in an envelope."""

    KIND = INDEX_KIND_EVIDENCE

    def _iter_source_rows(
        self, runtime: EvidenceRuntime, key: RuntimeKey
    ) -> Iterator[_SourceRow]:
        envelope = runtime.to_envelope_dict(key)
        for atom in envelope.get("atoms", []) or []:
            yield _SourceRow(
                ref_id=str(atom["id"]),
                text=str(atom.get("text", "")),
                metadata={
                    "atom_type": str(atom.get("atom_type", "")),
                    "authority_class": str(atom.get("authority_class", "")),
                    "artifact_id": str(atom.get("artifact_id", "")),
                    "verified": str(atom.get("verified", "unverified")),
                },
            )

    def _hydrate_text(
        self, runtime: EvidenceRuntime, hit: RetrievalHit, key: RuntimeKey
    ) -> str:
        atom = runtime.get_atom(hit.id, key=key) or {}
        return str(atom.get("text", ""))
