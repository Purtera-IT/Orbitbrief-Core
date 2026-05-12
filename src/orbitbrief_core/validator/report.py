"""Output schema for the validator.

A :class:`ValidationReport` is a per-item verdict: each item the
brain emitted gets either a ``passed`` slot (with no failures) or
a ``failed`` slot listing every rule that fired. We never raise
on validation — the calibrator wants to consult the report and
make a probabilistic call about what to do.
"""
from __future__ import annotations

from collections import Counter
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ValidationSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    BLOCKER = "blocker"


class ValidationRuleId(str, Enum):
    """Stable, append-only set of validator rule ids."""

    PATH_LEGALITY = "path_legality"  # claim → packet → atom → source_ref
    UNRESOLVED_PACKET = "unresolved_packet"  # cited packet not in bundle
    UNRESOLVED_ATOM = "unresolved_atom"  # cited atom not in lookup
    MISSING_SOURCE_REF = "missing_source_ref"  # atom has no locator/source
    MISSING_EVIDENCE = "missing_evidence"  # item ground-truth-thin
    SITE_COUNT_SANITY = "site_count_sanity"  # quantity vs SiteRealityState
    PACK_INCOMPATIBILITY = "pack_incompatibility"  # mutually exclusive packs
    IMPOSSIBLE_STATE = "impossible_state"  # active item cites failed-replay atom
    SCHEMA_DRIFT = "schema_drift"  # field outside known section


class ItemRef(BaseModel):
    """Stable handle for a brain-emitted item across validator + queue."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: str
    compile_id: str
    brain: str  # e.g. "managed_services"
    section: str  # e.g. "scope_items"
    item_id: str  # the brain-emitted id

    @property
    def composite_id(self) -> str:
        return f"{self.project_id}/{self.compile_id}/{self.brain}/{self.section}/{self.item_id}"


class ValidationFailure(BaseModel):
    """One rule firing on one item."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: ValidationRuleId
    severity: ValidationSeverity
    message: str = Field(min_length=1, max_length=500)
    detail: dict[str, Any] = Field(default_factory=dict)


class ItemValidation(BaseModel):
    """Per-item verdict: zero or more failures."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item: ItemRef
    failures: tuple[ValidationFailure, ...] = ()

    @property
    def passed(self) -> bool:
        return not any(
            f.severity is not ValidationSeverity.INFO for f in self.failures
        )

    @property
    def has_blocker(self) -> bool:
        return any(f.severity is ValidationSeverity.BLOCKER for f in self.failures)


class ValidationReport(BaseModel):
    """Full report over one brain output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: str
    compile_id: str
    brain: str
    items: tuple[ItemValidation, ...]
    # Project-level rule firings (e.g. pack_incompatibility) live
    # here so reviewers see them once, not per-item.
    project_failures: tuple[ValidationFailure, ...] = ()

    @property
    def passed_items(self) -> tuple[ItemValidation, ...]:
        return tuple(i for i in self.items if i.passed)

    @property
    def failed_items(self) -> tuple[ItemValidation, ...]:
        return tuple(i for i in self.items if not i.passed)

    @property
    def blocker_items(self) -> tuple[ItemValidation, ...]:
        return tuple(i for i in self.items if i.has_blocker)

    def rule_counts(self) -> dict[str, int]:
        c: Counter = Counter()
        for iv in self.items:
            for f in iv.failures:
                c[f.rule_id.value] += 1
        for f in self.project_failures:
            c[f.rule_id.value] += 1
        return dict(sorted(c.items()))

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
