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
    lines.extend(_render_reconciliation(handoff))
    lines.extend(_render_questions(handoff))
    lines.extend(_render_known_facts(handoff))
    lines.extend(_render_solution_architect_view(handoff))
    lines.extend(_render_source_inventory(handoff))
    lines.extend(_render_customer_email(handoff))
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


def _render_customer_email(handoff: PMHandoff) -> list[str]:
    questions = handoff.customer_questions[:18]
    lines = ["## Customer clarification email starter", ""]
    if not questions:
        return lines + ["No clarification email is required from the current rulebook output.", ""]
    lines.extend([
        "```text",
        "Subject: Clarifications needed before SOW draft",
        "",
        "Hi team,",
        "",
        "We reviewed the intake package and need the following clarifications before we can finalize the SOW:",
        "",
    ])
    for i, g in enumerate(questions, 1):
        lines.append(f"{i}. {g.suggested_open_question or g.message}")
    lines.extend([
        "",
        "Once we have these answers, we can update the scope, assumptions, exclusions, acceptance criteria, and commercial terms.",
        "",
        "Thanks,",
        "Project team",
        "```",
        "",
    ])
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
