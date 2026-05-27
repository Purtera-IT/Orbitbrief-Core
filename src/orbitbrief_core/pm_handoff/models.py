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
    # Additive gap-fix fields (PMHandoff contract additive update):
    # ``pack_name`` mirrors ``label`` (or ``domain_id`` when the label
    # is missing) so the frontend can render a friendly pack name
    # without having to mirror the domain-label registry.
    # ``score`` is the per-pack confidence from the pack_prior router
    # (``pack_prior.top_scores[*].confidence``). ``None`` when the
    # router didn't surface a score for this domain id, so consumers
    # never confuse "unscored" with a real 0.0 score.
    pack_name: str | None = None
    score: float | None = None


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
    # B6 polish: explicit BOM-allocation cost lines (e.g. "ATL-HQ:
    # 52 Wi-Fi APs × $995 = $51,740") with per-site totals.
    site_allocations: list[dict[str, Any]] = field(default_factory=list)
    # B3: consolidated PM action items from gaps + risks + phases.
    action_items: list[dict[str, Any]] = field(default_factory=list)
    # B4: role-lens one-pagers (CFO / IT / Procurement) — slicing
    # the intake into stakeholder-shaped summaries.
    stakeholder_pagers: list[dict[str, Any]] = field(default_factory=list)
    # B10: compliance / legal callouts — named-framework + generic-
    # legal language pulled from constraint / exclusion / decision
    # atoms so PM can route them to legal review.
    compliance_callouts: list[dict[str, Any]] = field(default_factory=list)
    # B9: acceptance criteria checklist — schedule exit_criteria +
    # cutover checklist rows rendered as a copy-pasteable checkbox
    # list with owner / timing / evidence-required fields so the
    # field team has a deterministic execution checklist.
    acceptance_checks: list[dict[str, Any]] = field(default_factory=list)
    # B8: vendor RFP line items — auto-categorized vendor_line_item
    # atoms used by ``render_rfp_draft`` to generate RFP_DRAFT.md.
    rfp_line_items: list[dict[str, Any]] = field(default_factory=list)
    # PM-audit gap fillers:
    # Executive summary (3-line briefing for the top of PM_HANDOFF).
    executive_summary: dict[str, Any] = field(default_factory=dict)
    # Stakeholder contact directory (name / role / email / phone).
    stakeholder_contacts: list[dict[str, Any]] = field(default_factory=list)
    # Out-of-scope items surfaced at PM layer (in addition to SOW).
    exclusions: list[dict[str, Any]] = field(default_factory=list)
    # Customer- vs provider-supplied responsibilities split.
    responsibilities: list[dict[str, Any]] = field(default_factory=list)
    # Quantity claims + cross-doc quantity reconciliation flags.
    quantity_claims: list[dict[str, Any]] = field(default_factory=list)
    quantity_contradictions: list[dict[str, Any]] = field(default_factory=list)
    # Tier 1-4 PM intelligence
    margin_view: dict[str, Any] = field(default_factory=dict)
    critical_path: list[dict[str, Any]] = field(default_factory=list)
    lead_time_flags: list[dict[str, Any]] = field(default_factory=list)
    engagement_model: dict[str, Any] = field(default_factory=dict)
    license_items: list[dict[str, Any]] = field(default_factory=list)
    currency_mentions: list[dict[str, Any]] = field(default_factory=list)
    tax_clauses: list[dict[str, Any]] = field(default_factory=list)
    subcontractor_mentions: list[dict[str, Any]] = field(default_factory=list)
    sla_penalties: list[dict[str, Any]] = field(default_factory=list)
    resource_conflicts: list[dict[str, Any]] = field(default_factory=list)
    change_order_triggers: list[dict[str, Any]] = field(default_factory=list)
    risk_aging: list[dict[str, Any]] = field(default_factory=list)
    actions_by_week: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    acceptance_by_site: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    intake_completeness: list[dict[str, Any]] = field(default_factory=list)
    # Final universality wave
    currency_conversions: list[dict[str, Any]] = field(default_factory=list)
    eol_flags: list[dict[str, Any]] = field(default_factory=list)
    phase_dependencies: list[dict[str, Any]] = field(default_factory=list)
    critical_path_chain: list[str] = field(default_factory=list)
    comparable_deals: list[dict[str, Any]] = field(default_factory=list)
    ocr_backend_status: dict[str, Any] = field(default_factory=dict)
    crm_detections: list[dict[str, Any]] = field(default_factory=list)
    # UI-mapping additions
    sow_draft_markdown: str = ""        # Rendered SOW (so the UI can pull it from one payload)
    rfp_draft_markdown: str = ""        # Rendered RFP
    parser_quality_score: dict[str, Any] = field(default_factory=dict)  # {score, components}
    # A+ wave: run telemetry + drift + urgency + customer-answer scaffold
    run_telemetry: dict[str, Any] = field(default_factory=dict)
    drift_snapshot: dict[str, Any] = field(default_factory=dict)
    urgency_signals: list[dict[str, Any]] = field(default_factory=list)
    customer_answer_slots: list[dict[str, Any]] = field(default_factory=list)
    # PMHandoff contract gap-fix additive fields:
    # ``calibrator_verdict`` projects the Verdict enum's string value
    # (``"auto_accept"`` / ``"needs_review"`` / ``"reject"``) so PM
    # consumers can see whether the calibrated brain output is
    # auto-acceptable. ``None`` means the calibrator either wasn't
    # invoked in the build path or no calibration artifact was on
    # disk. Wired by ``builder.py`` from
    # ``<case>/60_calibrations/*.json`` when present.
    calibrator_verdict: str | None = None
    # ``polish_stage`` exposes the polish telemetry block (phase,
    # model, polished_count, fallback_count, validator_enforced). A
    # ``None`` here means polish never ran on this build; an emitted
    # dict with ``model="none"`` means polish ran as a no-op because
    # no LLM client was supplied. Populated by ``polish_pm_handoff``
    # via a ``replace(handoff, polish_stage=...)`` step.
    polish_stage: dict[str, Any] | None = None

    # ── v46 envelope-enrichment fields (Track A passthroughs) ────────
    # parser-os emits a much richer envelope than the historical
    # builder consumes.  These eight fields are direct passthroughs of
    # the curated views parser already computes — no new LLM calls,
    # no derivation in orbitbrief, just plumbing.
    project_vitals: dict[str, Any] = field(default_factory=dict)
    sow_readiness_dimensions: dict[str, Any] = field(default_factory=dict)
    contested_scope_items: list[dict[str, Any]] = field(default_factory=list)
    site_readiness: list[dict[str, Any]] = field(default_factory=list)
    milestones: list[dict[str, Any]] = field(default_factory=list)
    stakeholder_load: list[dict[str, Any]] = field(default_factory=list)
    evidence_authority: dict[str, Any] = field(default_factory=dict)
    change_order_timeline: list[dict[str, Any]] = field(default_factory=list)

    # ── v46 Track B: graph-based risk signals ───────────────────────
    # ``risk_signals`` carries per-axis ranked risk lists computed from
    # the envelope graph (authority_rank, edge density, contradiction
    # density, missing-source-replay).  Computed without any trained
    # model — purely a set of calibrated heuristics over graph features
    # the parser already extracts.  See risk_net/scorers.py.
    risk_signals: dict[str, Any] = field(default_factory=dict)

    # ── v46 Track C: Cross-Authority Consensus Net (CACN) ───────────
    # ``claim_consensus`` annotates every PM-visible claim (gap, risk,
    # money_mention, date_mention, quantity_claim, customer_question)
    # with: authority_diversity (count of distinct authority classes
    # supporting it), consensus_strength (rank-weighted), contradiction
    # flag (graph-walked), confidence_ribbon (0-1).  PM can filter or
    # sort by these.  See risk_net/consensus.py.
    claim_consensus: dict[str, Any] = field(default_factory=dict)

    # ── v46 Track D: per-section PM-voice narration ─────────────────
    # ``section_narration`` is one PM-voice sentence per v46 section,
    # generated by one batched LLM call after Track A/B/C run.  UI
    # renders it above the section content as a lead paragraph so PMs
    # immediately know what the numbers mean and what to do.  See
    # risk_net/narrator.py.
    section_narration: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
