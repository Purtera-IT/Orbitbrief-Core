"""Assemble typed :class:`RetrievalBundle` instances from an :class:`EvidenceRuntime`.

Brains can't read the runtime directly (Phase-5 isolation rules),
so the orchestrator runs this assembler *for them*. Per active
pack, we collect packets across every relevant family, attach
the cited atoms' compact text snippets, and emit one
:class:`RetrievalBundle` per pack.

Heuristic for "relevant family":

* Until we hit retrieval-driven family selection (Phase 8+), we
  use the union of every family across all packets in the
  envelope. Most engagements yield 5–30 packets total — the
  brain's prompt-side cap (``_PACKETS_PER_FAMILY_CAP=12``) keeps
  prompt size predictable regardless.
* Atom snippets are pre-trimmed to :data:`_MAX_SNIPPET_CHARS`
  characters (240) so a chatty atom can't blow out the prompt.
* Per-family cap (:data:`_PACKETS_PER_FAMILY_CAP=25`) is a
  defense in depth; the prompt builder caps again.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from orbitbrief_core.brains._retrieval_bundle import (
    PacketSnippet,
    RetrievalBundle,
)
from orbitbrief_core.evidence_runtime.runtime import EvidenceRuntime, RuntimeKey


_PACKETS_PER_FAMILY_CAP = 25
_MAX_SNIPPET_CHARS = 240


@dataclass
class BundleAssembler:
    """Stateless wrapper around an :class:`EvidenceRuntime`."""

    runtime: EvidenceRuntime
    key: RuntimeKey | None = None

    def assemble(self, *, pack_id: str) -> RetrievalBundle:
        """One :class:`RetrievalBundle` for ``pack_id`` (today: pack-agnostic)."""
        rk = self.key or self.runtime.default_key
        if rk is None:
            raise ValueError("BundleAssembler.assemble: runtime has no default key")

        envelope = self.runtime.to_envelope_dict(rk)
        atom_index: dict[str, dict[str, Any]] = {
            a["id"]: a for a in (envelope.get("atoms") or ())
        }

        # We pull packets directly from the envelope (rather than
        # via runtime.packets_for(family=...)) so this is one DB read.
        packets = envelope.get("packets") or []
        by_family: dict[str, list[PacketSnippet]] = defaultdict(list)
        for raw in packets:
            family = raw.get("family") or ""
            if not family:
                continue
            if len(by_family[family]) >= _PACKETS_PER_FAMILY_CAP:
                continue
            snippet = self._packet_to_snippet(raw, atom_index)
            by_family[family].append(snippet)

        # Sort each family by packet_id so two runs over byte-identical
        # envelopes produce byte-identical bundles.
        packets_by_family = {
            family: tuple(sorted(snips, key=lambda p: p.packet_id))
            for family, snips in by_family.items()
        }

        return RetrievalBundle(
            project_id=rk.project_id,
            compile_id=rk.compile_id,
            packets_by_family=packets_by_family,
        )

    @staticmethod
    def _packet_to_snippet(
        raw: dict[str, Any], atom_index: dict[str, dict[str, Any]]
    ) -> PacketSnippet:
        gov = tuple(raw.get("governing_atom_ids") or ())
        sup = tuple(raw.get("supporting_atom_ids") or ())
        contra = tuple(raw.get("contradicting_atom_ids") or ())
        cited_ids = set(gov) | set(sup) | set(contra)
        atom_text: dict[str, str] = {}
        for aid in cited_ids:
            atom = atom_index.get(aid)
            if atom is None:
                continue
            text = atom.get("text") or ""
            if text:
                atom_text[aid] = text[:_MAX_SNIPPET_CHARS]
        return PacketSnippet(
            packet_id=str(raw.get("id") or ""),
            family=str(raw.get("family") or ""),
            anchor_type=str(raw.get("anchor_type") or ""),
            anchor_key=str(raw.get("anchor_key") or ""),
            status=str(raw.get("status") or ""),
            confidence=float(raw.get("confidence") or 0.0),
            governing_atom_ids=gov,
            supporting_atom_ids=sup,
            contradicting_atom_ids=contra,
            atom_text=atom_text,
        )
