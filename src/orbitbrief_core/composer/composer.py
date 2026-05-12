"""``Composer`` — turns brain outputs into a typed :class:`ComposedBrief`.

The composer's job is mostly bookkeeping: walk the per-pack brain
outputs, attach each item's calibrated confidence + validator
verdict + reasons, group everything by domain section, and add a
top-level executive summary derived from the planner's
:class:`BriefState`.

Two brain shapes today:

* **Briefing brains** (Phase 7.5) — wireless, low_voltage_cabling,
  rack_and_stack, datacenter, imac. Emit :class:`BriefingState`
  with the canonical 9 sections.
* **Managed-services brain** (Phase 5) — ``msp``. Emits
  :class:`ManagedServicesScopeState` with 7 sections; we map them
  onto the 9-section briefing layout so the reviewer UI doesn't
  have to special-case it.

Output : :class:`ComposedBrief`. Everything is typed + frozen so
two runs over identical inputs produce identical documents.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field

from orbitbrief_core.brains._briefing import (
    CANONICAL_SECTIONS as _BRIEFING_SECTIONS,
    BriefingState,
)
from orbitbrief_core.brains.managed_services.schema import (
    ManagedServicesScopeState,
)
from orbitbrief_core.calibrator.calibrator import CalibratorReport
from orbitbrief_core.calibrator.verdict import EscalationReason, Verdict
from orbitbrief_core.validator.report import ValidationReport
from orbitbrief_core.world_model.planner.schema import BriefState


# ────────────────────────────── schema ─────────────────────────────────


class DomainSectionItem(BaseModel):
    """One brain item, decorated with calibrator + validator output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_id: str
    statement: str
    supporting_packet_ids: tuple[str, ...]
    supporting_atom_ids: tuple[str, ...] = ()
    raw_confidence: float = Field(ge=0.0, le=1.0)
    calibrated_confidence: float = Field(ge=0.0, le=1.0)
    verdict: Verdict
    reasons: tuple[EscalationReason, ...] = ()
    validation_failures: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)


class DomainSection(BaseModel):
    """One section under a domain (e.g. ``scope_overview``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    section_id: str  # e.g. "scope_overview"
    display_name: str
    items: tuple[DomainSectionItem, ...]

    @property
    def item_count(self) -> int:
        return len(self.items)


class DomainGroup(BaseModel):
    """All sections under one domain (one brain output)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pack_id: str
    brain: str  # "wireless", "managed_services", …
    display_name: str
    fallback_used: bool = False
    sections: tuple[DomainSection, ...]

    def section_by_id(self, section_id: str) -> DomainSection | None:
        for s in self.sections:
            if s.section_id == section_id:
                return s
        return None


class SiteRosterEntry(BaseModel):
    """One site cluster surfaced in the doc's site roster."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cluster_id: str
    canonical_name: str
    role: str
    site_keys: tuple[str, ...] = ()


class ExecutiveSummary(BaseModel):
    """Top-of-doc summary derived from the planner output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: str
    compile_id: str
    generated_at: str
    active_packs: tuple[str, ...]
    site_count: int
    contradiction_count: int
    review_flag_count: int
    planner_model: str
    planner_tier: str
    planner_fallback_used: bool = False


