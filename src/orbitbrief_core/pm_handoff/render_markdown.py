from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from orbitbrief_core.pm_handoff.business_labels import CATEGORY_ORDER, FACT_CATEGORY_LABELS, SEVERITY_SORT, severity_label
from orbitbrief_core.pm_handoff.models import GapCard, PMHandoff

_STATUS_ICON = {"green": "🟢", "yellow": "🟡", "red": "🔴"}


def render_pm_handoff_markdown(handoff: PMHandoff) -> str:
    icon = _STATUS_ICON.get(handoff.status, "⚪")
    lines: list[str] = [
        f"# OrbitBrief PM / Solution Architect Handoff — {handoff.case_id}",
        "",
        f"**Status:** {icon} **{handoff.status_label}**",
        "",
        f"> {handoff.one_line_summary}",
        "",
    ]
    # Executive summary at the very top — 3-line PM briefing.
    lines.extend(_render_executive_summary(handoff))
    lines.extend(_render_intake_completeness(handoff))
    lines.append("This report translates the intake package into evidence, SOW gaps, customer questions, and SA review work.")
    lines.append("")
    lines.extend(_render_scorecard(handoff))
    lines.extend(_render_margin_view(handoff))
    lines.extend(_render_engagement_model(handoff))
    lines.extend(_render_domains(handoff))
    lines.extend(_render_sites(handoff))
    lines.extend(_render_stakeholder_contacts(handoff))
    lines.extend(_render_site_rollups(handoff))
    lines.extend(_render_site_allocations(handoff))
    lines.extend(_render_risk_register(handoff))
    lines.extend(_render_risk_aging(handoff))
    lines.extend(_render_schedule(handoff))
    lines.extend(_render_critical_path(handoff))
    lines.extend(_render_resource_conflicts(handoff))
    lines.extend(_render_lead_time_flags(handoff))
    lines.extend(_render_license_items(handoff))
    lines.extend(_render_subcontractors(handoff))
    lines.extend(_render_sla_penalties(handoff))
    lines.extend(_render_change_order_triggers(handoff))
    lines.extend(_render_currencies_taxes(handoff))
    lines.extend(_render_action_items(handoff))
    lines.extend(_render_actions_by_week(handoff))
    lines.extend(_render_acceptance_checklist(handoff))
    lines.extend(_render_acceptance_by_site(handoff))
    lines.extend(_render_compliance_callouts(handoff))
    lines.extend(_render_exclusions(handoff))
    lines.extend(_render_responsibilities(handoff))
    lines.extend(_render_reconciliation(handoff))
    lines.extend(_render_quantity_reconciliation(handoff))
    lines.extend(_render_questions(handoff))
    lines.extend(_render_known_facts(handoff))
    lines.extend(_render_solution_architect_view(handoff))
    lines.extend(_render_source_inventory(handoff))
    lines.extend(_render_customer_email(handoff))
    lines.extend(_render_stakeholder_pagers(handoff))
    return "\n".join(lines).rstrip() + "\n"


def _render_executive_summary(handoff: PMHandoff) -> list[str]:
    """Top-of-doc 3-line executive briefing."""
    es = handoff.executive_summary or {}
    if not es:
        return []
    lines = ["## Executive summary", ""]
    if es.get("headline"):
        lines.append(es["headline"])
        lines.append("")
    if es.get("health_line"):
        lines.append(es["health_line"])
        lines.append("")
    if es.get("next_action"):
        lines.append(f"**Next action:** {es['next_action']}")
        lines.append("")
    return lines


def _render_stakeholder_contacts(handoff: PMHandoff) -> list[str]:
    """Stakeholder contact directory — name, role, email, phone."""
    contacts = handoff.stakeholder_contacts or []
    if not contacts:
        return []
    lines = [
        "## Stakeholder contact directory",
        "",
        "| Name | Role | Email | Phone | Source |",
        "|---|---|---|---|---|",
    ]
    for c in contacts:
        lines.append(
            f"| {c.get('name','')} | {c.get('role','') or '—'} | "
            f"{c.get('email','') or '—'} | {c.get('phone','') or '—'} | "
            f"`{c.get('source','')}` |"
        )
    lines.append("")
    return lines


def _render_exclusions(handoff: PMHandoff) -> list[str]:
    """Top-level out-of-scope section so the PM doesn't have to dig
    through SOW_DRAFT to see what's excluded."""
    items = handoff.exclusions or []
    if not items:
        return []
    lines = [
        "## Out of scope (explicit exclusions)",
        "",
        "These items are explicitly **out of scope** per the intake package. PM should confirm the customer agrees before sending the SOW.",
        "",
    ]
    for e in items:
        lines.append(f"- {e.get('text','')} _(source: `{e.get('source','')}`)_")
    lines.append("")
    return lines


def _render_responsibilities(handoff: PMHandoff) -> list[str]:
    """Customer-supplied vs provider-supplied responsibility split."""
    items = handoff.responsibilities or []
    if not items:
        return []
    customer_items = [r for r in items if r.get("party") == "customer"]
    provider_items = [r for r in items if r.get("party") == "provider"]
    if not (customer_items or provider_items):
        return []
    lines = ["## Responsibilities (customer vs provider)", ""]
    if customer_items:
        lines.append("### Customer-supplied / customer-responsible")
        lines.append("")
        for r in customer_items:
            lines.append(f"- {r.get('text','')} _(source: `{r.get('source','')}`)_")
        lines.append("")
    if provider_items:
        lines.append("### Provider-supplied / provider-responsible")
        lines.append("")
        for r in provider_items:
            lines.append(f"- {r.get('text','')} _(source: `{r.get('source','')}`)_")
        lines.append("")
    return lines


