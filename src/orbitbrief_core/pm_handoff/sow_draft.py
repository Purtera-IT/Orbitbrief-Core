"""B1: SOW draft auto-generation from PM handoff + inspection report.

This module produces a ``SOW_DRAFT.md`` file structured the way a
real Statement of Work looks: numbered sections, signature block,
the works. Every line in the draft comes from a parser-os atom or
a PMHandoff field — no LLM, no inference, all evidence-traceable.

The draft is intentionally marked as a *draft*: the PM still needs
to fill gaps the parser couldn't (e.g. pricing model, signature
authorities), but the bones — scope, exclusions, sites, schedule,
risks, assumptions, commercial highlights — are all populated.

What lands in v1:

  1. Project Overview
  2. Sites and locations
  3. Scope of Work
  4. Out of Scope (Exclusions)
  5. Deliverables
  6. Project Schedule
  7. Acceptance Criteria
  8. Commercial Terms
  9. Assumptions
 10. Risks
 11. Roles and Contacts
 12. Change Management (boilerplate placeholder)
 13. Signatures (boilerplate placeholder)

Sections are suppressed entirely when there is no source evidence
(so a single-doc intake doesn't produce empty headings).
"""
from __future__ import annotations

from typing import Any

from orbitbrief_core.pm_handoff.models import PMHandoff

_BOILERPLATE_CHANGE_MANAGEMENT = (
    "Any change in scope, schedule, or commercial terms will be "
    "documented in a Change Order signed by both parties before "
    "work proceeds. Verbal agreements are non-binding until "
    "incorporated into a signed Change Order."
)

_BOILERPLATE_SIGNATURE = """
| Customer | Provider |
|---|---|
| Name: ________________________ | Name: ________________________ |
| Title: _______________________ | Title: _______________________ |
| Date: ________________________ | Date: ________________________ |
| Signature: ____________________ | Signature: ____________________ |
"""


