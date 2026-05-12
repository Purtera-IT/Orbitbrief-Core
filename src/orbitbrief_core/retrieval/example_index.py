"""Precedent / few-shot example retrieval.

Unlike the other three indices (which build off the live runtime),
the example index is fed by an explicit corpus of *labeled
exemplars* — past projects' high-confidence packets paired with
their human-approved composer outputs, used by Phase-4 brains for
in-context examples.

For Phase 2, what ships is the substrate: a typed
:class:`ExampleRecord`, a corpus loader (
:meth:`ExampleIndex.build_from_records`), and the same vector
search surface as the other indices. Curating the actual corpus is
out of scope for this phase.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

from pydantic import BaseModel, ConfigDict, Field

from orbitbrief_core.evidence_runtime import EvidenceRuntime, RuntimeKey
from orbitbrief_core.retrieval._index_base import _BaseIndex, _SourceRow
from orbitbrief_core.retrieval.base import INDEX_KIND_EXAMPLE, RetrievalHit


class ExampleRecord(BaseModel):
    """One labeled few-shot example for the brain stack.

    The ``input_text`` is what gets embedded; ``output_text`` is the
    target completion that downstream prompts will paste in.
    Corpus curation will pin schemas like this in
    Shared-contracts/ during Phase 4 — for now we keep them lax so
    the substrate isn't blocked.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    input_text: str
    output_text: str
    metadata: dict = Field(default_factory=dict)


# Project / compile namespace under which examples live. Examples
# aren't tied to any particular project, but the store uses a
# composite key — we use sentinel constants so all examples live
# in one logical bucket and don't collide with real envelopes.
EXAMPLES_PROJECT_ID = "__examples__"
EXAMPLES_COMPILE_ID = "__corpus__"


@dataclass
class _ExampleRuntime:
    """Adapter that lets the ``_BaseIndex`` build path consume records.

    The base class's :meth:`build` reads from an
    :class:`EvidenceRuntime`. Examples don't have one — they live
    outside the per-envelope substrate. This adapter wraps the
    record list so the same build path works without forking.
    """

    records: list[ExampleRecord] = field(default_factory=list)


class ExampleIndex(_BaseIndex):
    """Vector index over labeled few-shot examples."""

    KIND = INDEX_KIND_EXAMPLE

    def build_from_records(
        self,
        records: list[ExampleRecord],
        *,
        batch_size: int = 64,
        ensure_hnsw: bool = True,
    ) -> int:
        """Bulk-load ``records`` under the examples namespace."""
        if not records:
            return 0
        rows = [
            (r.id, {**r.metadata, "output_text": r.output_text}, vec)
            for r, vec in zip(
                records,
                self._embedder.embed([r.input_text for r in records]),
            )
        ]
        # We chunk the embed call upstream — for simplicity the
        # build_from_records does it in one batch. Re-batch if the
        # corpus grows beyond a few thousand.
        n = self._store.upsert(
            self.KIND,
            project_id=EXAMPLES_PROJECT_ID,
            compile_id=EXAMPLES_COMPILE_ID,
            rows=rows,
        )
        if ensure_hnsw:
            self._store.ensure_hnsw(self.KIND)
        return n

    def search_examples(
        self, query: str, *, top_k: int = 4
    ) -> list[RetrievalHit]:
        """Convenience: search the examples namespace without runtime ceremony."""
        from orbitbrief_core.evidence_runtime.runtime import RuntimeKey

        return self.search(
            query,
            key=RuntimeKey(
                project_id=EXAMPLES_PROJECT_ID,
                compile_id=EXAMPLES_COMPILE_ID,
            ),
            top_k=top_k,
        )

    # The base build() path requires a runtime; for examples we
    # offer build_from_records() above instead. _iter_source_rows
    # exists only to satisfy the abstract contract.
    def _iter_source_rows(
        self, runtime: EvidenceRuntime, key: RuntimeKey
    ) -> Iterator[_SourceRow]:
        raise NotImplementedError(
            "ExampleIndex builds from a record list, not an EvidenceRuntime; "
            "call build_from_records() instead of build()."
        )

    def _hydrate_text(
        self, runtime: EvidenceRuntime, hit: RetrievalHit, key: RuntimeKey
    ) -> str:
        # Examples store output_text in metadata; rerank against
        # the output (what a brain would actually emit).
        return str(hit.metadata.get("output_text", ""))
