"""Typed atom-resolution protocol for the validator + calibrator.

The validator needs to follow the path
``claim → packet → atom → source_ref``. The first two hops live
in the :class:`RetrievalBundle` it already has. The third hop —
``atom_id → atom_dict`` (with ``locator`` / ``source_refs``) —
needs an evidence resolver. We hide that behind a tiny protocol
so the trust layer doesn't have to import :class:`EvidenceRuntime`
just to type its function signatures.

Three implementations live here:

* :class:`RuntimeEvidenceLookup` — adapts a real
  :class:`EvidenceRuntime` (the production case).
* :class:`DictEvidenceLookup` — a hand-built lookup table for
  tests.
* :class:`NullEvidenceLookup` — returns ``None`` for everything;
  the validator surfaces this as ``UNRESOLVED_ATOM`` so callers
  see they forgot to wire a real lookup.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class EvidenceLookup(Protocol):
    """Minimum shape: resolve an atom id to its atom dict."""

    def get_atom(self, atom_id: str) -> dict[str, Any] | None: ...


@dataclass
class DictEvidenceLookup:
    """In-memory lookup over ``{atom_id: atom_dict}``. Test-friendly."""

    atoms: dict[str, dict[str, Any]]

    def get_atom(self, atom_id: str) -> dict[str, Any] | None:
        return self.atoms.get(atom_id)


@dataclass
class RuntimeEvidenceLookup:
    """Adapter from :class:`EvidenceRuntime` to :class:`EvidenceLookup`.

    Imported lazily so the validator package itself doesn't need
    evidence_runtime at module-load time (the orchestrator
    constructs this with the live runtime).
    """

    runtime: Any  # EvidenceRuntime — typed as Any to avoid an upstream import dep

    def get_atom(self, atom_id: str) -> dict[str, Any] | None:
        return self.runtime.get_atom(atom_id)


class NullEvidenceLookup:
    """Returns ``None`` for every atom; surfaces as UNRESOLVED_ATOM in the report."""

    def get_atom(self, atom_id: str) -> dict[str, Any] | None:  # noqa: ARG002
        return None