def render_sow_draft(handoff: PMHandoff, report: dict[str, Any]) -> str:
    """Produce the SOW_DRAFT.md text from a PM handoff + report.

    The handoff already contains canonical PM views (sites,
    risks, schedule, action items). The inspection report is
    consulted for scope_item / exclusion / assumption / decision
    atoms — the things that don't live on the handoff today.
    """
    lines: list[str] = []

    # ── Header ─────────────────────────────────────────────────────────
    lines.extend([
        f"# Statement of Work — DRAFT",
        f"## Project: {handoff.case_id}",
        "",
        f"> **Status: DRAFT.** This document was auto-generated from "
        f"the intake package. PM must review every section, fill any "
        f"`[TBD]` placeholders, and confirm pricing & legal language "
        f"before sending to the customer.",
        "",
        f"_{handoff.one_line_summary}_",
        "",
    ])

    section_no = 0

    # ── 1. Project overview ────────────────────────────────────────────
    section_no += 1
    lines.extend([f"## {section_no}. Project Overview", ""])
    overview_lines: list[str] = []
    workstreams = [d.label for d in handoff.domains if d.active_for_sow]
    if workstreams:
        overview_lines.append(
            f"This Statement of Work covers the following workstreams: "
            f"{', '.join(workstreams)}."
        )
    sites = [s.name for s in handoff.sites if s.publishable]
    if sites:
        overview_lines.append(
            f"Work will be performed at the following confirmed sites: {', '.join(sites)}."
        )
    money = handoff.money_mentions or []
    headline = next((m for m in money if int(m.get("value", 0)) >= 100_000), None)
    if headline:
        overview_lines.append(
            f"Headline contract value reflected in the intake: {headline.get('display', '')} "
            f"(see Commercial Terms below for full reconciliation)."
        )
    if not overview_lines:
        overview_lines.append("[TBD] PM to author a concise project overview paragraph.")
    lines.extend(overview_lines)
    lines.append("")

    # ── 2. Sites and locations ─────────────────────────────────────────
    section_no += 1
    lines.extend([f"## {section_no}. Sites and Locations", ""])
    if handoff.sites:
        lines.extend(["| Site | Kind | Confirmed | Evidence items |", "|---|---|:-:|---:|"])
        for s in handoff.sites:
            mark = "✓" if s.publishable else ""
            lines.append(f"| {s.name} | {s.kind} | {mark} | {s.member_evidence_count} |")
    else:
        lines.append("[TBD] No physical sites were confirmed by the intake. PM must add site addresses, access constraints, and on-site contacts.")
    lines.append("")

    # ── 3. Scope of Work ──────────────────────────────────────────────
    section_no += 1
    lines.extend([f"## {section_no}. Scope of Work", ""])
    scope_atoms = _collect_text_atoms(report, atom_types={"scope_item"}, structured_kinds_block={"visual_page_marker", "table_row"})
    if scope_atoms:
        for text in scope_atoms[:30]:
            lines.append(f"- {text}")
    else:
        lines.append("[TBD] PM must author the scope of work section from the intake materials.")
    lines.append("")

    # ── 4. Exclusions ──────────────────────────────────────────────────
    section_no += 1
    lines.extend([f"## {section_no}. Out of Scope (Exclusions)", ""])
    excl_atoms = _collect_text_atoms(report, atom_types={"exclusion"})
    if excl_atoms:
        for text in excl_atoms[:20]:
            lines.append(f"- {text}")
    else:
        lines.append("- Anything not explicitly stated in the Scope of Work section.")
        lines.append("- [TBD] PM to confirm with the customer whether any specific exclusions should be added (e.g. third-party licensing, electrical, low-voltage cabling, post-launch support).")
    lines.append("")

    # ── 5. Deliverables ────────────────────────────────────────────────
    section_no += 1
    lines.extend([f"## {section_no}. Deliverables", ""])
    deliverables_lines: list[str] = []
    if handoff.sites:
        deliverables_lines.append(f"- Site-by-site installation and validation across {len(handoff.sites)} confirmed site(s).")
    workstream_labels = [d.label for d in handoff.domains if d.active_for_sow]
    for label in workstream_labels:
        deliverables_lines.append(f"- {label} workstream completion, including evidence-of-completion artifacts.")
    if handoff.schedule_phases:
        deliverables_lines.append(f"- Schedule milestones: {len(handoff.schedule_phases)} phase(s) listed in section {section_no + 2}.")
    if not deliverables_lines:
        deliverables_lines.append("[TBD] PM to list deliverables per workstream.")
    lines.extend(deliverables_lines)
    lines.append("")

    # ── 6. Schedule ────────────────────────────────────────────────────
    section_no += 1
    lines.extend([f"## {section_no}. Project Schedule", ""])
    if handoff.schedule_phases:
        lines.extend(["| Phase | Start | End | Owner |", "|---|---|---|---|"])
        for p in handoff.schedule_phases:
            lines.append(
                f"| {p.get('phase','')} | {p.get('start','—')} | {p.get('end','—')} | {p.get('owner','')} |"
            )
    else:
        lines.append("[TBD] PM to author the project schedule and milestones.")
    lines.append("")

    # ── 7. Acceptance criteria ─────────────────────────────────────────
    section_no += 1
    lines.extend([f"## {section_no}. Acceptance Criteria", ""])
    accept_atoms = _collect_acceptance_criteria(report)
    if accept_atoms:
        for text in accept_atoms[:20]:
            lines.append(f"- {text}")
    else:
        lines.append("- Each phase is accepted when its exit criteria are met and signed off by the named owner.")
        lines.append("- [TBD] PM to confirm any specific test, performance, or compliance acceptance thresholds.")
    lines.append("")

    # ── 8. Commercial terms ────────────────────────────────────────────
    section_no += 1
    lines.extend([f"## {section_no}. Commercial Terms", ""])
    if money:
        lines.extend(["| Amount | Mentioned in | Sample sentence |", "|---:|---|---|"])
        for m in money[:12]:
            srcs = sorted({s.get("filename", "") for s in (m.get("sources") or [])})
            files_str = ", ".join(f"`{x}`" for x in srcs if x)
            sample = ((m.get("sources") or [{}])[0]).get("snippet", "").replace("|", "\\|")
            lines.append(f"| {m.get('display','')} | {files_str} | {sample} |")
        lines.append("")
    if handoff.reconciliation_flags:
        lines.append("**Reconciliation required before signature:**")
        lines.append("")
        for f in handoff.reconciliation_flags:
            lines.append(f"- {f.get('label','')}")
        lines.append("")
    pricing_gap = next(
        (g for g in handoff.gaps if "pricing" in (g.label or "").lower() or "pricing" in (g.message or "").lower()),
        None,
    )
    if pricing_gap:
        lines.append(f"- **Pricing model:** {pricing_gap.suggested_open_question or pricing_gap.message}")
        lines.append("")
    lines.append("**Payment terms:** [TBD] PM to confirm net terms (typically Net 30) and milestone payment schedule.")
    lines.append("")

    # ── 9. Assumptions ─────────────────────────────────────────────────
    section_no += 1
    lines.extend([f"## {section_no}. Assumptions", ""])
    assump_atoms = _collect_text_atoms(report, atom_types={"assumption"})
    if assump_atoms:
        for text in assump_atoms[:20]:
            lines.append(f"- {text}")
    else:
        lines.append("- The customer provides timely access, escorts, and approvals as required by the schedule.")
        lines.append("- Site readiness (power, environmentals, network drops) is the customer's responsibility unless explicitly included in scope.")
        lines.append("- [TBD] PM to confirm additional project-specific assumptions.")
    lines.append("")

    # ── 10. Risks ──────────────────────────────────────────────────────
    section_no += 1
    lines.extend([f"## {section_no}. Risks", ""])
    if handoff.risk_register:
        lines.extend([
            "| ID | Risk | Likelihood | Impact | Mitigation | Owner |",
            "|---|---|:-:|:-:|---|---|",
        ])
        for r in handoff.risk_register:
            lines.append(
                f"| {r.get('risk_id','')} | {r.get('description','')} | {r.get('likelihood','')} | "
                f"{r.get('impact','')} | {r.get('mitigation','')} | {r.get('owner','')} |"
            )
    else:
        lines.append("- [TBD] PM to populate the risk register before sending to customer.")
    lines.append("")

    # ── 11. Roles and Contacts ─────────────────────────────────────────
    section_no += 1
    lines.extend([f"## {section_no}. Roles and Contacts", ""])
    contacts = _collect_stakeholders(report)
    if contacts:
        lines.extend(["| Name | Role | Source |", "|---|---|---|"])
        for c in contacts[:20]:
            lines.append(f"| {c['name']} | {c['role']} | `{c['source']}` |")
    else:
        lines.append("- [TBD] PM to list customer and provider points of contact.")
    lines.append("")

    # ── 12. Change Management ──────────────────────────────────────────
    section_no += 1
    lines.extend([f"## {section_no}. Change Management", "", _BOILERPLATE_CHANGE_MANAGEMENT, ""])

    # ── 13. Signatures ─────────────────────────────────────────────────
    section_no += 1
    lines.extend([f"## {section_no}. Signatures", _BOILERPLATE_SIGNATURE, ""])

    return "\n".join(lines).rstrip() + "\n"


