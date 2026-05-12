"""Packet-level retrieval index.

One row per packet. The embedded text is a deterministic
projection of the packet — anchor + reason + a leading slice of
governing-atom text — so search returns packets whose
human-readable description matches a query.
"""
from __future__ import annotations

from typing import Iterator

from orbitbrief_core.evidence_runtime import EvidenceRuntime, RuntimeKey
from orbitbrief_core.retrieval._index_base import _BaseIndex, _SourceRow
from orbitbrief_core.retrieval.base import INDEX_KIND_PACKET, RetrievalHit


# How many governing-atom snippets to inline in the packet's
# embedded text. Bounded to keep embeddings cheap and consistent.
MAX_GOVERNING_SNIPPETS = 3
# Per-snippet character cap (so one giant atom doesn't dominate).
SNIPPET_CHAR_CAP = 240


class PacketIndex(_BaseIndex):
    """Vector index over every packet in an envelope."""

    KIND = INDEX_KIND_PACKET

    def _iter_source_rows(
        self, runtime: EvidenceRuntime, key: RuntimeKey
    ) -> Iterator[_SourceRow]:
        envelope = runtime.to_envelope_dict(key)
        atoms_by_id = {a["id"]: a for a in (envelope.get("atoms") or [])}
        for packet in envelope.get("packets", []) or []:
            text = self._project_packet_text(packet, atoms_by_id)
            yield _SourceRow(
                ref_id=str(packet["id"]),
                text=text,
                metadata={
                    "family": str(packet.get("family", "")),
                    "anchor_type": str(packet.get("anchor_type", "")),
                    "anchor_key": str(packet.get("anchor_key", "")),
                    "status": str(packet.get("status", "")),
                },
            )

    def _hydrate_text(
        self, runtime: EvidenceRuntime, hit: RetrievalHit, key: RuntimeKey
    ) -> str:
        envelope = runtime.to_envelope_dict(key)
        atoms_by_id = {a["id"]: a for a in (envelope.get("atoms") or [])}
        for packet in envelope.get("packets", []) or []:
            if packet["id"] == hit.id:
                return self._project_packet_text(packet, atoms_by_id)
        return ""

    @staticmethod
    def _project_packet_text(packet: dict, atoms_by_id: dict[str, dict]) -> str:
        """Stable, terse text projection used for embedding + rerank.

        Format:
            family|anchor_key|reason
            • atom_text_1
            • atom_text_2
            ...

        We embed the same text we'd hand a reranker, so vector and
        rerank scores are over the same surface.
        """
        family = str(packet.get("family", ""))
        anchor_key = str(packet.get("anchor_key", ""))
        reason = str(packet.get("reason", ""))
        head = f"{family}|{anchor_key}|{reason}".strip("|")
        snippets: list[str] = []
        for atom_id in (packet.get("governing_atom_ids") or [])[:MAX_GOVERNING_SNIPPETS]:
            atom = atoms_by_id.get(atom_id)
            if atom is None:
                continue
            atom_text = str(atom.get("text", "")).strip()
            if not atom_text:
                continue
            if len(atom_text) > SNIPPET_CHAR_CAP:
                atom_text = atom_text[: SNIPPET_CHAR_CAP - 1] + "…"
            snippets.append("• " + atom_text)
        if snippets:
            return head + "\n" + "\n".join(snippets)
        return head