class ComposedBrief(BaseModel):
    """The final reviewable document."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: str
    compile_id: str
    generated_at: str
    summary: ExecutiveSummary
    sites: tuple[SiteRosterEntry, ...]
    domains: tuple[DomainGroup, ...]
    open_questions: tuple[DomainSectionItem, ...] = ()
    blocker_count: int = 0
    review_count: int = 0
    auto_accept_count: int = 0


# ────────────────────────────── inputs ─────────────────────────────────


@dataclass(frozen=True)
class ComposerInputs:
    """Per-pack brain output + reports the composer needs."""

    brief: BriefState
    # Per pack_id, the brain's typed output state.
    brain_states: dict[str, BriefingState | ManagedServicesScopeState] = field(
        default_factory=dict
    )
    calibrations: dict[str, CalibratorReport] = field(default_factory=dict)
    validations: dict[str, ValidationReport] = field(default_factory=dict)
    # Per pack_id, whether the brain's runner fell back to its skeleton.
    fallback_used: dict[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class ComposerConfig:
    """Knobs for the composer (defaults are production-sane)."""

    include_validation_failures: bool = True
    open_questions_section_ids: tuple[str, ...] = ("open_items", "open_questions")
    pack_display_names: dict[str, str] = field(
        default_factory=lambda: {
            "msp": "Managed Services",
            "wireless": "Wireless",
            "low_voltage_cabling": "Low Voltage Cabling",
            "rack_and_stack": "Rack & Stack",
            "datacenter": "Datacenter",
            "imac": "IMAC",
        }
    )
    section_display_names: dict[str, str] = field(
        default_factory=lambda: {
            # Briefing sections
            "scope_overview": "Scope Overview",
            "detailed_scope_of_services": "Detailed Scope of Services",
            "deliverables": "Deliverables",
            "assumptions": "Assumptions",
            "customer_responsibilities": "Customer Responsibilities",
            "out_of_scope": "Out of Scope",
            "risks_or_dependencies": "Risks / Dependencies",
            "completion_criteria": "Completion Criteria",
            "open_items": "Open Items",
            # Managed-services sections
            "scope_items": "Scope Items",
            "exclusions": "Exclusions",
            "milestones": "Milestones",
            "dispatch_readiness_flags": "Dispatch Readiness Flags",
            "open_questions": "Open Questions",
        }
    )


# ────────────────────────────── composer ───────────────────────────────


@dataclass
class Composer:
    """Stateless composer. One instance is safe to reuse across many briefs."""

    config: ComposerConfig = field(default_factory=ComposerConfig)

    def compose(self, inputs: ComposerInputs) -> ComposedBrief:
        brief = inputs.brief
        site_entries = self._site_roster(brief)
        domain_groups: list[DomainGroup] = []
        all_open_questions: list[DomainSectionItem] = []

        for pack_id, state in inputs.brain_states.items():
            calibration = inputs.calibrations.get(pack_id)
            validation = inputs.validations.get(pack_id)
            group = self._group_for_pack(
                pack_id=pack_id,
                state=state,
                calibration=calibration,
                validation=validation,
                fallback=inputs.fallback_used.get(pack_id, False),
            )
            domain_groups.append(group)
            all_open_questions.extend(self._extract_open_questions(group))

        blocker_count = 0
        review_count = 0
        auto_accept_count = 0
        for grp in domain_groups:
            for sec in grp.sections:
                for it in sec.items:
                    if it.verdict is Verdict.AUTO_ACCEPT:
                        auto_accept_count += 1
                    elif it.verdict is Verdict.NEEDS_REVIEW:
                        review_count += 1
                    elif it.verdict is Verdict.REJECT:
                        blocker_count += 1

        summary = ExecutiveSummary(
            project_id=brief.project_id,
            compile_id=brief.compile_id,
            generated_at=_iso_now(),
            active_packs=tuple(
                sorted(
                    {
                        pa.pack_id
                        for pa in brief.pack_activations
                        if pa.status.value == "active"
                    }
                )
            ),
            site_count=len(brief.sites),
            contradiction_count=len(brief.contradictions),
            review_flag_count=len(brief.review_flags),
            planner_model=brief.model_used or "",
            planner_tier=brief.tier or "",
            planner_fallback_used=bool(
                (brief.escalation_log or {}).get("planner_fallback")
            ),
        )

        return ComposedBrief(
            project_id=brief.project_id,
            compile_id=brief.compile_id,
            generated_at=summary.generated_at,
            summary=summary,
            sites=tuple(site_entries),
            domains=tuple(domain_groups),
            open_questions=tuple(all_open_questions),
            blocker_count=blocker_count,
            review_count=review_count,
            auto_accept_count=auto_accept_count,
        )

    # ───── internals ─────

    def _group_for_pack(
        self,
        *,
        pack_id: str,
        state: BriefingState | ManagedServicesScopeState,
        calibration: CalibratorReport | None,
        validation: ValidationReport | None,
        fallback: bool,
    ) -> DomainGroup:
        """One :class:`DomainGroup` aggregating per-section items + their decorations."""
        # Build composite_id → CalibratedItem index for O(1) lookup.
        cal_by_id = {ci.ref.composite_id: ci for ci in (calibration.items if calibration else ())}
        val_by_id = {iv.item.composite_id: iv for iv in (validation.items if validation else ())}

        section_ids, brain_label, display_name = self._sections_for(state, pack_id)
        sections: list[DomainSection] = []

        for section_id in section_ids:
            items = []
            for raw_item in getattr(state, section_id):
                composite_id = (
                    f"{state.project_id}/{state.compile_id}/"
                    f"{brain_label}/{section_id}/{raw_item.id}"
                )
                cal = cal_by_id.get(composite_id)
                val = val_by_id.get(composite_id)
                # Default values when calibrator/validator weren't run for this item.
                raw_conf = float(getattr(raw_item, "confidence", 0.0)) if cal is None else cal.raw_confidence
                cal_conf = float(getattr(raw_item, "confidence", 0.0)) if cal is None else cal.calibrated_confidence
                verdict = cal.verdict if cal else Verdict.AUTO_ACCEPT
                reasons = cal.reasons if cal else ()
                failures = (
                    tuple(_failure_dict(f) for f in (val.failures if val else ()))
                    if self.config.include_validation_failures
                    else ()
                )
                items.append(
                    DomainSectionItem(
                        item_id=raw_item.id,
                        statement=raw_item.statement,
                        supporting_packet_ids=tuple(raw_item.supporting_packet_ids),
                        supporting_atom_ids=tuple(getattr(raw_item, "supporting_atom_ids", ())),
                        raw_confidence=_clip(raw_conf),
                        calibrated_confidence=_clip(cal_conf),
                        verdict=verdict,
                        reasons=reasons,
                        validation_failures=failures,
                        metadata=_item_metadata(raw_item),
                    )
                )
            display = self.config.section_display_names.get(
                section_id, section_id.replace("_", " ").title()
            )
            sections.append(
                DomainSection(
                    section_id=section_id,
                    display_name=display,
                    items=tuple(items),
                )
            )

        return DomainGroup(
            pack_id=pack_id,
            brain=brain_label,
            display_name=display_name,
            fallback_used=fallback,
            sections=tuple(sections),
        )

    def _sections_for(
        self,
        state: BriefingState | ManagedServicesScopeState,
        pack_id: str,
    ) -> tuple[tuple[str, ...], str, str]:
        """Return (section ids in display order, brain label, display name)."""
        if isinstance(state, BriefingState):
            return (
                _BRIEFING_SECTIONS,
                state.domain_id,
                self.config.pack_display_names.get(
                    pack_id, pack_id.replace("_", " ").title()
                ),
            )
        # ManagedServicesScopeState
        return (
            (
                "scope_items",
                "exclusions",
                "customer_responsibilities",
                "milestones",
                "assumptions",
                "dispatch_readiness_flags",
                "open_questions",
            ),
            "managed_services",
            self.config.pack_display_names.get(
                pack_id, pack_id.replace("_", " ").title()
            ),
        )

    def _site_roster(self, brief: BriefState) -> list[SiteRosterEntry]:
        return [
            SiteRosterEntry(
                cluster_id=s.cluster_id,
                canonical_name=s.canonical_name,
                role=s.role.value,
            )
            for s in brief.sites
        ]

    def _extract_open_questions(
        self, group: DomainGroup
    ) -> Iterable[DomainSectionItem]:
        for sec in group.sections:
            if sec.section_id in self.config.open_questions_section_ids:
                for it in sec.items:
                    yield it


# ────────────────────────────── helpers ────────────────────────────────


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clip(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _failure_dict(failure) -> dict[str, Any]:
    return {
        "rule_id": failure.rule_id.value,
        "severity": failure.severity.value,
        "message": failure.message,
    }


def _item_metadata(raw_item) -> dict[str, Any]:
    """Pull domain-specific metadata that doesn't fit the shared shape."""
    md: dict[str, Any] = {}
    # Briefing items carry a metadata bag.
    if hasattr(raw_item, "metadata") and isinstance(raw_item.metadata, dict):
        md.update(raw_item.metadata)
    # Managed-services items carry typed extras (severity, deadline, …).
    for k in (
        "severity",
        "deadline_relative",
        "target_relative",
        "addressee",
        "rationale",
        "risk_if_false",
        "blocker_owner",
        "category",
        "status",
    ):
        v = getattr(raw_item, k, None)
        if v is None:
            continue
        # Pydantic enums dump as their .value.
        v = v.value if hasattr(v, "value") else v
        if isinstance(v, str) and v.strip():
            md[k] = v
    return md
