"""Shared 9-field briefing schema used by every Phase-7.5 domain brain.

Source of truth: ``brains/data/briefing_configs.yaml``, extracted
from the AWESOME_CHASE intake workbook (PRE/POST schemas the user
authored). The same canonical 9 sections power every briefing
brain (wireless, low_voltage_cabling, rack_and_stack, datacenter,
imac) — domain differences live in the prompt + normalization
config, not in the output schema.

Each item is grounded: ``supporting_packet_ids`` is required;
``supporting_atom_ids`` is optional but encouraged. The post-call
validator + Phase-6 trust layer enforce both.

Sections (same shape, distinct semantics):

* ``scope_overview`` — narrative summary (a single string item).
* ``detailed_scope_of_services`` — list of executable activities.
* ``deliverables`` — list of customer-facing tangible outputs.
* ``assumptions`` — atomic + testable assumptions.
* ``customer_responsibilities`` — actions the customer must take.
* ``out_of_scope`` — explicit exclusions.
* ``risks_or_dependencies`` — risks + dependencies + unknowns.
* ``completion_criteria`` — objective indicators of done.
* ``open_items`` — unresolved items blocking finalization.

The schema is shared so the validator + calibrator have one
section list per brain (see :data:`CANONICAL_SECTIONS` below).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


CANONICAL_SECTIONS: tuple[str, ...] = (
    "scope_overview",
    "detailed_scope_of_services",
    "deliverables",
    "assumptions",
    "customer_responsibilities",
    "out_of_scope",
    "risks_or_dependencies",
    "completion_criteria",
    "open_items",
)


class BriefingItem(BaseModel):
    """A single grounded statement inside any 9-field section."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    statement: str = Field(min_length=1, max_length=600)
    supporting_packet_ids: tuple[str, ...]
    supporting_atom_ids: tuple[str, ...] = ()
    confidence: float = Field(ge=0.0, le=1.0)
    # Free-form metadata bucket so each domain can stash a few
    # extras (severity, deadline, deliverable_type, …) without
    # blowing the schema up. Bounded to 600 chars per value at
    # validation time below.
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _has_packet_grounding(self) -> "BriefingItem":
        if not self.supporting_packet_ids:
            raise ValueError(
                f"item {self.id!r}: supporting_packet_ids must be non-empty"
            )
        for k, v in self.metadata.items():
            if not isinstance(v, str):
                raise ValueError(f"metadata[{k!r}] must be a string")
            if len(v) > 600:
                raise ValueError(f"metadata[{k!r}] exceeds 600 chars")
        return self


class BriefingState(BaseModel):
    """Domain-agnostic 9-field briefing output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: str = Field(min_length=1)
    compile_id: str = Field(min_length=1)
    generated_at: str = Field(min_length=1)
    domain_id: str = Field(min_length=1)

    scope_overview: tuple[BriefingItem, ...] = ()
    detailed_scope_of_services: tuple[BriefingItem, ...] = ()
    deliverables: tuple[BriefingItem, ...] = ()
    assumptions: tuple[BriefingItem, ...] = ()
    customer_responsibilities: tuple[BriefingItem, ...] = ()
    out_of_scope: tuple[BriefingItem, ...] = ()
    risks_or_dependencies: tuple[BriefingItem, ...] = ()
    completion_criteria: tuple[BriefingItem, ...] = ()
    open_items: tuple[BriefingItem, ...] = ()

    # Provenance (stamped by the runner).
    model_used: str = Field(default="", max_length=80)
    token_cost: dict[str, Any] = Field(default_factory=dict)
    fallback_used: bool = False
    unresolved_packet_ids: tuple[str, ...] = ()
    unresolved_atom_ids: tuple[str, ...] = ()

    def section_items(self, section: str) -> tuple[BriefingItem, ...]:
        if section not in CANONICAL_SECTIONS:
            raise KeyError(f"unknown section {section!r}")
        return getattr(self, section)

    def all_items(self):
        for s in CANONICAL_SECTIONS:
            for it in getattr(self, s):
                yield s, it
