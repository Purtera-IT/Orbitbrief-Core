"""Typed retrieval bundle handed to a brain by the orchestrator.

This is the boundary between the substrate and the brains. The
brain never reaches into the envelope or the retrieval store
directly; it consumes a :class:`RetrievalBundle` that the
orchestrator (a future component) populates from the Phase-2
retrieval indices and the planner's :class:`BriefState`.

Each :class:`PacketSnippet` carries enough provenance for the
brain's outputs to ground back to atoms (and via the atoms, to
source artifacts). The brain promises every claim it emits cites
``packet_id`` (resolvable in this bundle) and ``atom_id``s
(resolvable in ``packet.atom_ids``).
"""
from __future__ import annotations

from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field


class PacketSnippet(BaseModel):
    """Compact packet view for brain prompts.

    Mirrors the shape downstream brains actually need — packet id,
    family, anchor, status, governing/supporting atom ids, plus
    pre-collected text snippets so the brain can cite directly
    without walking back to the envelope.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    packet_id: str = Field(min_length=1)
    family: str = Field(min_length=1)
    anchor_type: str = ""
    anchor_key: str = ""
    status: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    governing_atom_ids: tuple[str, ...] = ()
    supporting_atom_ids: tuple[str, ...] = ()
    contradicting_atom_ids: tuple[str, ...] = ()
    # ``atom_id → text snippet`` so the brain can cite text
    # without re-fetching atoms. Snippets are pre-trimmed by the
    # orchestrator to keep prompt size predictable.
    atom_text: dict[str, str] = Field(default_factory=dict)


class RetrievalBundle(BaseModel):
    """Everything a brain needs from the retrieval substrate.

    The orchestrator builds one of these per (project, brain)
    pair. Brains read it; they never write.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: str
    compile_id: str
    # Packets keyed by family for cheap brain-side filtering.
    packets_by_family: dict[str, tuple[PacketSnippet, ...]] = Field(
        default_factory=dict
    )

    @property
    def all_packets(self) -> tuple[PacketSnippet, ...]:
        """Flat tuple in deterministic ``(family, packet_id)`` order."""
        out: list[PacketSnippet] = []
        for family in sorted(self.packets_by_family):
            for p in self.packets_by_family[family]:
                out.append(p)
        return tuple(out)

    def packets_for_families(self, families: Iterable[str]) -> tuple[PacketSnippet, ...]:
        """All packets whose family is in ``families`` (deterministic order)."""
        wanted = set(families)
        out: list[PacketSnippet] = []
        for family in sorted(wanted & set(self.packets_by_family)):
            out.extend(self.packets_by_family[family])
        return tuple(out)

    def known_packet_ids(self) -> set[str]:
        return {p.packet_id for p in self.all_packets}

    def known_atom_ids(self) -> set[str]:
        out: set[str] = set()
        for p in self.all_packets:
            out.update(p.governing_atom_ids)
            out.update(p.supporting_atom_ids)
            out.update(p.contradicting_atom_ids)
        return out
