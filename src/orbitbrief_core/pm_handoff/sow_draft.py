"""B1: SOW draft auto-generation from PM handoff + inspection report.

This module produces a ``SOW_DRAFT.md`` file structured the way a
real Statement of Work looks. Every line is built deterministically
from parser-os atoms or PMHandoff fields — no LLM, no inference,
all evidence-traceable.

The draft is intentionally marked as a draft: the PM still needs
to fill jurisdiction-specific clauses (governing law, IP
language) and to verify the signature block. But the bones —
scope, exclusions, sites, schedule, pricing breakdown, payment
milestones, risks, customer + provider responsibilities,
compliance, full legal boilerplate, signature block — are all
populated and editable.

Section layout (21 numbered sections + cover page):

  Cover page (project name, document control, exec summary)
   1. Background & Objectives
   2. Project Scope
       2.1 Workstreams in scope
       2.2 In-scope services (deduped from atoms)
       2.3 Out of scope (exclusions)
   3. Sites & Locations
   4. Deliverables
   5. Project Schedule & Milestones
       5.1 Phase milestones
       5.2 Critical path
   6. Acceptance Criteria
   7. Pricing & Payment Schedule
       7.1 Cost breakdown
       7.2 Payment milestones
       7.3 Pricing model
       7.4 Tax handling
   8. Customer Responsibilities
   9. Provider Responsibilities
  10. Assumptions
  11. Risks & Mitigation
  12. Compliance & Legal References
  13. Change Management
  14. Confidentiality & IP
  15. Warranty
  16. Limitation of Liability
  17. Term & Termination
  18. Force Majeure
  19. Governing Law
  20. Stakeholders & Points of Contact
  21. Signatures
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from orbitbrief_core.pm_handoff.models import PMHandoff


# Use the boilerplate clauses we curated in pm_intelligence so SOW
# draft + PM_HANDOFF stay in sync.
try:
    from orbitbrief_core.pm_handoff.pm_intelligence import SOW_DEFAULTS
except Exception:  # pragma: no cover — defensive
    SOW_DEFAULTS = {}


# ──────────────────────────── helpers ────────────────────────────


def _humanize_case_id(case_id: str) -> str:
    """``OPTBOT_Atlanta_Office_Refresh_Mock_Deal`` → ``OPTBOT Atlanta
    Office Refresh``. Drops obvious test-data suffixes."""
    if not case_id:
        return "[Project name TBD]"
    parts = case_id.replace("_", " ").split()
    # Strip suffix tokens that mark test fixtures
    drop_tail = {"mock", "deal", "test", "demo", "fake"}
    while parts and parts[-1].lower() in drop_tail:
        parts.pop()
    return " ".join(parts) or case_id


def _humanize_site_name(name: str) -> str:
    """``atl hq`` → ``ATL-HQ``; ``airport logistics annex`` →
    ``Airport Logistics Annex``."""
    if not name:
        return ""
    parts = name.split()
    # Short tokens → likely a code → uppercase + hyphenate
    if all(len(p) <= 4 for p in parts) and len(parts) <= 3:
        return "-".join(p.upper() for p in parts if p)
    return " ".join(p.capitalize() for p in parts if p)


_INTERNAL_NOISE_TOKENS = (
    "fictional data only", "mock document", "parser-os", "orbitbrief",
    "hubspot dev", "dev-integration-owner", "parser_batch_id",
    "azure storage path", "classification: mock", "documentsequence",
    "contenttype should preserve", "extraction should", "should mention",
    "should include", "test parser recognition", "hubspot deal id:",
    "mock deal", "dealstage", "dev deal", "sample data", "synthetic",
    "expected hubspot", "expected azure", "expected parser",
    "executive brief pdf. 2.", "statement of work docx.",
    "should be installed", "filename should",
)


def _is_internal_marker(text: str) -> bool:
    """Filter out parser-os internals + fictional-data disclaimers."""
    if not text:
        return True
    low = text.lower()
    return any(tok in low for tok in _INTERNAL_NOISE_TOKENS)


def _iter_atoms(report: dict[str, Any]):
    for art in report.get("artifacts") or []:
        for atom in art.get("atoms") or []:
            yield atom, str(art.get("filename") or "")


def _collect_text_atoms(
    report: dict[str, Any],
    *,
    atom_types: set[str],
    structured_kinds_block: set[str] | None = None,
    cap: int = 30,
) -> list[str]:
    """De-duplicated text snippets from atoms of the requested types."""
    block = structured_kinds_block or set()
    seen_norm: set[str] = set()
    out: list[str] = []
    for atom, _src in _iter_atoms(report):
        if atom.get("atom_type") not in atom_types:
            continue
        structured = atom.get("structured") or {}
        if isinstance(structured, dict) and structured.get("kind") in block:
            continue
        text = (atom.get("text") or "").strip()
        if not text or _is_internal_marker(text):
            continue
        # Drop atoms that are mid-sentence fragments or shorter than a
        # real bullet (parser-os occasionally emits these from PDFs
        # where a sentence crosses a layout boundary).
        if len(text) < 25 or not text[0].isupper():
            continue
        # Normalize for dedup
        norm = re.sub(r"\s+", " ", text[:200]).lower()
        if norm in seen_norm:
            continue
        seen_norm.add(norm)
        out.append(text[:400])
        if len(out) >= cap:
            break
    return out


def _collect_acceptance_criteria(report: dict[str, Any]) -> list[dict[str, str]]:
    """Pull phase exit-criteria + cutover checklist items into structured rows."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for atom, _ in _iter_atoms(report):
        structured = atom.get("structured") or {}
        if not isinstance(structured, dict):
            continue
        cells = structured.get("canonical_cells") or structured.get("cells") or {}
        if not isinstance(cells, dict):
            continue
        exit_crit = (
            cells.get("exit_criteria") or cells.get("Exit Criteria")
            or cells.get("acceptance_criteria") or cells.get("Acceptance Criteria")
        )
        if not exit_crit:
            continue
        phase = str(
            cells.get("name") or cells.get("Name")
            or cells.get("phase") or cells.get("Phase") or ""
        )
        owner = str(cells.get("owner") or cells.get("Owner") or "")
        key = (phase + "|" + str(exit_crit))[:160].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "phase": phase or "General",
            "criterion": str(exit_crit),
            "owner": owner,
        })
    return out


