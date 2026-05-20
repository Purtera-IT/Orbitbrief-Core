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
        "This report translates the intake package into evidence, SOW gaps, customer questions, and SA review work.",
        "",
    ]
    lines.extend(_render_scorecard(handoff))
    lines.extend(_render_domains(handoff))
    lines.extend(_render_sites(handoff))
    lines.extend(_render_site_rollups(handoff))
    lines.extend(_render_risk_register(handoff))
    lines.extend(_render_schedule(handoff))
    lines.extend(_render_action_items(handoff))
    lines.extend(_render_reconciliation(handoff))
    lines.extend(_render_questions(handoff))
    lines.extend(_render_known_facts(handoff))
    lines.extend(_render_solution_architect_view(handoff))
    lines.extend(_render_source_inventory(handoff))
    lines.extend(_render_customer_email(handoff))
    lines.extend(_render_stakeholder_pagers(handoff))
    return "\n".join(lines).rstrip() + "\n"


def render_portfolio_markdown(handoffs: Iterable[PMHandoff]) -> str:
    handoffs = list(handoffs)
    red = sum(1 for h in handoffs if h.status == "red")
    yellow = sum(1 for h in handoffs if h.status == "yellow")
    green = sum(1 for h in handoffs if h.status == "green")
    lines = [
        "# OrbitBrief PM Portfolio Dashboard",
        "",
        f"**Cases:** {len(handoffs)}  ·  🔴 {red} red  ·  🟡 {yellow} yellow  ·  🟢 {green} green",
        "",
        "| Case | Status | Sites | Workstreams | Blockers | Warnings | Evidence items |",
        "|---|---|---:|---|---:|---:|---:|",
    ]
    for h in handoffs:
        domains = ", ".join(d.label for d in h.domains if d.selected_by_router or d.active_for_sow)
        lines.append(
            f"| `{h.case_id}` | {_STATUS_ICON.get(h.status, '⚪')} {h.status_label} | {h.metrics.get('sites_published', 0)} | {domains[:130]} | {h.metrics.get('blockers', 0)} | {h.metrics.get('warnings', 0)} | {h.metrics.get('evidence_items_extracted', 0)} |"
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
    """
    rows = handoff.risk_register or []
    if not rows:
        return []
    lines: list[str] = [
        "## Risk register",
        "",
        "| ID | Risk | Likelihood | Impact | Mitigation | Owner | Sites |",
        "|---|---|:-:|:-:|---|---|---|",
    ]
    for r in rows:
        sites = ", ".join(r.get("sites") or []) or "—"
        desc = (r.get("description") or "").replace("|", "\\|")
        miti = (r.get("mitigation") or "").replace("|", "\\|")
        lines.append(
            f"| {r.get('risk_id','')} | {desc} | {r.get('likelihood','')} | "
            f"{r.get('impact','')} | {miti} | {r.get('owner','')} | {sites} |"
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