def _render_quantity_reconciliation(handoff: PMHandoff) -> list[str]:
    """Cross-doc quantity contradictions (parallel to money A5)."""
    contradictions = handoff.quantity_contradictions or []
    if not contradictions:
        return []
    lines = [
        "## Cross-document quantity reconciliation",
        "",
        "Counts of the same device / part that differ across documents. PM must confirm the authoritative count before SOW lock.",
        "",
    ]
    for c in contradictions:
        target = c.get("target", "")
        vals = ", ".join(str(v) for v in c.get("values", []))
        files = ", ".join(f"`{f}`" for f in c.get("files", []))
        lines.append(f"- **{target}** — counts: {vals} (across: {files})")
        for ex in c.get("examples", [])[:3]:
            lines.append(f"  - {ex.get('qty')} from `{ex.get('source','')}`: {ex.get('snippet','')}")
    lines.append("")
    return lines


def render_portfolio_markdown(handoffs: Iterable[PMHandoff]) -> str:
    handoffs = list(handoffs)
    red = sum(1 for h in handoffs if h.status == "red")
    yellow = sum(1 for h in handoffs if h.status == "yellow")
    green = sum(1 for h in handoffs if h.status == "green")
    # C5 polish: roll up money + risk + schedule signal across the
    # portfolio so the PM sees the cross-deal picture in one shot.
    total_money_at_stake = 0
    for h in handoffs:
        money = (h.money_mentions or [])
        if money:
            # Largest single money value per case approximates "deal size"
            total_money_at_stake += max(int(m.get("value", 0)) for m in money)
    total_risks = sum(len(h.risk_register or []) for h in handoffs)
    total_high_risks = sum(
        1
        for h in handoffs
        for r in (h.risk_register or [])
        if (r.get("likelihood","").lower(), r.get("impact","").lower()) in {
            ("high", "high"), ("high", "medium"), ("medium", "high"),
        }
    )
    total_compliance_callouts = sum(len(h.compliance_callouts or []) for h in handoffs)

    lines = [
        "# OrbitBrief PM Portfolio Dashboard",
        "",
        f"**Cases:** {len(handoffs)}  ·  🔴 {red} red  ·  🟡 {yellow} yellow  ·  🟢 {green} green",
        "",
        "## Portfolio totals",
        "",
        f"- **Aggregate deal value across cases (largest money value per case):** ${total_money_at_stake:,}",
        f"- **Total risks tracked:** {total_risks} ({total_high_risks} high-priority)",
        f"- **Total compliance callouts requiring legal review:** {total_compliance_callouts}",
        "",
        "## Case index",
        "",
        "| Case | Status | Sites | Workstreams | Blockers | Warnings | Evidence | Deal value | High risks |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|",
    ]
    for h in handoffs:
        domains = ", ".join(d.label for d in h.domains if d.selected_by_router or d.active_for_sow)
        case_money = max(
            (int(m.get("value", 0)) for m in (h.money_mentions or [])),
            default=0,
        )
        case_high_risks = sum(
            1
            for r in (h.risk_register or [])
            if (r.get("likelihood","").lower(), r.get("impact","").lower()) in {
                ("high", "high"), ("high", "medium"), ("medium", "high"),
            }
        )
        lines.append(
            f"| `{h.case_id}` | {_STATUS_ICON.get(h.status, '⚪')} {h.status_label} | "
            f"{h.metrics.get('sites_published', 0)} | {domains[:120]} | "
            f"{h.metrics.get('blockers', 0)} | {h.metrics.get('warnings', 0)} | "
            f"{h.metrics.get('evidence_items_extracted', 0)} | "
            f"{'$' + format(case_money, ',') if case_money else '—'} | {case_high_risks} |"
        )
    lines.extend(["", "## PM follow-up queue", ""])
    for h in handoffs:
        blockers = [g for g in h.gaps if g.severity == "blocker"]
        if not blockers:
            continue
        lines.extend([f"### {h.case_id}", ""])
        for g in blockers[:10]:
            lines.append(f"- **{g.domain_label}: {g.label}** — {g.suggested_open_question or g.message}")
        lines.append("")
    # C5 polish: cross-deal reconciliation pull-up — show every
    # reconciliation flag the portfolio carries so the PM can spot
    # systematic money mismatches across multiple deals.
    any_flags = any(h.reconciliation_flags for h in handoffs)
    if any_flags:
        lines.extend(["## Cross-deal money reconciliation queue", ""])
        for h in handoffs:
            if not h.reconciliation_flags:
                continue
            lines.append(f"**{h.case_id}**")
            for f in h.reconciliation_flags:
                lines.append(f"- {f.get('label','')}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_scorecard(handoff: PMHandoff) -> list[str]:
    m = handoff.metrics
    return [
        "## PM scorecard",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Source files read | {m.get('source_files', 0)} |",
        f"| Evidence items extracted | {m.get('evidence_items_extracted', 0)} |",
        f"| PM-visible evidence cards | {m.get('pm_visible_fact_cards', 0)} |",
        f"| Confirmed physical sites | {m.get('sites_published', 0)} |",
        f"| SOW blocker questions | {m.get('blockers', 0)} |",
        f"| SOW warning questions | {m.get('warnings', 0)} |",
        f"| Top workstream | {m.get('top_workstream') or 'unknown'} |",
        "",
    ]


def _render_domains(handoff: PMHandoff) -> list[str]:
    lines = ["## Detected workstreams", "", "| Workstream | Routed? | SOW checks active? | Blockers | Warnings |", "|---|:-:|:-:|---:|---:|"]
    for d in handoff.domains:
        lines.append(f"| {d.label} | {'✓' if d.selected_by_router else ''} | {'✓' if d.active_for_sow else ''} | {d.blockers} | {d.warnings} |")
    lines.append("")
    return lines


def _render_sites(handoff: PMHandoff) -> list[str]:
    lines = ["## Confirmed sites", ""]
    if not handoff.sites:
        return lines + ["No confirmed physical site was found. This is a PM blocker.", ""]
    lines.extend(["| Site | Kind | Confirmed | Evidence items | Source files |", "|---|---|:-:|---:|---:|"])
    for s in handoff.sites:
        lines.append(f"| {s.name} | {s.kind} | {'✓' if s.publishable else ''} | {s.member_evidence_count} | {s.artifact_count} |")
    lines.append("")
    return lines


def _render_questions(handoff: PMHandoff) -> list[str]:
    lines = ["## Questions to resolve before SOW", ""]
    if not handoff.gaps:
        return lines + ["No missing SOW items were found by the current rulebook.", ""]
    by_sev: dict[str, list[GapCard]] = defaultdict(list)
    for g in handoff.gaps:
        by_sev[g.severity].append(g)
    for sev in ["blocker", "warning", "info"]:
        items = by_sev.get(sev) or []
        if not items:
            continue
        lines.extend([f"### {severity_label(sev)}", ""])
        for g in items:
            lines.append(f"- **{g.domain_label} — {g.label}:** {g.suggested_open_question or g.message}")
        lines.append("")
    return lines


def _render_known_facts(handoff: PMHandoff) -> list[str]:
    lines = ["## What OrbitBrief found in the intake package", ""]
    for category in CATEGORY_ORDER:
        cards = handoff.facts_by_category.get(category) or []
        if not cards:
            continue
        lines.extend([f"### {FACT_CATEGORY_LABELS.get(category, category.title())}", ""])
        for c in cards:
            lines.append(f"- **{c.title}:** {c.text}  ")
            lines.append(f"  _Source: {c.source.display()}_")
        lines.append("")
    return lines


def _render_solution_architect_view(handoff: PMHandoff) -> list[str]:
    lines = ["## Solution architect review lane", ""]
    if handoff.sa_focus:
        lines.append("Technical checks the SA should validate before design/SOW sign-off:")
        lines.append("")
        for item in handoff.sa_focus:
            lines.append(f"- {item}")
        lines.append("")
    technical = [g for g in handoff.gaps if g.domain_id in {"low_voltage_cabling", "wireless", "network_maintenance", "security_camera", "audio_visual", "electrical", "datacenter", "rack_and_stack"}]
    if technical:
        lines.extend(["### SA-owned open items", ""])
        for g in technical[:20]:
            lines.append(f"- **{g.label}:** {g.suggested_open_question or g.message}")
        lines.append("")
    return lines


def _render_acceptance_checklist(handoff: PMHandoff) -> list[str]:
    """B9: copy-pasteable acceptance criteria checklist.

    Grouped by phase / step. Each row is a markdown checkbox with
    owner, evidence-required, and timing metadata so the field
    team can execute the block directly.
    """
    checks = handoff.acceptance_checks or []
    if not checks:
        return []
    lines: list[str] = [
        "## Acceptance criteria checklist",
        "",
        "Copy-paste into the field team's execution doc. One checkbox per criterion; ticking implies the named owner has verified completion and attached the listed evidence.",
        "",
    ]
    from collections import OrderedDict
    by_phase: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for c in checks:
        by_phase.setdefault(c.get("phase_or_step", "Misc"), []).append(c)
    for phase, items in by_phase.items():
        lines.append(f"### {phase}")
        lines.append("")
        for c in items:
            owner = c.get("owner") or "—"
            evidence = c.get("evidence_required") or ""
            timing = c.get("timing") or ""
            suffix_bits: list[str] = []
            if timing:
                suffix_bits.append(f"timing: {timing}")
            suffix_bits.append(f"owner: {owner}")
            if evidence:
                suffix_bits.append(f"evidence: {evidence}")
            suffix = " · ".join(suffix_bits)
            lines.append(f"- [ ] {c.get('criterion','')} _({suffix})_")
        lines.append("")
    return lines


def _render_compliance_callouts(handoff: PMHandoff) -> list[str]:
    """B10: compliance / legal callouts for legal review.

    Lists every atom that mentions a named compliance framework
    (SOC 2, HIPAA, ISO 27001, GDPR, etc.) or generic legal
    language (indemnification, warranty, audit rights, MSA, ...).
    PM forwards this block to legal review as a starting point —
    every line is a copy-pasteable quote from the source.
    """
    callouts = handoff.compliance_callouts or []
    if not callouts:
        return []
    lines: list[str] = [
        "## Compliance & legal callouts",
        "",
        "Atoms that mention named compliance frameworks or generic legal language. **Route these to legal review** before SOW signature.",
        "",
        "| Framework / clause | Source | Snippet |",
        "|---|---|---|",
    ]
    for c in callouts:
        snippet = (c.get("snippet") or "").replace("|", "\\|")
        lines.append(
            f"| **{c.get('framework','')}** | `{c.get('source','')}` | {snippet} |"
        )
    lines.append("")
    return lines


def _render_action_items(handoff: PMHandoff) -> list[str]:
    """B3: PM action checklist consolidated from gaps + risks + phases.

    Grouped by ``kind`` (gap / risk / phase) with a checkbox-style
    markdown list so the PM can copy/paste the block into their
    PM tool. ``owner`` defaults to "PM" when unassigned.
    """
    items = handoff.action_items or []
    if not items:
        return []
    lines: list[str] = ["## PM action checklist", ""]
    # Render by kind, in the same order action_items is built.
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        by_kind.setdefault(it.get("kind", ""), []).append(it)
    section_titles = {
        "gap": "From SOW gap analysis",
        "risk": "From risk register",
        "phase": "From schedule",
    }
    for kind in ("gap", "risk", "phase"):
        bucket = by_kind.get(kind) or []
        if not bucket:
            continue
        lines.append(f"### {section_titles.get(kind, kind)}")
        lines.append("")
        for it in bucket:
            owner = it.get("owner") or "PM"
            due = it.get("due")
            due_str = f" — due {due}" if due else ""
            sev = it.get("severity")
            sev_str = f" **[{sev}]**" if sev in {"blocker", "warning"} else ""
            lines.append(f"- [ ]{sev_str} {it.get('label','')} (owner: {owner}{due_str})")
        lines.append("")
    return lines


def _render_site_allocations(handoff: PMHandoff) -> list[str]:
    """B6 polish: per-site $ arithmetic from BOM allocations.

    Groups each parsed allocation line by site so the PM sees one
    row per (site, device) plus a per-site grand total. Pure
    arithmetic — values are quantity × unit_price as parsed from
    the source text, with no LLM rounding.
    """
    rows = handoff.site_allocations or []
    if not rows:
        return []
    from collections import defaultdict as _defaultdict
    by_site: dict[str, list[dict[str, Any]]] = _defaultdict(list)
    for r in rows:
        by_site[r.get("site", "?")].append(r)

    lines: list[str] = [
        "## Per-site BOM allocation (computed)",
        "",
        "Computed by multiplying quantity × unit_price for every explicit allocation line in the BOM. Use this to verify the per-site rollup matches the SOW commercial section.",
        "",
    ]
    grand_total = 0
    for site in sorted(by_site):
        site_rows = by_site[site]
        site_total = sum(int(r.get("extended", 0)) for r in site_rows)
        grand_total += site_total
        lines.append(f"### {site} — ${site_total:,}")
        lines.append("")
        lines.append("| Device | Qty | Unit price | Extended | Source |")
        lines.append("|---|---:|---:|---:|---|")
        for r in sorted(site_rows, key=lambda x: -int(x.get("extended", 0))):
            lines.append(
                f"| {r.get('device','')} | {r.get('quantity', 0)} | "
                f"${int(r.get('unit_price', 0)):,} | ${int(r.get('extended', 0)):,} | "
                f"`{r.get('source','')}` |"
            )
        lines.append("")
    lines.append(f"**Allocated total across sites: ${grand_total:,}**")
    lines.append("")
    return lines


def _render_site_rollups(handoff: PMHandoff) -> list[str]:
    """B6: per-site evidence rollup.

    For each site, lists distinct devices, money values, dates, and
    stakeholders mentioned alongside that site across every
    document. PM can scan the table to confirm coverage parity
    across sites and spot orphans (e.g. a site that's mentioned
    once with no money / device evidence at all).
    """
    rolls = handoff.site_rollups or []
    if not rolls:
        return []
    lines: list[str] = [
        "## Per-site evidence rollup",
        "",
        "Aggregated by site across every document. The PM should sanity-check that each site has the device, money, date, and stakeholder coverage the SOW will need.",
        "",
        "| Site | Atoms | Devices | Money | Dates | Stakeholders |",
        "|---|---:|---|---|---|---|",
    ]
    for r in rolls:
        def _cap(seq: list[str], limit: int = 6) -> str:
            seq = list(seq or [])
            if len(seq) <= limit:
                return ", ".join(seq)
            extra = len(seq) - limit
            return ", ".join(seq[:limit]) + f" _(+{extra})_"

        lines.append(
            f"| **{r.get('site_name','')}** | {r.get('atom_count', 0)} | "
            f"{_cap(r.get('devices'))} | {_cap(r.get('money_values'))} | "
            f"{_cap(r.get('dates'))} | {_cap(r.get('stakeholders'))} |"
        )
    lines.append("")
    return lines


def _render_risk_register(handoff: PMHandoff) -> list[str]:
    """B2: PM-ready risk register table.

    One row per ``atom_type=risk`` atom. Sorted by Likelihood ×
    Impact descending so the highest-priority risks are first.

    C3: every row now ends with the source filename so the PM /
    SA can click through to the underlying spreadsheet row.
    """
    rows = handoff.risk_register or []
    if not rows:
        return []
    lines: list[str] = [
        "## Risk register",
        "",
        "| ID | Risk | Likelihood | Impact | Mitigation | Owner | Sites | Source |",
        "|---|---|:-:|:-:|---|---|---|---|",
    ]
    for r in rows:
        sites = ", ".join(r.get("sites") or []) or "—"
        desc = (r.get("description") or "").replace("|", "\\|")
        miti = (r.get("mitigation") or "").replace("|", "\\|")
        source = r.get("source") or "—"
        lines.append(
            f"| {r.get('risk_id','')} | {desc} | {r.get('likelihood','')} | "
            f"{r.get('impact','')} | {miti} | {r.get('owner','')} | {sites} | "
            f"`{source}` |"
        )
    lines.append("")
    return lines


def _render_schedule(handoff: PMHandoff) -> list[str]:
    """B5: Project schedule — Mermaid Gantt + fallback table.

    Emits a mermaid block when at least one phase has a real start
    date (so the chart renders cleanly), plus a markdown table
    that's readable on platforms without mermaid support.
    """
    phases = handoff.schedule_phases or []
    if not phases:
        return []
    lines: list[str] = ["## Project schedule", ""]
    datable = [p for p in phases if p.get("start") and p.get("end")]
    if datable:
        lines.extend(["```mermaid", "gantt", "    dateFormat  YYYY-MM-DD", "    title Project Schedule", ""])
        # Group by source file as Gantt sections so phases from
        # different docs don't collide visually.
        by_src: dict[str, list[dict[str, Any]]] = {}
        for p in datable:
            by_src.setdefault(p.get("source", ""), []).append(p)
        for src, items in by_src.items():
            if src:
                lines.append(f"    section {src}")
            for p in items:
                safe = (p.get("phase", "")).replace(":", " -").replace("\n", " ")[:60] or "phase"
                lines.append(f"    {safe} :{p['start']}, {p['end']}")
        lines.extend(["```", ""])
    lines.extend([
        "| Phase | Start | End | Owner | Source |",
        "|---|---|---|---|---|",
    ])
    for p in phases:
        lines.append(
            f"| {p.get('phase','')} | {p.get('start','—')} | {p.get('end','—')} | "
            f"{p.get('owner','')} | `{p.get('source','')}` |"
        )
    lines.append("")
    return lines


def _render_reconciliation(handoff: PMHandoff) -> list[str]:
    """A5: Cross-doc money + date reconciliation tables.

    Two tables and an optional flagged-pairs block. The intent is
    PM-actionable at a glance — "do the docs agree on the contract
    value and the dates?" — without an LLM in the loop.

    Suppressed entirely when both tables are empty so a single-doc
    intake doesn't render a useless header.
    """
    money = handoff.money_mentions or []
    dates = handoff.date_mentions or []
    flags = handoff.reconciliation_flags or []
    if not money and not dates:
        return []

    lines: list[str] = ["## Cross-document reconciliation", ""]

    if flags:
        lines.extend([
            "### Values that may need PM reconciliation",
            "",
            "Pairs of money values close enough to plausibly refer to the same line item but not equal. The PM should confirm which one is authoritative before SOW lock.",
            "",
        ])
        for f in flags:
            lines.append(f"- **{f.get('label', '')}**")
            for v in f.get("values", []):
                src_files = sorted({s.get("filename", "") for s in v.get("sources", [])})
                files_str = ", ".join(f"`{x}`" for x in src_files if x)
                lines.append(f"  - {v.get('display','')} — seen in {files_str}")
        lines.append("")

    if money:
        # Cap at 25 distinct values so the worst-case (a BOM with
        # 100 line-item prices) doesn't overwhelm the doc; 25 is
        # enough to show every "total / subtotal / contingency"
        # together with the largest line items.
        lines.extend([
            "### Money mentioned across documents",
            "",
            "| Value | Files | Sample text |",
            "|---:|---|---|",
        ])
        for m in money[:25]:
            sources = m.get("sources") or []
            files = sorted({s.get("filename", "") for s in sources})
            files_str = "<br>".join(f"`{x}`" for x in files if x)
            sample = (sources[0].get("snippet", "") if sources else "").replace("|", "\\|")
            lines.append(f"| {m.get('display','')} | {files_str} | {sample} |")
        if len(money) > 25:
            lines.append(f"| _… {len(money) - 25} more money values not shown_ | | |")
        lines.append("")

    if dates:
        # Surface only cross-doc dates here — single-doc dates
        # rarely tell the PM anything new at this layer.
        cross_doc_dates = [d for d in dates if len({s.get("filename", "") for s in (d.get("sources") or [])}) >= 2]
        if cross_doc_dates:
            lines.extend([
                "### Dates mentioned in multiple documents",
                "",
                "| Date | Files |",
                "|---|---|",
            ])
            for d in cross_doc_dates[:25]:
                files = sorted({s.get("filename", "") for s in (d.get("sources") or [])})
                files_str = ", ".join(f"`{x}`" for x in files if x)
                lines.append(f"| {d.get('iso','')} | {files_str} |")
            if len(cross_doc_dates) > 25:
                lines.append(f"| _… {len(cross_doc_dates) - 25} more cross-doc dates not shown_ | |")
            lines.append("")
    return lines


def _render_source_inventory(handoff: PMHandoff) -> list[str]:
    # A6 graceful degradation: include a per-file status column and a
    # callout box for any file that wasn't cleanly parsed. The PM sees
    # immediately which files succeeded vs which need manual review.
    _STATUS_GLYPH = {
        "ok": "✅",
        "ok_empty": "⚠️ (no atoms)",
        "failed_parse": "❌ failed",
        "skipped_no_parser": "⏭️ skipped",
        "unknown": "❓",
    }
    lines = [
        "## Source inventory read",
        "",
        "| File | Type | Parser | Evidence items | Status |",
        "|---|---|---|---:|:--|",
    ]
    for s in handoff.source_files:
        glyph = _STATUS_GLYPH.get(s.status, s.status)
        lines.append(
            f"| `{s.filename}` | {s.artifact_type} | {s.parser_name} | "
            f"{s.evidence_items} | {glyph} |"
        )
    lines.append("")
    # Degraded-files callout — only render when there's something to flag.
    degraded = [s for s in handoff.source_files if s.status not in {"ok", "unknown"}]
    if degraded:
        lines.extend([
            "### ⚠ Files requiring manual review",
            "",
            "These files did not produce clean evidence. Verify the source manually:",
            "",
        ])
        for s in degraded:
            line = f"- **`{s.filename}`** — {s.status}"
            if s.status_reason:
                line += f": {s.status_reason}"
            lines.append(line)
        lines.append("")
    return lines


_INTERNAL_QUESTION_TOKENS = (
    "verify",
    "synthesis rendering",
    "model is broken",
    "promotion path",
    "site reality v",
    "parser-os",
    "orbitbrief",
    "publish as a physical-site cluster",
    "kind=physical_site",
)


def _is_customer_facing(text: str) -> bool:
    """Filter PM-internal questions (parser-os correctness checks)
    from the customer-facing email starter. PM still sees them in
    the "Questions to resolve before SOW" section above."""
    if not text:
        return False
    low = text.lower()
    return not any(tok in low for tok in _INTERNAL_QUESTION_TOKENS)


def _render_customer_email(handoff: PMHandoff) -> list[str]:
    # B7 — filter out parser-os internal correctness questions so
    # the email starter is safe to copy/paste to the customer
    # without redacting first. The PM still has the full question
    # list in the "Questions to resolve before SOW" section.
    customer_safe = [
        g for g in handoff.customer_questions
        if _is_customer_facing(g.suggested_open_question or g.message)
    ][:18]
    lines = ["## Customer clarification email starter", ""]
    if not customer_safe:
        return lines + ["No customer-facing clarifications are required from the current rulebook output.", ""]
    # Group by severity so the customer reads blockers before nice-to-haves.
    blockers = [g for g in customer_safe if g.severity == "blocker"]
    warnings = [g for g in customer_safe if g.severity == "warning"]
    lines.extend([
        "```text",
        "Subject: Clarifications needed before SOW draft",
        "",
        "Hi team,",
        "",
        "We reviewed the intake package and need the following clarifications before we can finalize the SOW:",
        "",
    ])
    counter = 1
    if blockers:
        lines.append("MUST-ANSWER before we can draft scope:")
        for g in blockers:
            lines.append(f"  {counter}. {g.suggested_open_question or g.message}")
            counter += 1
        lines.append("")
    if warnings:
        lines.append("CONFIRMATIONS that will shape commercial terms and assumptions:")
        for g in warnings:
            lines.append(f"  {counter}. {g.suggested_open_question or g.message}")
            counter += 1
        lines.append("")
    lines.extend([
        "Once we have these answers, we can finalize the scope, assumptions, exclusions, acceptance criteria, and commercial terms.",
        "",
        "Thanks,",
        "Project team",
        "```",
        "",
    ])
    return lines


def _render_stakeholder_pagers(handoff: PMHandoff) -> list[str]:
    """B4: Stakeholder one-pagers — CFO / IT / Procurement lenses.

    Each pager is a self-contained section the PM can copy out to
    forward to that specific stakeholder. The section heading is
    the role title; sub-sections cover headline money, risks, and
    action items the lens picked.
    """
    pagers = handoff.stakeholder_pagers or []
    if not pagers:
        return []
    lines: list[str] = [
        "---",
        "",
        "# Stakeholder one-pagers",
        "",
        "Each section below is a self-contained briefing for one stakeholder lens. Forward as-is.",
        "",
    ]
    for p in pagers:
        lines.append(f"## {p.get('title','')}")
        lines.append("")
        for s in p.get("summary_lines", []) or []:
            lines.append(s)
        if p.get("summary_lines"):
            lines.append("")
        if p.get("money_lines"):
            lines.append("**Money items:**")
            lines.append("")
            lines.extend(p["money_lines"])
            lines.append("")
        if p.get("risk_lines"):
            lines.append("**Risks for this lens:**")
            lines.append("")
            lines.extend(p["risk_lines"])
            lines.append("")
        if p.get("action_lines"):
            lines.append("**Open items for this lens:**")
            lines.append("")
            lines.extend(p["action_lines"])
            lines.append("")
    return lines


def _render_intake_completeness(handoff: PMHandoff) -> list[str]:
    items = handoff.intake_completeness or []
    if not items:
        return []
    total = len(items)
    present = sum(1 for i in items if i.get("present"))
    pct = (present / total * 100) if total else 0
    bar_len = 20
    filled = int(pct / 100 * bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)
    lines = [
        "## Intake completeness",
        "",
        f"**Coverage: {present}/{total} ({pct:.0f}%)**  `{bar}`",
        "",
    ]
    for i in items:
        mark = "✅" if i.get("present") else "❌"
        lines.append(f"- {mark} {i.get('item','')}")
    lines.append("")
    return lines


def _render_margin_view(handoff: PMHandoff) -> list[str]:
    m = handoff.margin_view or {}
    if not (m.get("deal_total") or m.get("hardware_cost_subtotal")):
        return []
    lines = ["## Margin & profitability", ""]
    if m.get("confidence") == "low":
        lines.append("> _Computed from partial signals — treat as indicative, not contractual._")
        lines.append("")
    lines.append("| Line | Value |")
    lines.append("|---|---:|")
    if m.get("deal_total"):
        lines.append(f"| Deal total (largest money ≥ $100k) | ${int(m['deal_total']):,} |")
    if m.get("hardware_cost_subtotal"):
        lines.append(f"| Hardware cost (BOM qty × unit) | ${int(m['hardware_cost_subtotal']):,} |")
    if m.get("services_subtotal"):
        lines.append(f"| Services subtotal (text-matched) | ${int(m['services_subtotal']):,} |")
    if m.get("other_cost_subtotal"):
        lines.append(f"| Logistics / freight / contingency / tax | ${int(m['other_cost_subtotal']):,} |")
    if m.get("total_cost"):
        lines.append(f"| **Total cost** | **${int(m['total_cost']):,}** |")
    if m.get("gross_profit"):
        lines.append(f"| Gross profit | ${int(m['gross_profit']):,} |")
    if m.get("margin_pct"):
        lines.append(f"| **Margin %** | **{m['margin_pct']:.1f}%** |")
    lines.append(f"| Confidence | {m.get('confidence','low')} |")
    lines.append("")
    for n in m.get("notes") or []:
        lines.append(f"- {n}")
    if m.get("notes"):
        lines.append("")
    return lines


def _render_engagement_model(handoff: PMHandoff) -> list[str]:
    em = handoff.engagement_model or {}
    model = em.get("detected_model") or "unknown"
    if model == "unknown" and not em.get("has_tm_cap"):
        return []
    pretty = {
        "fixed_fee": "Fixed Fee", "tm": "T&M", "subscription": "Subscription",
        "mixed": "Mixed (multiple models detected)", "unknown": "Unknown",
    }
    lines = [
        "## Engagement model", "",
        f"**Detected model:** {pretty.get(model, model)}",
        "",
    ]
    if em.get("has_tm_cap"):
        lines.append(f"- T&M / NTE cap: ${int(em['tm_cap_amount']):,}")
    for e in em.get("evidence") or []:
        lines.append(f"- {e}")
    lines.append("")
    return lines


def _render_critical_path(handoff: PMHandoff) -> list[str]:
    cp = handoff.critical_path or []
    if not cp:
        return []
    lines = [
        "## Critical path",
        "",
        "Phases marked **critical** have zero slack to the project end. A slip here pushes everything downstream. Non-critical phases have a buffer.",
        "",
        "| Phase | Start | End | Duration (days) | Critical? |",
        "|---|---|---|---:|:-:|",
    ]
    for p in cp:
        mark = "🔴 yes" if p.get("is_critical") else ""
        lines.append(
            f"| {p.get('phase','')} | {p.get('start','')} | {p.get('end','')} | "
            f"{p.get('duration_days', 0)} | {mark} |"
        )
    lines.append("")
    return lines


def _render_resource_conflicts(handoff: PMHandoff) -> list[str]:
    confs = handoff.resource_conflicts or []
    if not confs:
        return []
    lines = [
        "## Resource conflicts",
        "",
        "Owners assigned to phases whose date ranges overlap. PM must rebalance or confirm coverage.",
        "",
    ]
    for c in confs:
        phases = ", ".join(c.get("phases", []))
        windows = ", ".join(f"{s}→{e}" for s, e in c.get("overlap_windows", []))
        lines.append(f"- **{c.get('owner','?')}** — overlaps in: {phases} (windows: {windows})")
    lines.append("")
    return lines


def _render_lead_time_flags(handoff: PMHandoff) -> list[str]:
    flags = handoff.lead_time_flags or []
    if not flags:
        return []
    lines = [
        "## Lead-time risk",
        "",
        "BOM items whose lead times may gate the project schedule. Order early or accept slip risk.",
        "",
        "| Tier | Part # | Description | Qty | Lead time | Source |",
        "|:--|---|---|---:|---|---|",
    ]
    tier_emoji = {"extreme": "🚨", "long": "⚠️", "medium": "⏰", "unknown": "❓"}
    for f in flags[:25]:
        emoji = tier_emoji.get(f.get("risk_tier",""), "")
        lines.append(
            f"| {emoji} {f.get('risk_tier','')} | `{f.get('part_number','')}` | "
            f"{f.get('description','')} | {f.get('quantity', 0)} | "
            f"{f.get('lead_time_text','')} | `{f.get('source','')}` |"
        )
    lines.append("")
    return lines


def _render_license_items(handoff: PMHandoff) -> list[str]:
    items = handoff.license_items or []
    if not items:
        return []
    lines = [
        "## Recurring software & licenses",
        "",
        "Items billed as licenses, subscriptions, or maintenance — different P&L treatment than hardware capex.",
        "",
        "| Part # | Description | Qty | Unit price | Term | Source |",
        "|---|---|---:|---:|---|---|",
    ]
    for li in items[:25]:
        up = li.get("unit_price", 0)
        up_disp = f"${int(up):,}" if up else "—"
        lines.append(
            f"| `{li.get('part_number','')}` | {li.get('description','')[:80]} | "
            f"{li.get('quantity', 0)} | {up_disp} | {li.get('term_text','') or '—'} | "
            f"`{li.get('source','')}` |"
        )
    lines.append("")
    return lines


def _render_subcontractors(handoff: PMHandoff) -> list[str]:
    subs = handoff.subcontractor_mentions or []
    if not subs:
        return []
    lines = [
        "## Subcontractors & vendors named",
        "",
        "Parties referenced in the intake. PM should confirm contract status with each.",
        "",
        "| Name | Likely role | Source | Mention |",
        "|---|---|---|---|",
    ]
    for s in subs:
        lines.append(
            f"| **{s.get('name','')}** | {s.get('role_hint','') or '—'} | "
            f"`{s.get('source','')}` | {s.get('snippet','')[:160]} |"
        )
    lines.append("")
    return lines


def _render_sla_penalties(handoff: PMHandoff) -> list[str]:
    pens = handoff.sla_penalties or []
    if not pens:
        return []
    pretty = {
        "liquidated_damages": "Liquidated damages",
        "sla_credit": "SLA service credit",
        "termination_right": "Termination right",
        "uptime_sla": "Uptime / availability SLA",
        "response_sla": "Response-time SLA",
        "late_delivery": "Late delivery penalty",
    }
    lines = [
        "## SLA penalties & liquidated damages",
        "",
        "**Route to legal review.** Any of these can produce a contractual penalty if the project misses targets.",
        "",
        "| Kind | Source | Snippet |",
        "|---|---|---|",
    ]
    for p in pens:
        lines.append(
            f"| {pretty.get(p.get('kind',''), p.get('kind',''))} | "
            f"`{p.get('source','')}` | {p.get('snippet','')[:180].replace('|','\\|')} |"
        )
    lines.append("")
    return lines


def _render_change_order_triggers(handoff: PMHandoff) -> list[str]:
    co = handoff.change_order_triggers or []
    if not co:
        return []
    lines = [
        "## Change-order triggers detected",
        "",
        "Clauses that will require a Change Order if invoked. PM should pre-stage CO templates.",
        "",
    ]
    for c in co:
        kind = c.get("kind","")
        snippet = (c.get("snippet","") or "").replace("|", "\\|")
        lines.append(f"- **{kind}**: {snippet} _(source: `{c.get('source','')}`)_")
    lines.append("")
    return lines


def _render_currencies_taxes(handoff: PMHandoff) -> list[str]:
    cur = handoff.currency_mentions or []
    tax = handoff.tax_clauses or []
    if not (cur or tax):
        return []
    lines = ["## Currencies & tax", ""]
    if cur:
        lines.append("**Non-USD currency mentions detected:**")
        lines.append("")
        for c in cur:
            lines.append(
                f"- {c.get('currency','?')} {int(c.get('amount',0)):,} "
                f"in `{c.get('source','')}`: \"{c.get('snippet','')[:160]}\""
            )
        lines.append("")
    if tax:
        lines.append("**Tax clauses:**")
        lines.append("")
        for t in tax:
            rate = t.get("rate_pct", 0)
            rate_disp = f"{rate}%" if rate else "(inclusive/exclusive language)"
            lines.append(
                f"- **{t.get('label','')}** {rate_disp} "
                f"in `{t.get('source','')}`: \"{t.get('snippet','')[:160]}\""
            )
        lines.append("")
    return lines


def _render_risk_aging(handoff: PMHandoff) -> list[str]:
    aging = handoff.risk_aging or []
    if not aging:
        return []
    lines = [
        "## Risk aging",
        "",
        "How long each risk has been open. Stale risks (≥30 days) need escalation.",
        "",
        "| ID | Severity | Days open | Bucket | Description |",
        "|---|:-:|---:|:--|---|",
    ]
    bucket_emoji = {"fresh": "🟢", "active": "🟡", "stale": "🔴"}
    for a in aging:
        emoji = bucket_emoji.get(a.get("aging_bucket",""), "")
        lines.append(
            f"| {a.get('risk_id','')} | {a.get('severity','')} | "
            f"{a.get('days_open', 0)} | {emoji} {a.get('aging_bucket','')} | "
            f"{a.get('description','')[:120].replace('|','\\|')} |"
        )
    lines.append("")
    return lines


def _render_actions_by_week(handoff: PMHandoff) -> list[str]:
    buckets = handoff.actions_by_week or {}
    if not any(buckets.values()):
        return []
    titles = {
        "this_week": "This week",
        "next_week": "Next week",
        "later": "Later",
        "no_date": "No date set",
    }
    lines = ["## Action items by due-date week", ""]
    for k in ("this_week", "next_week", "later", "no_date"):
        items = buckets.get(k) or []
        if not items:
            continue
        lines.append(f"### {titles[k]}")
        lines.append("")
        for a in items:
            owner = a.get("owner") or "PM"
            due = f" — due {a.get('due')}" if a.get("due") else ""
            sev = a.get("severity") or ""
            sev_tag = f" **[{sev}]**" if sev in {"blocker", "warning"} else ""
            lines.append(f"- [ ]{sev_tag} {a.get('label','')} (owner: {owner}{due})")
        lines.append("")
    return lines


def _render_acceptance_by_site(handoff: PMHandoff) -> list[str]:
    by_site = handoff.acceptance_by_site or {}
    if not by_site:
        return []
    # Suppress when project_wide is the only bucket (covered by main checklist).
    if list(by_site.keys()) == ["project_wide"]:
        return []
    lines = [
        "## Acceptance criteria by site",
        "",
        "The same exit-criteria list, but grouped by site so each field crew sees their slice.",
        "",
    ]
    for site, checks in sorted(by_site.items()):
        if not checks:
            continue
        lines.append(f"### {site}")
        lines.append("")
        for c in checks:
            lines.append(f"- [ ] {c.get('criterion','')} (owner: {c.get('owner','—')})")
        lines.append("")
    return lines


def render_pm_executive_markdown(handoff: PMHandoff) -> str:
    """Short PM-facing view: no evidence flood, just readiness and actions."""
    icon = _STATUS_ICON.get(handoff.status, "⚪")
    lines: list[str] = [
        f"# PM Intake Readiness — {handoff.case_id}",
        "",
        f"**Status:** {icon} **{handoff.status_label}**",
        "",
        f"> {handoff.one_line_summary}",
        "",
        "## What the PM does next",
        "",
    ]
    if handoff.status == "red":
        lines.append("1. Do **not** publish the SOW yet.")
        lines.append("2. Send the blocker questions below to the customer / vendor / internal owner.")
        lines.append("3. Assign the solution-architect review items before draft lock.")
    elif handoff.status == "yellow":
        lines.append("1. Draft is possible, but PM review is required before publish.")
        lines.append("2. Resolve or consciously accept the warning questions below.")
        lines.append("3. Confirm the SA review lane has no design blockers.")
    else:
        lines.append("1. Intake is clean against the current rulebook.")
        lines.append("2. Proceed to SOW drafting with normal PM review.")
    lines.append("")
    lines.extend(_render_scorecard(handoff))
    lines.extend(_render_sites(handoff))
    lines.extend(_render_domains(handoff))
    lines.extend(_render_questions(handoff))
    lines.extend(_render_customer_email(handoff))
    return "\n".join(lines).rstrip() + "\n"


def render_solution_architect_markdown(handoff: PMHandoff) -> str:
    """Detailed SA-facing view: source-backed technical/commercial evidence."""
    lines: list[str] = [
        f"# Solution Architect Review Packet — {handoff.case_id}",
        "",
        f"**PM readiness:** {_STATUS_ICON.get(handoff.status, '⚪')} {handoff.status_label}",
        "",
        f"> {handoff.one_line_summary}",
        "",
    ]
    lines.extend(_render_solution_architect_view(handoff))
    lines.extend(_render_known_facts(handoff))
    lines.extend(_render_source_inventory(handoff))
    return "\n".join(lines).rstrip() + "\n"
