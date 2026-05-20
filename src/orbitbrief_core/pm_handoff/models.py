from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SourcePointer:
    filename: str
    locator: str = ""

    def display(self) -> str:
        if self.locator:
            return f"{self.filename} — {self.locator}"
        return self.filename


@dataclass(frozen=True)
class SourceFileSummary:
    filename: str
    artifact_type: str
    parser_name: str
    evidence_items: int
    # A6 graceful degradation: per-file parse outcome surfaced from
    # parser-os' envelope. ``status`` is one of: ok / ok_empty /
    # failed_parse / skipped_no_parser / unknown. ``status_reason``
    # is the human-readable failure cause (e.g. "FileDataError: ...").
    # PM_HANDOFF renderers show degraded files in a separate callout
    # so the systems engineer knows which files to manually inspect
    # instead of silently producing an envelope with fewer atoms.
    status: str = "ok"
    status_reason: str | None = None


@dataclass(frozen=True)
class SiteSummary:
    name: str
    kind: str
    publishable: bool
    member_evidence_count: int = 0
    artifact_count: int = 0


@dataclass(frozen=True)
class DomainSummary:
    domain_id: str
    label: str
    selected_by_router: bool
    active_for_sow: bool
    blockers: int = 0
    warnings: int = 0
    info: int = 0


@dataclass(frozen=True)
class GapCard:
    rule_id: str
    domain_id: str
    domain_label: str
    label: str
    severity: str
    message: str
    suggested_open_question: str
    observed_summary: str = ""


@dataclass(frozen=True)
class EvidenceCard:
    title: str
    category: str
    text: str
    source: SourcePointer
    confidence: float | None = None
    verified: str = ""
    internal_id: str = ""


@dataclass(frozen=True)
class PMHandoff:
    case_id: str
    status: str
    status_label: str
    one_line_summary: str
    metrics: dict[str, Any]
    domains: list[DomainSummary] = field(default_factory=list)
    sites: list[SiteSummary] = field(default_factory=list)
    gaps: list[GapCard] = field(default_factory=list)
    facts_by_category: dict[str, list[EvidenceCard]] = field(default_factory=dict)
    source_files: list[SourceFileSummary] = field(default_factory=list)
    sa_focus: list[str] = field(default_factory=list)
    customer_questions: list[GapCard] = field(default_factory=list)
    # A5: cross-doc numeric / date reconciliation tables. These are
    # plain-dict snapshots of MoneyMention / DateMention /
    # ReconciliationFlag so PMHandoff stays JSON-serializable via
    # ``to_dict`` without circular imports of the reconciliation
    # module. The markdown renderer reads them directly.
    money_mentions: list[dict[str, Any]] = field(default_factory=list)
    date_mentions: list[dict[str, Any]] = field(default_factory=list)
    reconciliation_flags: list[dict[str, Any]] = field(default_factory=list)
    # B2: PM-ready risk register projected from atom_type=risk rows.
    risk_register: list[dict[str, Any]] = field(default_factory=list)
    # B5: project-schedule rows projected from atom_type=schedule_phase
    # atoms. Used to render a Mermaid Gantt block + fallback table.
    schedule_phases: list[dict[str, Any]] = field(default_factory=list)
    # B6: per-site evidence rollup — devices, money, dates, and
    # stakeholders each site touches, aggregated across all docs.
    site_rollups: list[dict[str, Any]] = field(default_factory=list)
    # B3: consolidated PM action items from gaps + risks + phases.
    action_items: list[dict[str, Any]] = field(default_factory=list)
    # B4: role-lens one-pagers (CFO / IT / Procurement) — slicing
    # the intake into stakeholder-shaped summaries.
    stakeholder_pagers: list[dict[str, Any]] = field(default_factory=list)
    # B10: compliance / legal callouts — named-framework + generic-
    # legal language pulled from constraint / exclusion / decision
    # atoms so PM can route them to legal review.
    compliance_callouts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