def _collect_payment_terms(report: dict[str, Any]) -> list[dict[str, str]]:
    """Pull explicit % milestones from atom text.

    Pattern: ``30% at order acceptance, 40% on equipment receipt, …``
    """
    schedule_re = re.compile(
        r"(\d{1,3})\s*%\s*(?:at|on|after|upon)?\s+([a-zA-Z][\w\s,/&\-]+?)(?=,|\.|$|\d+\s*%)",
        re.IGNORECASE,
    )
    out: list[dict[str, str]] = []
    seen: set[tuple[int, str]] = set()
    for atom, _ in _iter_atoms(report):
        text = (atom.get("text") or "")
        if "payment schedule" not in text.lower() and "%" not in text:
            continue
        for m in schedule_re.finditer(text):
            try:
                pct = int(m.group(1))
            except ValueError:
                continue
            if pct < 5 or pct > 100:
                continue
            milestone = m.group(2).strip().rstrip(".,;").strip()
            milestone = re.sub(r"\s+", " ", milestone)[:80]
            if not milestone:
                continue
            key = (pct, milestone.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append({"percentage": pct, "milestone": milestone})
            if len(out) >= 8:
                break
    return out


def _collect_stakeholder_table(report: dict[str, Any]) -> list[dict[str, str]]:
    """Stakeholder roster — pipe-separated ``Name | Title | Email | Role``."""
    pipe_roster_re = re.compile(
        r"([A-Z][\w\-']+(?:\s+[A-Z][\w\-']+){1,3})"
        r"\s*\|\s*"
        r"([A-Z][\w\s,\-/&]+?)"
        r"\s*\|\s*"
        r"([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})"
    )
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for atom, filename in _iter_atoms(report):
        text = atom.get("text") or ""
        if "|" not in text or "@" not in text:
            continue
        for m in pipe_roster_re.finditer(text):
            name = m.group(1).strip()
            role = m.group(2).strip()[:80]
            email = m.group(3).strip()
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append({"name": name, "role": role, "email": email, "source": filename})
    return out


def _today_iso() -> str:
    return date.today().isoformat()


def _filter_workstreams(domains: list[Any]) -> list[str]:
    """Pull only meaningful active workstreams (skip 'Commercial terms'
    + 'Sites / facilities' which are PM lenses, not delivery work)."""
    PM_LENSES = {"commercial terms", "sites / facilities", "global"}
    out: list[str] = []
    for d in domains or []:
        label = getattr(d, "label", "")
        if not getattr(d, "active_for_sow", False):
            continue
        if label.lower() in PM_LENSES:
            continue
        out.append(label)
    return out


# ──────────────────────────── main renderer ────────────────────────────


def render_sow_draft(handoff: PMHandoff, report: dict[str, Any]) -> str:
    """Produce the ``SOW_DRAFT.md`` text from a PM handoff + report."""
    lines: list[str] = []

    case_pretty = _humanize_case_id(handoff.case_id)
    today = _today_iso()
    sites_pretty = [_humanize_site_name(s.name) for s in handoff.sites if s.publishable]
    workstreams = _filter_workstreams(handoff.domains)
    money = handoff.money_mentions or []
    margin = handoff.margin_view or {}

    # ──── Cover ─────────────────────────────────────────────────────
    lines.extend([
        f"# Statement of Work",
        f"## {case_pretty}",
        "",
        "> **STATUS: DRAFT — not for execution.** This document was auto-generated from the intake package. PM must review every section, fill any `[TBD]` placeholders, confirm pricing and legal language with counsel, and lock the signature block before sending to the customer.",
        "",
        "### Document control",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Project | {case_pretty} |",
        f"| Document version | 0.1 (auto-draft) |",
        f"| Date prepared | {today} |",
        f"| Prepared by | OrbitBrief — auto-generated; PM review required |",
        f"| Classification | Confidential — internal review only until executed |",
        f"| Status | DRAFT |",
        "",
    ])

    # ──── Executive summary ─────────────────────────────────────────
    headline_money = ""
    if margin.get("deal_total"):
        headline_money = f"${int(margin['deal_total']):,}"
    elif money:
        big = next((m for m in money if int(m.get("value", 0)) >= 100_000), None)
        if big:
            headline_money = big.get("display", "")
    site_phrase = ", ".join(sites_pretty) if sites_pretty else "[TBD — sites pending]"
    workstream_phrase = ", ".join(workstreams) if workstreams else "[TBD]"
    lines.extend([
        "### Executive summary",
        "",
        f"This Statement of Work covers **{workstream_phrase}** across "
        f"**{len(sites_pretty)} confirmed site(s)** ({site_phrase}). "
        f"The headline contract value referenced in intake is **{headline_money or '[TBD]'}**. "
        f"Delivery is governed by the milestones, acceptance criteria, "
        f"and payment schedule defined below.",
        "",
    ])

    sn = 0  # section number counter

    # ──── 1. Background & Objectives ───────────────────────────────
    sn += 1
    lines.extend([f"## {sn}. Background & Objectives", ""])
    # Best-background heuristic: prefer a scope_item that mentions the
    # customer name + "refresh" / "modernization" / "implementation" etc.
    # — i.e. an actual project-purpose paragraph, not a procurement
    # boilerplate sentence.
    background_candidates = _collect_text_atoms(
        report, atom_types={"scope_item"},
        structured_kinds_block={"visual_page_marker", "table_row"},
        cap=15,
    )
    bg_keywords = ("refresh", "modernization", "implementation", "objective",
                   "wants a", "experience", "standard", "consistent")
    background_picked: list[str] = []
    for b in background_candidates:
        if any(k in b.lower() for k in bg_keywords) and len(b) > 60:
            background_picked.append(b)
            if len(background_picked) >= 1:
                break
    if not background_picked and background_candidates:
        background_picked = [background_candidates[0]]
    if background_picked:
        for b in background_picked:
            lines.append(f"- {b}")
    else:
        lines.append("- [TBD] PM to author 1–2 sentence project background.")
    lines.extend([
        "",
        f"**Project objectives:** Successfully deliver "
        f"{workstream_phrase} workstreams across {len(sites_pretty)} "
        f"confirmed site(s) within the schedule and budget defined herein, "
        f"satisfying the acceptance criteria in Section 6.",
        "",
    ])

    # ──── 2. Project Scope ─────────────────────────────────────────
    sn += 1
    lines.extend([f"## {sn}. Project Scope", ""])
    # 2.1 Workstreams
    lines.extend([f"### {sn}.1 Workstreams in scope", ""])
    if workstreams:
        for w in workstreams:
            lines.append(f"- {w}")
    else:
        lines.append("- [TBD] PM to confirm active workstreams.")
    # 2.2 In-scope services
    lines.extend(["", f"### {sn}.2 In-scope services", ""])
    scope_atoms = _collect_text_atoms(
        report, atom_types={"scope_item"},
        structured_kinds_block={"visual_page_marker", "table_row"},
        cap=20,
    )
    if scope_atoms:
        for s in scope_atoms:
            lines.append(f"- {s}")
    else:
        lines.append("- [TBD] PM to author scope-of-work bullets.")
    # 2.3 Out of scope
    lines.extend(["", f"### {sn}.3 Out of scope (exclusions)", ""])
    exclusion_items = list(handoff.exclusions or [])
    if exclusion_items:
        for e in exclusion_items:
            text = (e.get("text") or "").strip()
            if text and not _is_internal_marker(text):
                lines.append(f"- {text}")
    if not exclusion_items:
        lines.append("- Anything not explicitly stated in Section 2.2.")
        lines.append("- New construction, electrical, structural work, furniture procurement, legal review, customer communications.")
    lines.append("")

    # ──── 3. Sites & Locations ─────────────────────────────────────
    sn += 1
    lines.extend([f"## {sn}. Sites & Locations", ""])
    if handoff.sites:
        lines.extend([
            "| Site | Type | Evidence items | Source files | Notes |",
            "|---|---|---:|---:|---|",
        ])
        for s in handoff.sites:
            mark = "Confirmed" if s.publishable else "Unconfirmed"
            lines.append(
                f"| **{_humanize_site_name(s.name)}** | {s.kind} | "
                f"{s.member_evidence_count} | {s.artifact_count} | {mark} |"
            )
    else:
        lines.append("[TBD] No physical sites confirmed by intake. PM must add site addresses, primary contacts, access constraints, and on-site coordinator.")
    lines.append("")

    # ──── 4. Deliverables ──────────────────────────────────────────
    sn += 1
    lines.extend([f"## {sn}. Deliverables", ""])
    deliverables: list[tuple[str, str]] = []
    if sites_pretty:
        deliverables.append((
            "Site-by-site installation & validation",
            f"Each of the {len(sites_pretty)} sites installed, validated, and signed off per Section 6 acceptance criteria.",
        ))
    for w in workstreams[:6]:
        deliverables.append((
            f"{w} delivery package",
            f"Complete {w.lower()} work including installation, configuration, testing, and evidence-of-completion artifacts.",
        ))
    if handoff.schedule_phases:
        deliverables.append((
            "Milestone documentation",
            f"At each of the {len(handoff.schedule_phases)} schedule milestones (Section 5.1), delivery of the named exit artifacts.",
        ))
    deliverables.append((
        "Closeout package",
        "As-built documentation, asset inventory, test results, and customer-acceptance sign-off.",
    ))
    lines.extend([
        "| # | Deliverable | Description |",
        "|--:|---|---|",
    ])
    for i, (title, desc) in enumerate(deliverables, 1):
        lines.append(f"| {i} | **{title}** | {desc} |")
    lines.append("")

    # ──── 5. Project Schedule & Milestones ─────────────────────────
    sn += 1
    lines.extend([f"## {sn}. Project Schedule & Milestones", ""])
    lines.extend([f"### {sn}.1 Phase milestones", ""])
    if handoff.schedule_phases:
        lines.extend([
            "| # | Phase | Start | End | Owner |",
            "|--:|---|---|---|---|",
        ])
        for i, p in enumerate(handoff.schedule_phases, 1):
            lines.append(
                f"| {i} | {p.get('phase','')} | {p.get('start','')} | "
                f"{p.get('end','')} | {p.get('owner','') or '[TBD]'} |"
            )
    else:
        lines.append("[TBD] PM to author project schedule.")
    # Critical path — only render when SOME phases are critical and
    # SOME aren't (signal). When every phase is critical (purely
    # sequential schedule), the section adds no info; suppress.
    cp = handoff.critical_path or []
    if cp:
        critical_phases = [c.get("phase", "") for c in cp if c.get("is_critical")]
        non_critical = [c.get("phase", "") for c in cp if not c.get("is_critical")]
        if critical_phases and non_critical:
            lines.extend([
                "",
                f"### {sn}.2 Critical path",
                "",
                "The following phases have zero slack — a slip on any one shifts the project go-live:",
                "",
            ])
            for p in critical_phases:
                lines.append(f"- {p}")
            lines.append("")
            lines.append(
                f"_Non-critical phases (with slack): {', '.join(non_critical)}._"
            )
        elif critical_phases and not non_critical:
            lines.extend([
                "",
                f"### {sn}.2 Critical path",
                "",
                "All scheduled phases are sequential — every phase is on the critical path. A slip on any one moves go-live by the same amount.",
            ])
    lines.append("")

    # ──── 6. Acceptance Criteria ───────────────────────────────────
    sn += 1
    lines.extend([f"## {sn}. Acceptance Criteria", ""])
    accept = _collect_acceptance_criteria(report)
    if accept:
        lines.extend([
            "| Phase | Acceptance criterion | Owner |",
            "|---|---|---|",
        ])
        for a in accept:
            crit = (a.get("criterion") or "").replace("|", "\\|")
            lines.append(f"| {a.get('phase','')} | {crit} | {a.get('owner','') or '[TBD]'} |")
    else:
        lines.append("- [TBD] Each phase is accepted when its exit criteria are met and signed off by the named owner.")
    lines.append("")

    # ──── 7. Pricing & Payment Schedule ────────────────────────────
    sn += 1
    lines.extend([f"## {sn}. Pricing & Payment Schedule", ""])
    # 7.1 Cost breakdown
    lines.extend([f"### {sn}.1 Cost breakdown", ""])
    deal_total = int(margin.get("deal_total") or 0)
    hw = int(margin.get("hardware_cost_subtotal") or 0)
    svc = int(margin.get("services_subtotal") or 0)
    other = int(margin.get("other_cost_subtotal") or 0)
    if deal_total or hw or svc:
        lines.extend([
            "| Component | Amount (USD) |",
            "|---|---:|",
        ])
        if hw:
            lines.append(f"| Hardware | ${hw:,} |")
        if svc:
            lines.append(f"| Professional services | ${svc:,} |")
        if other:
            lines.append(f"| Logistics, freight, contingency, tax | ${other:,} |")
        if deal_total:
            lines.append(f"| **Contract total** | **${deal_total:,}** |")
        lines.append("")
        margin_pct = margin.get("margin_pct", 0)
        if margin_pct == 0 and hw and svc and deal_total:
            lines.append(
                f"_Note: extracted hardware + services + logistics = ${hw + svc + other:,} which "
                f"exactly matches the headline contract total. PM should confirm whether the "
                f"deal carries provider margin or is a pass-through arrangement._"
            )
            lines.append("")
    else:
        lines.append("[TBD] PM to author pricing breakdown.")
        lines.append("")
    # 7.2 Payment milestones
    lines.extend([f"### {sn}.2 Payment milestones", ""])
    payment_terms = _collect_payment_terms(report)
    if payment_terms:
        lines.extend([
            "| % | Milestone | Amount (USD) |",
            "|--:|---|---:|",
        ])
        for t in payment_terms:
            pct = t.get("percentage", 0)
            amt = int(round(deal_total * pct / 100.0)) if deal_total else 0
            amt_disp = f"${amt:,}" if amt else "[TBD]"
            lines.append(f"| {pct}% | {t.get('milestone','')} | {amt_disp} |")
    else:
        lines.append("[TBD] PM to confirm milestone-billing schedule (typical: 30% order acceptance / 40% equipment receipt / 20% site acceptance / 10% post-hypercare).")
    lines.append("")
    # 7.3 Pricing model
    lines.extend([f"### {sn}.3 Pricing model", ""])
    eng = handoff.engagement_model or {}
    model_pretty = {
        "fixed_fee": "Fixed Fee", "tm": "Time & Materials",
        "subscription": "Subscription / Recurring", "mixed": "Mixed",
        "unknown": "[TBD]",
    }.get(eng.get("detected_model", "unknown"), "[TBD]")
    lines.append(f"**Detected model:** {model_pretty}")
    if eng.get("has_tm_cap"):
        lines.append(f"  - T&M not-to-exceed cap: ${int(eng.get('tm_cap_amount', 0)):,}")
    lines.append("")
    lines.append(SOW_DEFAULTS.get("pricing_model", "[TBD] PM to insert pricing model clause."))
    if model_pretty == "[TBD]" or eng.get("detected_model") == "tm":
        lines.append("")
        lines.append(SOW_DEFAULTS.get("tm_terms", ""))
    lines.append("")
    # 7.4 Tax handling
    lines.extend([f"### {sn}.4 Tax handling & currency", ""])
    if handoff.tax_clauses:
        for t in handoff.tax_clauses:
            rate = t.get("rate_pct", 0)
            disp = f"{rate}%" if rate else "(inclusive/exclusive language)"
            lines.append(f"- **{t.get('label','')}** {disp} per `{t.get('source','')}`")
    else:
        lines.append("- All amounts in USD unless otherwise noted in payment milestone rows.")
        lines.append("- Pricing is **tax-exclusive**. Sales / use / VAT tax assessed per the customer's jurisdiction; quoted separately on invoice.")
    if handoff.currency_conversions:
        lines.append("- Non-USD references converted at the snapshot mid-market FX rate (see PM_HANDOFF Multi-currency section).")
    lines.append("")
    # 7.5 Payment terms boilerplate
    lines.extend([f"### {sn}.5 Payment terms", ""])
    lines.append(SOW_DEFAULTS.get("payment_terms", "Net 30 days from invoice receipt."))
    lines.append("")

    # ──── 8. Customer Responsibilities ─────────────────────────────
    sn += 1
    lines.extend([f"## {sn}. Customer Responsibilities", ""])
    customer_items = [r for r in (handoff.responsibilities or []) if r.get("party") == "customer"]
    if customer_items:
        for r in customer_items:
            lines.append(f"- {r.get('text','')}")
    else:
        lines.append("- Provide timely access to all sites, including escorts and after-hours approvals, per the schedule.")
        lines.append("- Supply final site addresses, room lists, and primary on-site contact per site.")
        lines.append("- Approve change orders and acceptance documents within 5 business days of submission.")
        lines.append("- Provide network connectivity, power, and environmental conditions for installed equipment.")
    lines.append("")

    # ──── 9. Provider Responsibilities ─────────────────────────────
    sn += 1
    lines.extend([f"## {sn}. Provider Responsibilities", ""])
    provider_items = [r for r in (handoff.responsibilities or []) if r.get("party") == "provider"]
    if provider_items:
        for r in provider_items:
            lines.append(f"- {r.get('text','')}")
    else:
        lines.append("- Deliver each workstream per the schedule in Section 5 and the acceptance criteria in Section 6.")
        lines.append("- Provide qualified installation and configuration personnel.")
        lines.append("- Manage subcontractors / distributors per Section 20 contacts.")
        lines.append("- Document and report progress weekly during execution.")
    lines.append("")

    # ──── 10. Assumptions ──────────────────────────────────────────
    sn += 1
    lines.extend([f"## {sn}. Assumptions", ""])
    assumption_atoms = _collect_text_atoms(report, atom_types={"assumption"}, cap=15)
    if assumption_atoms:
        for a in assumption_atoms:
            lines.append(f"- {a}")
    else:
        lines.append("- Site readiness (power, environmentals, network drops) is the customer's responsibility unless explicitly in scope above.")
        lines.append("- Customer approvals are returned within 5 business days.")
        lines.append("- Hardware list is final at SOW signature; substitutions follow Change Management.")
    lines.append("")

    # ──── 11. Risks & Mitigation ───────────────────────────────────
    sn += 1
    lines.extend([f"## {sn}. Risks & Mitigation", ""])
    if handoff.risk_register:
        lines.extend([
            "| ID | Risk | L | I | Mitigation | Owner |",
            "|---|---|:-:|:-:|---|---|",
        ])
        for r in handoff.risk_register:
            desc = (r.get("description") or "").replace("|", "\\|")
            miti = (r.get("mitigation") or "").replace("|", "\\|")
            lines.append(
                f"| {r.get('risk_id','')} | {desc} | {r.get('likelihood','')} | "
                f"{r.get('impact','')} | {miti} | {r.get('owner','') or '[TBD]'} |"
            )
    else:
        lines.append("- [TBD] PM to populate the risk register.")
    lines.append("")

    # ──── 12. Compliance & Legal References ────────────────────────
    sn += 1
    lines.extend([f"## {sn}. Compliance & Legal References", ""])
    callouts = handoff.compliance_callouts or []
    if callouts:
        # Group by framework
        from collections import defaultdict
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for c in callouts:
            grouped[c.get("framework", "Other")].append(c)
        lines.append("Frameworks and clauses referenced in intake (route to legal):")
        lines.append("")
        for framework in sorted(grouped):
            lines.append(f"- **{framework}**")
            for c in grouped[framework][:3]:
                src = c.get("source", "")
                snip = (c.get("snippet") or "").replace("|", "\\|")[:200]
                lines.append(f"  - From `{src}`: \"{snip}\"")
    else:
        lines.append("- [TBD] PM to confirm any specific compliance frameworks (SOC 2, HIPAA, PCI-DSS, etc.) that apply to this engagement.")
    lines.append("")

    # ──── 13. Change Management ────────────────────────────────────
    sn += 1
    lines.extend([f"## {sn}. Change Management", "", SOW_DEFAULTS.get("change_management", ""), ""])
    if handoff.change_order_triggers:
        lines.append("**Pre-identified change-order triggers in intake:**")
        lines.append("")
        for co in handoff.change_order_triggers:
            snip = (co.get("snippet") or "").replace("|", "\\|")[:200]
            # Trim mid-word leading characters so the snippet starts at
            # the first capital letter or sentence boundary.
            m = re.search(r"[A-Z]", snip)
            if m:
                snip = snip[m.start():]
            lines.append(f"- {snip} _(source: `{co.get('source','')}`)_")
        lines.append("")

    # ──── 14. Confidentiality & IP ─────────────────────────────────
    sn += 1
    lines.extend([
        f"## {sn}. Confidentiality & IP", "",
        f"### {sn}.1 Confidentiality",
        "",
        SOW_DEFAULTS.get("confidentiality", ""),
        "",
        f"### {sn}.2 Intellectual property",
        "",
        SOW_DEFAULTS.get("ip_rights", ""),
        "",
    ])

    # ──── 15. Warranty ─────────────────────────────────────────────
    sn += 1
    lines.extend([f"## {sn}. Warranty", "", SOW_DEFAULTS.get("warranty", ""), ""])

    # ──── 16. Limitation of Liability ──────────────────────────────
    sn += 1
    lines.extend([f"## {sn}. Limitation of Liability", "", SOW_DEFAULTS.get("liability_cap", ""), ""])

    # ──── 17. Term & Termination ───────────────────────────────────
    sn += 1
    lines.extend([f"## {sn}. Term & Termination", "", SOW_DEFAULTS.get("termination", ""), ""])
    if handoff.sla_penalties:
        lines.append("**SLA / penalty clauses identified in intake (route to legal):**")
        lines.append("")
        for s in handoff.sla_penalties[:8]:
            snip = (s.get("snippet") or "").replace("|", "\\|")[:200]
            lines.append(f"- {s.get('kind','')}: {snip} _(source: `{s.get('source','')}`)_")
        lines.append("")

    # ──── 18. Force Majeure ────────────────────────────────────────
    sn += 1
    lines.extend([f"## {sn}. Force Majeure", "", SOW_DEFAULTS.get("force_majeure", ""), ""])

    # ──── 19. Governing Law ────────────────────────────────────────
    sn += 1
    lines.extend([
        f"## {sn}. Governing Law", "",
        "| Field | Value |",
        "|---|---|",
        "| Governing law (state / country) | `[FILL: STATE / COUNTRY]` |",
        "| Exclusive venue (court / city) | `[FILL: VENUE]` |",
        "| Conflict-of-laws carve-out | Without regard to its conflict-of-laws principles |",
        "",
        "This SOW is governed by and construed under the laws of the jurisdiction stated above, without regard to its conflict-of-laws principles. Any dispute is resolved exclusively in the named venue.",
        "",
        "_PM action: replace the two `[FILL: …]` fields with the customer-mandated jurisdiction OR the provider's default per the master agreement._",
        "",
    ])

    # ──── 20. Stakeholders & Points of Contact ─────────────────────
    sn += 1
    lines.extend([f"## {sn}. Stakeholders & Points of Contact", ""])
    contacts = _collect_stakeholder_table(report)
    if not contacts:
        contacts = [
            {"name": c.get("name", ""), "role": c.get("role", ""), "email": c.get("email", ""), "source": c.get("source", "")}
            for c in (handoff.stakeholder_contacts or [])
        ]
    if contacts:
        lines.extend([
            "| Name | Role | Email |",
            "|---|---|---|",
        ])
        for c in contacts:
            lines.append(
                f"| {c.get('name','')} | {c.get('role','') or '[TBD]'} | "
                f"{c.get('email','') or '[TBD]'} |"
            )
    else:
        lines.append("- [TBD] PM to list customer and provider points of contact.")
    lines.append("")

    # ──── 21. Signatures ───────────────────────────────────────────
    sn += 1
    lines.extend([
        f"## {sn}. Signatures",
        "",
        "By executing below, each party acknowledges acceptance of the scope, schedule, pricing, and terms in this SOW.",
        "",
        "### Customer",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Authorized signatory (printed name) | ________________________ |",
        f"| Title | ________________________ |",
        f"| Date | ________________________ |",
        f"| Signature | ________________________ |",
        "",
        "### Provider",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Authorized signatory (printed name) | ________________________ |",
        f"| Title | ________________________ |",
        f"| Date | ________________________ |",
        f"| Signature | ________________________ |",
        "",
        "---",
        "",
        f"_End of Statement of Work — {case_pretty} — auto-generated draft v0.1 ({today})._",
        "",
    ])

    return "\n".join(lines).rstrip() + "\n"
