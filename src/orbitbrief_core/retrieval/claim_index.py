"""Claim-level retrieval index.

A *claim* is an atom that asserts something a downstream brain or
composer can act on: scope_item, quantity, constraint, exclusion,
compliance. Other atom types (entity, decision, action_item, etc.)
are evidence but not claims.

This narrower view is cheaper to embed and easier to retrieve
against precisely worded queries ("what's the headcount for site
B?", "is night work excluded?").
"""
from __future__ import annotations

from typing import Iterator

from orbitbrief_core.evidence_runtime import EvidenceRuntime, RuntimeKey
from orbitbrief_core.retrieval._index_base import _BaseIndex, _SourceRow
from orbitbrief_core.retrieval.base import INDEX_KIND_CLAIM, RetrievalHit


# The exact atom_types we treat as "claims". Pinned as a frozenset
# so callers can introspect it (and tests can pivot on the same
# definition).
CLAIM_ATOM_TYPES: frozenset[str] = frozenset(
    {
        "scope_item",
        "quantity",
        "constraint",
        "exclusion",
        "compliance",
        "customer_instruction",
    }
)


class ClaimIndex(_BaseIndex):
    """Vector index over claim-bearing atoms only."""

    KIND = INDEX_KIND_CLAIM

    def _iter_source_rows(
        self, runtime: EvidenceRuntime, key: RuntimeKey
    ) -> Iterator[_SourceRow]:
        envelope = runtime.to_envelope_dict(key)
        for atom in envelope.get("atoms", []) or []:
            if str(atom.get("atom_type", "")) not in CLAIM_ATOM_TYPES:
                continue
            yield _SourceRow(
                ref_id=str(atom["id"]),
                text=str(atom.get("text", "")),
                metadata={
                    "atom_type": str(atom.get("atom_type", "")),
                    "authority_class": str(atom.get("authority_class", "")),
                    "artifact_id": str(atom.get("artifact_id", "")),
                    "confidence": float(atom.get("confidence", 0.0)),
                },
            )

    def _hydrate_text(
        self, runtime: EvidenceRuntime, hit: RetrievalHit, key: RuntimeKey
    ) -> str:
        atom = runtime.get_atom(hit.id, key=key) or {}
        return str(atom.get("text", ""))