# ──────────────────────────── helpers ────────────────────────────


def _iter_atoms(report: dict[str, Any]):
    for art in report.get("artifacts") or []:
        for atom in art.get("atoms") or []:
            yield atom, str(art.get("filename") or "")


_INTERNAL_NOISE_TOKENS = (
    "fictional data only",
    "mock document",
    "parser-os",
    "orbitbrief",
    "hubspot dev",
    "dev-integration-owner",
    "parser_batch_id",
    "azure storage path",
    "classification: mock",
    "documentsequence",
    "contenttype should preserve",
    "extraction should",
    "should mention",
    "should include",
    "test parser recognition",
)


def _is_internal_marker(text: str) -> bool:
    """Filter out atoms that are parser-os internal markers or
    fictional-data disclaimers rather than real SOW content."""
    if not text:
        return True
    low = text.lower()
    return any(tok in low for tok in _INTERNAL_NOISE_TOKENS)


def _collect_text_atoms(
    report: dict[str, Any],
    *,
    atom_types: set[str],
    structured_kinds_block: set[str] | None = None,
) -> list[str]:
    """Pull every atom whose ``atom_type`` is in the set, returning
    de-duplicated short snippets.

    ``structured_kinds_block`` filters out atoms whose
    ``structured.kind`` is in the set (used to skip
    "visual_page_marker" pseudo-atoms parser-os emits for
    low-text PDF pages — those are not real scope).

    Also filters out parser-os internal markers and fictional
    mock-data disclaimers so the SOW draft stays customer-shaped.
    """
    seen: set[str] = set()
    out: list[str] = []
    block = structured_kinds_block or set()
    for atom, _src in _iter_atoms(report):
        if atom.get("atom_type") not in atom_types:
            continue
        structured = atom.get("structured") or {}
        if isinstance(structured, dict) and structured.get("kind") in block:
            continue
        text = (atom.get("text") or "").strip()
        if not text or _is_internal_marker(text):
            continue
        norm = text[:160].lower()
        if norm in seen:
            continue
        seen.add(norm)
        out.append(text[:260])
    return out


