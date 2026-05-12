"""parser-os ↔ OrbitBrief seam.

Everything in this package is the *consumer* side of the
``orbitbrief.input.v2`` envelope contract. OrbitBrief reads the
envelope JSON produced by ``parser-os`` (see
``app.core.orbitbrief_envelope``), validates it against the Pydantic
schema in :mod:`orbitbrief_core.seam.envelope`, and never reaches
behind that envelope into raw input files or parser internals.

Public surface:

* :class:`orbitbrief_core.seam.envelope.EnvelopeV2` — the schema.
* :func:`orbitbrief_core.seam.loader.load_envelope` — read + validate.
* :func:`orbitbrief_core.seam.consumer.consume_envelope` — produce a
  deterministic OrbitBrief-side summary.
* ``python -m orbitbrief_core.seam <envelope.json>`` — CLI runner.
"""
from __future__ import annotations

from orbitbrief_core.seam.consumer import (
    ConsumerSummary,
    consume_envelope,
)
from orbitbrief_core.seam.envelope import (
    ENVELOPE_SCHEMA_VERSION,
    EnvelopeAtom,
    EnvelopeDocument,
    EnvelopeEdge,
    EnvelopeEntity,
    EnvelopeIndexes,
    EnvelopePacket,
    EnvelopeSummary,
    EnvelopeV2,
)
from orbitbrief_core.seam.loader import load_envelope, load_envelope_dict

__all__ = [
    "ENVELOPE_SCHEMA_VERSION",
    "ConsumerSummary",
    "EnvelopeAtom",
    "EnvelopeDocument",
    "EnvelopeEdge",
    "EnvelopeEntity",
    "EnvelopeIndexes",
    "EnvelopePacket",
    "EnvelopeSummary",
    "EnvelopeV2",
    "consume_envelope",
    "load_envelope",
    "load_envelope_dict",
]