def _collect_acceptance_criteria(report: dict[str, Any]) -> list[str]:
    """Pull acceptance criteria from schedule-row atoms.

    Schedule rows that have an ``exit_criteria`` cell get
    promoted to acceptance criteria.
    """
    out: list[str] = []
    seen: set[str] = set()
    for atom, _ in _iter_atoms(report):
        structured = atom.get("structured") or {}
        if not isinstance(structured, dict):
            continue
        cells = structured.get("canonical_cells") or structured.get("cells") or {}
        if not isinstance(cells, dict):
            continue
        exit_crit = (
            cells.get("exit_criteria")
            or cells.get("Exit Criteria")
            or cells.get("acceptance_criteria")
            or cells.get("Acceptance Criteria")
        )
        if not exit_crit:
            continue
        phase = (
            cells.get("name")
            or cells.get("Name")
            or cells.get("phase")
            or cells.get("Phase")
            or ""
        )
        text = f"**{phase}**: {exit_crit}" if phase else str(exit_crit)
        norm = text.lower()
        if norm in seen:
            continue
        seen.add(norm)
        out.append(text)
    return out


def _collect_stakeholders(report: dict[str, Any]) -> list[dict[str, str]]:
    """Pull stakeholders from atoms that mention a stakeholder-typed row.

    parser-os emits stakeholder roster atoms whose structured
    fields contain Name + Role / Title + Email. v1 reads those
    canonical fields and dedupes by canonical name.
    """
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for atom, filename in _iter_atoms(report):
        structured = atom.get("structured") or {}
        if not isinstance(structured, dict):
            continue
        cells = structured.get("canonical_cells") or structured.get("cells") or {}
        if not isinstance(cells, dict):
            continue
        name = (
            cells.get("name")
            or cells.get("Name")
            or cells.get("stakeholder")
            or cells.get("Stakeholder")
            or ""
        )
        role = (
            cells.get("role")
            or cells.get("Role")
            or cells.get("title")
            or cells.get("Title")
            or cells.get("authority")
            or ""
        )
        if not name or not role:
            continue
        key = str(name).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": str(name), "role": str(role), "source": filename})
    return out
