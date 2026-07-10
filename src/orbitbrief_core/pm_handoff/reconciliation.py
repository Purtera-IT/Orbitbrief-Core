"""A5 + B2 + B5: Cross-document reconciliation, risk register, schedule.

A5 (cross-doc reconciliation) — money / date mention tables and
near-value flags built from atom entity_keys.

B2 (risk register) — atom_type=``risk`` rows projected into a
PM-ready table using parser-os's ``structured.canonical_cells``
fields (risk_id, description, likelihood, impact, mitigation,
owner). One row per risk atom; no LLM in the loop.

B5 (Gantt) — atom_type=``schedule_phase`` rows projected into a
mermaid Gantt block + a fallback markdown table. Reads
``structured`` start / end / phase_name fields.


The PM handoff is the place where the buyer (and the SA) need to
see *every* dollar amount and *every* date that appears in the
intake package, with the file it came from. A typical managed
services deal has a dozen money values and a dozen dates spread
across the SOW, vendor quote, schedule, deal-overview brief, and
contracting packet — and they don't always agree.

What this module produces:

* A list of ``MoneyMention`` records, one per money value seen
  anywhere in the envelope, with the files that mention it and a
  short text snippet for each mention. Values are grouped by the
  canonical ``money:<integer>`` entity_key parser-os emits.

* A list of ``DateMention`` records, same shape, keyed on
  ``date:<YYYY-MM-DD>``.

* A list of ``ReconciliationFlag`` records, one per money group
  whose values are *suspiciously close* (within 25% of each other
  but not equal) and appear on different docs. Two documents
  saying "$1,800,000" and "$1,847,250" gets flagged; "$995" and
  "$1,847,250" does not.

The intent is PM-actionable: the table answers "do all the docs
agree on the contract value?" without an LLM in the loop. Values
come straight from parser-os atoms; no inference, no re-parsing.

This module is pure — give it an inspection report dict, get
records back. The markdown renderer in render_markdown.py wires
the records into PM_HANDOFF.md.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MoneyMention:
    """One money value as it appears across the intake package."""

    value: int  # canonical integer value (cents dropped — parser-os emits whole-dollar atoms)
    display: str  # human-friendly: "$1,847,250"
    sources: list[dict[str, str]] = field(default_factory=list)  # [{filename, snippet}]


@dataclass(frozen=True)
class DateMention:
    """One date as it appears across the intake package."""

    iso: str  # canonical YYYY-MM-DD
    sources: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class ReconciliationFlag:
    """A money / date group that probably needs PM attention.

    Two scenarios:
    * ``kind="money_near"`` — two money values are suspiciously
      close (within 25%) and appear on different documents. Could
      be a "total $1.8M" vs "total $1,847,250" mismatch.
    * ``kind="date_role_conflict"`` — two different dates appear
      with the same surrounding role word (e.g. "go-live"). Future
      work — not emitted in v1.
    """

    kind: str
    label: str
    values: list[dict[str, Any]]  # [{display, sources:[...]}, ...]


_MAX_SNIPPET = 160


def _short(text: str) -> str:
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= _MAX_SNIPPET:
        return text
    return text[: _MAX_SNIPPET - 1] + "…"


def _display_money(value: int) -> str:
    return f"${value:,}"


def _iter_atoms_with_files(report: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
    """Yield (atom_dict, filename) for every atom in the report.

    The inspection report nests atoms under each artifact. We
    flatten so the reconciliation pass sees the file each atom
    came from in a single sweep.
    """
    out: list[tuple[dict[str, Any], str]] = []
    for art in report.get("artifacts") or []:
        filename = str(art.get("filename") or art.get("artifact_id") or "unknown")
        for atom in art.get("atoms") or []:
            out.append((atom, filename))
    return out


def build_money_mentions(report: dict[str, Any]) -> list[MoneyMention]:
    """Group every money entity_key across the envelope by value.

    Returns the list sorted by value descending so the largest
    amounts (which are usually the contract / project total)
    appear first in the PM_HANDOFF table.
    """
    by_value: dict[int, list[dict[str, str]]] = defaultdict(list)
    for atom, filename in _iter_atoms_with_files(report):
        for key in atom.get("entity_keys") or ():
            if not isinstance(key, str) or not key.startswith("money:"):
                continue
            raw = key.split(":", 1)[1]
            try:
                value = int(raw)
            except (TypeError, ValueError):
                continue
            if value <= 0:
                continue
            by_value[value].append({
                "filename": filename,
                "snippet": _short(atom.get("text") or ""),
            })

    mentions: list[MoneyMention] = []
    for value in sorted(by_value, reverse=True):
        # De-dupe sources by (filename, snippet) so a row repeated
        # via two cell references doesn't clutter the table.
        seen: set[tuple[str, str]] = set()
        deduped: list[dict[str, str]] = []
        for src in by_value[value]:
            key = (src["filename"], src["snippet"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(src)
        mentions.append(MoneyMention(value=value, display=_display_money(value), sources=deduped))
    return mentions


def build_date_mentions(report: dict[str, Any]) -> list[DateMention]:
    """Group every date entity_key across the envelope by ISO date."""
    by_date: dict[str, list[dict[str, str]]] = defaultdict(list)
    for atom, filename in _iter_atoms_with_files(report):
        for key in atom.get("entity_keys") or ():
            if not isinstance(key, str) or not key.startswith("date:"):
                continue
            iso = key.split(":", 1)[1]
            if len(iso) < 8:  # smoke: skip obviously malformed dates
                continue
            by_date[iso].append({
                "filename": filename,
                "snippet": _short(atom.get("text") or ""),
            })

    mentions: list[DateMention] = []
    for iso in sorted(by_date):
        seen: set[tuple[str, str]] = set()
        deduped: list[dict[str, str]] = []
        for src in by_date[iso]:
            key = (src["filename"], src["snippet"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(src)
        mentions.append(DateMention(iso=iso, sources=deduped))
    return mentions


def build_reconciliation_flags(
    money_mentions: list[MoneyMention],
    *,
    near_window: float = 0.25,
    min_value: int = 10_000,
) -> list[ReconciliationFlag]:
    """Flag money values that are suspiciously close but not equal.

    Two money values trigger a flag when:
      * both are >= ``min_value`` (default $10,000 — skip the noise
        of line-item unit prices),
      * their relative difference is within ``near_window`` (default
        25%) but they are NOT equal,
      * AND each appears on at least one document. (Same-file
        echoes don't count — those usually mean "$1.8M (rounded)
        elsewhere on the same page".)
    """
    candidates = [m for m in money_mentions if m.value >= min_value and m.sources]
    flags: list[ReconciliationFlag] = []
    seen_pairs: set[tuple[int, int]] = set()
    for i, a in enumerate(candidates):
        for b in candidates[i + 1 :]:
            if a.value == b.value:
                continue
            pair_key = (min(a.value, b.value), max(a.value, b.value))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            larger = max(a.value, b.value)
            diff = abs(a.value - b.value) / larger
            if diff > near_window:
                continue
            files_a = {s["filename"] for s in a.sources}
            files_b = {s["filename"] for s in b.sources}
            # Require evidence in at least two distinct files between
            # the pair so a single-file rounding ("$1.85M ≈ $1,847,250")
            # doesn't become a PM action item.
            if len(files_a | files_b) < 2:
                continue
            flags.append(
                ReconciliationFlag(
                    kind="money_near",
                    label=f"{a.display} vs {b.display} ({diff * 100:.0f}% delta)",
                    values=[
                        {"display": a.display, "sources": list(a.sources)},
                        {"display": b.display, "sources": list(b.sources)},
                    ],
                )
            )
    return flags


# ────────────────────────────── B2 risk register ──────────────────────────────


@dataclass(frozen=True)
class RiskRow:
    """One row in the PM-ready risk register.

    Pulled directly from atoms with ``atom_type == 'risk'`` and
    their ``structured.canonical_cells`` fields. No LLM, no
    inference — the values are what the parser extracted from the
    source spreadsheet / document.
    """

    risk_id: str
    description: str
    likelihood: str
    impact: str
    mitigation: str
    owner: str
    sites: list[str] = field(default_factory=list)  # canonical site keys (atl_hq, ...)
    source: str = ""  # filename the row was parsed from


_LIKELIHOOD_RANK = {"high": 3, "medium": 2, "med": 2, "low": 1}
_IMPACT_RANK = _LIKELIHOOD_RANK


def _risk_priority(likelihood: str, impact: str) -> int:
    """High = 9, Med/Med = 4, Low/Low = 1. Used to sort the register."""
    li = _LIKELIHOOD_RANK.get((likelihood or "").strip().lower(), 0)
    im = _IMPACT_RANK.get((impact or "").strip().lower(), 0)
    return li * im


def build_risk_register(report: dict[str, Any]) -> list[RiskRow]:
    """Project every ``atom_type == 'risk'`` atom into a register row.

    Sort order: priority desc (Likelihood × Impact), then risk_id.
    """
    rows: list[RiskRow] = []
    for atom, filename in _iter_atoms_with_files(report):
        if atom.get("atom_type") != "risk":
            continue
        structured = atom.get("structured") or {}
        cells = structured.get("canonical_cells") or {}
        # Sites the risk touches: read ``site:*`` entity_keys.
        sites = sorted(
            {
                k.split(":", 1)[1]
                for k in atom.get("entity_keys") or ()
                if isinstance(k, str) and k.startswith("site:")
            }
        )
        rows.append(
            RiskRow(
                risk_id=str(cells.get("risk_id") or ""),
                description=str(cells.get("description") or "")[:300],
                likelihood=str(cells.get("likelihood") or ""),
                impact=str(cells.get("impact") or ""),
                mitigation=str(cells.get("mitigation") or "")[:280],
                owner=str(cells.get("owner") or ""),
                sites=sites,
                source=filename,
            )
        )
    rows.sort(
        key=lambda r: (-_risk_priority(r.likelihood, r.impact), r.risk_id or "zz"),
    )
    return rows


# ────────────────────────────── B4 stakeholder one-pagers ──────────────────────────────


@dataclass(frozen=True)
class StakeholderPager:
    """One stakeholder-shaped view of the intake package.

    "Stakeholder" here means a role lens (CFO, IT, Procurement),
    not a literal person. Each lens picks the slice of atoms /
    risks / gaps a stakeholder in that role would care about,
    plus the headline numbers from the money table.

    Three default lenses ship in v1; future lenses can be added
    by registering a (label, predicate) pair in the builder.
    """

    role: str  # "cfo" / "it" / "procurement"
    title: str  # human-friendly "Chief Financial Officer"
    summary_lines: list[str] = field(default_factory=list)
    money_lines: list[str] = field(default_factory=list)
    risk_lines: list[str] = field(default_factory=list)
    action_lines: list[str] = field(default_factory=list)


# Keyword patterns that identify a risk / gap / action as relevant
# to each lens. These are intentionally broad — better to over-include
# (PM can ignore) than miss something the stakeholder needs.
_LENS_KEYWORDS: dict[str, tuple[str, ...]] = {
    "cfo": (
        "budget", "cost", "price", "approval", "cfo", "finance", "commercial",
        "procurement", "pricing", "payment", "invoice", "discount", "po", "vendor",
        "contract value", "total", "subtotal", "tax", "freight", "logistics",
    ),
    "it": (
        "circuit", "carrier", "vlan", "ip", "wireless", "wi-fi", "wifi",
        "switch", "router", "ap ", "access point", "cabling", "rack",
        "security", "camera", "vms", "compliance", "siem", "firewall",
        "patch", "network", "tls", "vpn", "monitoring",
    ),
    "procurement": (
        "vendor", "lead time", "shipping", "freight", "po", "purchase",
        "rfp", "rfq", "bid", "warranty", "license", "support tier",
        "msrp", "discount", "subscription", "renewal", "logistics",
    ),
}


def _lens_match(text: str, lens: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in _LENS_KEYWORDS.get(lens, ()))


def build_stakeholder_pagers(
    *,
    gaps: list[Any],
    risk_rows: list["RiskRow"],
    money_mentions: list[MoneyMention],
    reconciliation_flags: list[ReconciliationFlag],
    case_id: str,
) -> list[StakeholderPager]:
    """Build one StakeholderPager per default lens.

    Each pager is intentionally short — a single page when
    rendered, focused on the few decisions / numbers / risks the
    stakeholder cares about. v1 ships CFO / IT / Procurement.
    """
    pagers: list[StakeholderPager] = []
    lens_titles = {
        "cfo": "CFO — finance & approvals",
        "it": "IT — technical scope & risk",
        "procurement": "Procurement — vendors & logistics",
    }

    # Shared: top 3 money values become the executive headline.
    top_money = [m.display for m in money_mentions[:3] if m.value >= 10_000]
    headline_money = ", ".join(top_money) if top_money else ""

    for lens in ("cfo", "it", "procurement"):
        title = lens_titles[lens]
        summary: list[str] = []
        if headline_money:
            summary.append(f"Headline figures across the intake: {headline_money}.")

        money_lines: list[str] = []
        if lens == "cfo":
            money_lines = [
                f"- {m.display} — seen in {', '.join(sorted({s['filename'] for s in (m.sources or [])}))}"
                for m in money_mentions[:8]
                if m.value >= 10_000
            ]
            for f in reconciliation_flags:
                money_lines.append(f"- **Reconcile**: {f.label}")

        risk_lines = [
            f"- **{r.risk_id}** ({r.likelihood}/{r.impact}): {r.description} — mitigation: {r.mitigation}"
            for r in risk_rows
            if _lens_match(r.description, lens) or _lens_match(r.mitigation, lens) or lens == "cfo" and "approval" in (r.description + r.mitigation).lower()
        ][:5]

        action_lines: list[str] = []
        for g in gaps:
            # Audit fix: stakeholder pagers must filter parser-os
            # internal correctness questions (Site Reality v5
            # verification, kind=physical_site checks, etc.) — they
            # belong on the SA lane, not in a CFO / IT / Procurement
            # one-pager. Mirror the customer-email filter.
            if _is_internal_gap(g):
                continue
            label = getattr(g, "label", "") or getattr(g, "domain_label", "")
            text = (
                getattr(g, "suggested_open_question", "")
                or getattr(g, "message", "")
            )
            domain = getattr(g, "domain_label", "")
            if (
                _lens_match(label, lens)
                or _lens_match(text, lens)
                or _lens_match(domain, lens)
            ):
                sev = getattr(g, "severity", "")
                sev_prefix = "**[blocker]** " if sev == "blocker" else (
                    "[warning] " if sev == "warning" else ""
                )
                action_lines.append(f"- {sev_prefix}{text}")

        # If no domain-specific items, fall back to a generic note.
        if not risk_lines and not action_lines:
            summary.append("No domain-specific risks or open items were detected for this lens — review the full PM_HANDOFF.")
        pagers.append(
            StakeholderPager(
                role=lens,
                title=title,
                summary_lines=summary,
                money_lines=money_lines,
                risk_lines=risk_lines,
                action_lines=action_lines[:10],
            )
        )
    return pagers


# ────────────────────────────── B8 vendor RFP packet ──────────────────────────────


@dataclass(frozen=True)
class RFPLineItem:
    """One row in a vendor RFP packet.

    Built directly from ``atom_type == 'vendor_line_item'`` atoms
    with their ``structured`` part_number / description / quantity
    / unit_price_raw / lead_time fields. Category is inferred from
    the description so the RFP can be split into vendor-shaped
    sections even when the source BOM has no material_family
    column.
    """

    category: str  # "Network", "AV / Collaboration", "Power", ...
    part_number: str
    description: str
    quantity: int
    unit_price: int  # whole dollars; 0 if missing
    lead_time: str
    notes: str
    source: str


# Description-keyword → category mapping. Generous on purpose —
# better to over-categorize than miss a line item; the PM can
# re-bucket if needed.
_RFP_CATEGORY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Network & Wireless", (
        "access point", "wi-fi", "wifi", "ap ", "switch", "router",
        "firewall", "vpn", "wlan", "vlan", "poe", "patch panel",
    )),
    ("AV / Collaboration", (
        "video bar", "video conferencing", "camera", "microphone",
        "speaker", "soundbar", "monitor", "display", "signage",
        "scheduling panel", "interactive panel", "huddle",
    )),
    ("Power & Environmentals", (
        "ups", "uninterruptible", "pdu", "battery", "power",
        "rack", "cooling", "hvac",
    )),
    ("Endpoints / IT Devices", (
        "tablet", "laptop", "desktop", "workstation", "printer",
        "label printer", "scanner", "barcode", "rugged",
    )),
    ("Structured Cabling", (
        "cable", "fiber", "patch", "jack", "tray", "raceway",
        "conduit", "j-hook",
    )),
    ("Security / Surveillance", (
        "ip camera", "vms", "access control", "badge reader",
        "intrusion", "alarm", "intercom",
    )),
    ("Services & Labor", (
        "installation", "training", "discovery", "design",
        "project management", "support", "adoption", "labor",
        "after-hours", "weekend",
    )),
)


def _categorize_line_item(description: str) -> str:
    d = (description or "").lower()
    for category, keywords in _RFP_CATEGORY_KEYWORDS:
        if any(k in d for k in keywords):
            return category
    return "Miscellaneous"


def build_rfp_line_items(report: dict[str, Any]) -> list[RFPLineItem]:
    """Project every ``vendor_line_item`` atom into an RFP row.

    Items without a description AND without a part_number are
    dropped — they're usually placeholder rows in the BOM (blank
    services line, header row, etc.).
    """
    out: list[RFPLineItem] = []
    for atom, filename in _iter_atoms_with_files(report):
        if atom.get("atom_type") != "vendor_line_item":
            continue
        s = atom.get("structured") or {}
        if not isinstance(s, dict):
            continue
        description = str(s.get("description") or "")
        part_number = str(s.get("part_number") or "")
        if not description and not part_number:
            continue
        try:
            qty = int(float(s.get("quantity") or 0))
        except (ValueError, TypeError):
            qty = 0
        try:
            unit_price = int(float(str(s.get("unit_price_raw") or 0).replace(",", "")))
        except (ValueError, TypeError):
            unit_price = 0
        category = _categorize_line_item(description)
        out.append(
            RFPLineItem(
                category=category,
                part_number=part_number,
                description=description[:200],
                quantity=qty,
                unit_price=unit_price,
                lead_time=str(s.get("lead_time") or "")[:60],
                notes=str(s.get("notes") or "")[:160],
                source=filename,
            )
        )
    return out


# ────────────────────────────── B9 acceptance checklist ──────────────────────────────


@dataclass(frozen=True)
class AcceptanceCheck:
    """One acceptance-criterion line for the PM checklist.

    Pulled from schedule-row atoms whose ``canonical_cells`` carry
    an ``exit_criteria`` / ``acceptance_criteria`` field, and from
    cutover-checklist rows whose canonical_cells include a
    ``checklist_item`` + ``evidence_required`` pair. Rendered as
    a checkbox list with owner + evidence-needed columns so the
    PM can hand the block to the field team for execution.
    """

    phase_or_step: str  # e.g. "Procurement and staging" or "Step 3"
    criterion: str
    owner: str = ""
    evidence_required: str = ""
    timing: str = ""  # cutover-checklist timing label ("Day-of", "Closeout", ...)
    source: str = ""


def build_acceptance_checks(report: dict[str, Any]) -> list[AcceptanceCheck]:
    """Walk atoms for both schedule exit_criteria + cutover checklist rows."""
    out: list[AcceptanceCheck] = []
    seen: set[tuple[str, str]] = set()
    for atom, filename in _iter_atoms_with_files(report):
        structured = atom.get("structured") or {}
        if not isinstance(structured, dict):
            continue
        cells = structured.get("canonical_cells") or structured.get("cells") or {}
        if not isinstance(cells, dict):
            continue
        # Path 1: schedule rows with exit_criteria
        exit_crit = (
            cells.get("exit_criteria")
            or cells.get("Exit Criteria")
            or cells.get("acceptance_criteria")
            or cells.get("Acceptance Criteria")
        )
        if exit_crit:
            phase = str(
                cells.get("name")
                or cells.get("Name")
                or cells.get("phase")
                or cells.get("Phase")
                or ""
            )
            owner = str(cells.get("owner") or cells.get("Owner") or "")
            key = (phase, str(exit_crit)[:200])
            if key not in seen:
                seen.add(key)
                out.append(
                    AcceptanceCheck(
                        phase_or_step=phase or "Schedule",
                        criterion=str(exit_crit)[:280],
                        owner=owner,
                        source=filename,
                    )
                )
        # Path 2: cutover checklist rows with checklist_item + evidence_required
        checklist = (
            cells.get("checklist_item")
            or cells.get("Checklist Item")
            or cells.get("task")
            or cells.get("Task")
        )
        if checklist:
            step = str(
                cells.get("step")
                or cells.get("Step")
                or cells.get("order")
                or ""
            )
            timing = str(cells.get("timing") or cells.get("Timing") or "")
            evidence = str(
                cells.get("evidence_required")
                or cells.get("Evidence Required")
                or ""
            )
            owner = str(cells.get("owner") or cells.get("Owner") or "")
            key = (f"step_{step}_{checklist[:60]}", filename)
            if key not in seen:
                seen.add(key)
                out.append(
                    AcceptanceCheck(
                        phase_or_step=(
                            f"Step {step}" if step else "Cutover"
                        ),
                        criterion=str(checklist)[:280],
                        owner=owner,
                        evidence_required=evidence[:240],
                        timing=timing,
                        source=filename,
                    )
                )
    return out


# ────────────────────────────── PM-audit gap fillers ──────────────────────────────


@dataclass(frozen=True)
class StakeholderContact:
    """One row in the stakeholder contact directory.

    Pulled from atoms whose structured cells expose name + role +
    email-or-phone. Bare role-context name extractions (the
    ``stakeholder:*`` entity_keys) are emitted as rows even
    without email/phone; the PM sees "TBD" in those columns.
    """

    name: str
    role: str = ""
    email: str = ""
    phone: str = ""
    site: str = ""  # canonical site key when the row binds to a site
    source: str = ""


_EMAIL_RE = __import__("re").compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Phone pattern — require either a country-code prefix (+1, +44) or
# a standard 3-3-4 / (NNN) NNN-NNNN shape so we don't match ISO
# dates ("2026-07-27") or part numbers as phones.
_PHONE_RE = __import__("re").compile(
    r"(?:\+\d{1,3}[\s\-\.]?)?"
    r"(?:\(\d{3}\)[\s\-]?|\d{3}[\s\-\.])"
    r"\d{3}[\s\-\.]\d{4}"
)


def _proximity_email_for_name(text: str, name: str) -> str:
    """Return the email closest to a name occurrence in text, or empty.

    Prevents pairing every name in a roster paragraph with the FIRST
    email — the directory would otherwise list 5 stakeholders all
    sharing one email address. Returns empty when no email is within
    ±80 chars of a name occurrence.
    """
    import re as _re
    name_re = _re.compile(_re.escape(name), _re.IGNORECASE)
    name_spans = [(m.start(), m.end()) for m in name_re.finditer(text)]
    if not name_spans:
        return ""
    emails = list(_EMAIL_RE.finditer(text))
    if not emails:
        return ""
    best_email = ""
    best_dist = 80  # max ±80 chars
    for n_start, n_end in name_spans:
        for em in emails:
            mid = (em.start() + em.end()) // 2
            dist = min(abs(mid - n_start), abs(mid - n_end))
            if dist < best_dist:
                best_dist = dist
                best_email = em.group(0)
    return best_email


def build_stakeholder_contacts(report: dict[str, Any]) -> list[StakeholderContact]:
    """Walk atoms for name + role + email/phone rosters.

    Three paths:
      1. Structured roster rows where canonical_cells carry the
         four fields directly. Highest-fidelity path.
      2. Free-text pipe-separated roster: ``Name | Title | Email
         | Role | ...``. Common pattern in DOCX exec briefs.
      3. Free-text atoms where a stakeholder name appears near
         an email / phone pattern. Uses proximity matching.
    """
    out: list[StakeholderContact] = []
    seen: set[str] = set()  # name_norm dedup across the whole project

    # Path 2: pipe-separated roster rows. Detect blocks of text
    # where lines/segments match ``Name | Title | email@domain | ...``.
    import re as _re
    pipe_roster_re = _re.compile(
        r"([A-Z][\w\-']+(?:\s+[A-Z][\w\-']+){1,3})"
        r"\s*\|\s*"
        r"([A-Z][\w\s,\-/&]+?)"
        r"\s*\|\s*"
        r"([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})"
    )
    for atom, filename in _iter_atoms_with_files(report):
        text = atom.get("text") or ""
        if "|" not in text or "@" not in text:
            continue
        for m in pipe_roster_re.finditer(text):
            name = m.group(1).strip()
            role = m.group(2).strip()[:80]
            email = m.group(3).strip()
            name_norm = name.lower().strip()
            if name_norm in seen:
                continue
            seen.add(name_norm)
            out.append(StakeholderContact(
                name=name,
                role=role,
                email=email,
                phone="",
                source=filename,
            ))

    for atom, filename in _iter_atoms_with_files(report):
        structured = atom.get("structured") or {}
        if isinstance(structured, dict):
            cells = structured.get("canonical_cells") or structured.get("cells") or {}
            if isinstance(cells, dict):
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
                email = cells.get("email") or cells.get("Email") or ""
                phone = cells.get("phone") or cells.get("Phone") or ""
                if name and (role or email or phone):
                    name_norm = str(name).lower().strip()
                    if name_norm not in seen:
                        seen.add(name_norm)
                        out.append(
                            StakeholderContact(
                                name=str(name).strip(),
                                role=str(role).strip(),
                                email=str(email).strip(),
                                phone=str(phone).strip(),
                                source=filename,
                            )
                        )
                        continue

        # Free-text path — match emails / phones in atom text and
        # pair with the NEAREST stakeholder name (not just any).
        text = atom.get("text") or ""
        if not (_EMAIL_RE.search(text) or _PHONE_RE.search(text)):
            continue
        stakeholders = [
            k.split(":", 1)[1].replace("_", " ").title()
            for k in atom.get("entity_keys") or ()
            if isinstance(k, str) and k.startswith("stakeholder:")
        ]
        for name in stakeholders:
            name_norm = name.lower().strip()
            if name_norm in seen:
                continue
            # Proximity-paired email for THIS name; skip if no
            # email within ±80 chars (avoids the all-share-one-email
            # bug).
            email = _proximity_email_for_name(text, name)
            phones_found = _PHONE_RE.findall(text)
            if not email and not phones_found:
                continue
            seen.add(name_norm)
            out.append(
                StakeholderContact(
                    name=name,
                    role="",
                    email=email,
                    phone=phones_found[0] if phones_found else "",
                    source=filename,
                )
            )
    out.sort(key=lambda c: (c.name, c.source))
    return out


@dataclass(frozen=True)
class ExclusionItem:
    """One out-of-scope item the PM should escalate if the customer
    expects it.

    Pulled from atoms with ``atom_type == 'exclusion'``. Surfacing
    these at the top of PM_HANDOFF (in addition to SOW_DRAFT)
    means the PM can spot-check exclusions during customer
    review without scrolling to the SOW.
    """

    text: str
    source: str = ""


def build_exclusions(report: dict[str, Any]) -> list[ExclusionItem]:
    out: list[ExclusionItem] = []
    seen: set[str] = set()
    for atom, filename in _iter_atoms_with_files(report):
        if atom.get("atom_type") != "exclusion":
            continue
        text = (atom.get("text") or "").strip()
        if not text:
            continue
        norm = text[:160].lower()
        if norm in seen:
            continue
        seen.add(norm)
        out.append(ExclusionItem(text=text[:300], source=filename))
    return out


@dataclass(frozen=True)
class ResponsibilityItem:
    """One customer-supplied OR provider-supplied responsibility.

    Built from atoms whose text matches a customer-responsibility
    pattern ("customer to provide", "customer supplies", "OPTBOT
    will provide") or a provider-side pattern ("we will provide",
    "provider supplies").

    These atoms exist as scope_item / customer_instruction today;
    we surface them in a dedicated section so the PM can verify
    each side's commitments without reading through every scope
    bullet.
    """

    party: str  # "customer" / "provider"
    text: str
    source: str = ""


_CUSTOMER_RESP_RE = __import__("re").compile(
    r"\b(customer|client|"
    r"OPTBOT|the (?:customer|client|company|organization))\s+"
    r"(?:will|shall|to|must|is responsible for|provides?|supplies)\b",
    __import__("re").IGNORECASE,
)
_PROVIDER_RESP_RE = __import__("re").compile(
    r"\b(?:we|provider|vendor|contractor|the (?:provider|vendor|contractor))\s+"
    r"(?:will|shall|to|provides?|supplies|are responsible for)\b",
    __import__("re").IGNORECASE,
)


def build_responsibilities(report: dict[str, Any]) -> list[ResponsibilityItem]:
    out: list[ResponsibilityItem] = []
    seen: set[tuple[str, str]] = set()
    for atom, filename in _iter_atoms_with_files(report):
        atype = atom.get("atom_type") or ""
        if atype not in {"scope_item", "customer_instruction", "constraint", "assumption"}:
            continue
        text = (atom.get("text") or "").strip()
        if not text:
            continue
        is_customer = _CUSTOMER_RESP_RE.search(text)
        is_provider = _PROVIDER_RESP_RE.search(text)
        if not (is_customer or is_provider):
            continue
        party = "customer" if is_customer else "provider"
        norm = (party, text[:160].lower())
        if norm in seen:
            continue
        seen.add(norm)
        out.append(ResponsibilityItem(party=party, text=text[:300], source=filename))
    return out


@dataclass(frozen=True)
class QuantityClaim:
    """One numeric quantity claim about a device / service / scope.

    Built from atoms that include a ``device:*`` or ``part:*``
    entity_key alongside a quantity. PM uses the resulting table
    to spot quantity contradictions across documents (the
    A5-equivalent for hardware counts: "94 APs in one doc, 92 in
    another").
    """

    target: str  # canonical device/part slug
    quantity: int
    snippet: str
    source: str = ""


def build_quantity_claims(report: dict[str, Any]) -> list[QuantityClaim]:
    """Pull (device or part, quantity) from atoms with both signals."""
    import re as _re
    qty_re = _re.compile(r"\b(\d{1,5})\s+units?\b|\b(\d{1,5})\s*x\s*\$", _re.IGNORECASE)
    out: list[QuantityClaim] = []
    seen: set[tuple[str, int, str]] = set()
    for atom, filename in _iter_atoms_with_files(report):
        text = atom.get("text") or ""
        if not text:
            continue
        # Find device/part keys on this atom
        targets = [
            k.split(":", 1)[1]
            for k in atom.get("entity_keys") or ()
            if isinstance(k, str) and (k.startswith("device:") or k.startswith("part:"))
        ]
        if not targets:
            continue
        # Find quantities in the text
        for m in qty_re.finditer(text):
            raw = m.group(1) or m.group(2)
            if not raw:
                continue
            try:
                qty = int(raw)
            except ValueError:
                continue
            if qty <= 0 or qty > 50_000:
                continue
            # Use the first matching target as the comparison key
            target = targets[0]
            key = (target, qty, filename)
            if key in seen:
                continue
            seen.add(key)
            snippet = text[max(0, m.start() - 30):m.end() + 60].strip()
            out.append(
                QuantityClaim(
                    target=target,
                    quantity=qty,
                    snippet=snippet[:200],
                    source=filename,
                )
            )
    # Sort by target so contradictions cluster.
    out.sort(key=lambda q: (q.target, q.source))
    return out


def find_quantity_contradictions(
    claims: list[QuantityClaim],
) -> list[dict[str, Any]]:
    """Group QuantityClaims by target; flag groups with > 1 distinct
    quantity across different source files.

    Mirrors the money reconciliation: the PM needs to see when
    two documents disagree on how many APs / cameras / switches
    a project ships.
    """
    by_target: dict[str, list[QuantityClaim]] = defaultdict(list)
    for c in claims:
        by_target[c.target].append(c)
    out: list[dict[str, Any]] = []
    for target, group in sorted(by_target.items()):
        qtys = {c.quantity for c in group}
        if len(qtys) < 2:
            continue
        files = sorted({c.source for c in group})
        if len(files) < 2:
            continue
        out.append({
            "target": target,
            "values": sorted(qtys),
            "files": files,
            "examples": [
                {"qty": c.quantity, "source": c.source, "snippet": c.snippet}
                for c in group[:6]
            ],
        })
    return out


@dataclass(frozen=True)
class ExecutiveSummary:
    """One-paragraph executive brief for the very top of PM_HANDOFF.

    Built deterministically from the handoff fields: headline
    money + sites + dominant workstream + critical blocker count.
    No LLM in the loop. PM should be able to read this in 10
    seconds and know what they're looking at.
    """

    headline: str
    health_line: str
    next_action: str


def build_executive_summary(
    *,
    case_id: str,
    status: str,
    status_label: str,
    one_line_summary: str,
    money_mentions: list[MoneyMention],
    risks: list["RiskRow"],
    gaps: list[Any],
    sites: list[Any],
    domains: list[Any],
) -> ExecutiveSummary:
    """Compose the 3-line executive summary from PM-handoff fields."""
    top_money = next(
        (m.display for m in money_mentions if m.value >= 100_000),
        None,
    )
    site_count = sum(1 for s in sites if getattr(s, "publishable", False))
    blocker_count = sum(1 for g in gaps if getattr(g, "severity", "") == "blocker")
    warning_count = sum(1 for g in gaps if getattr(g, "severity", "") == "warning")
    high_risks = sum(
        1
        for r in risks
        if (r.likelihood.lower(), r.impact.lower())
        in {("high", "high"), ("high", "medium"), ("medium", "high")}
    )
    workstreams = [d.label for d in domains if getattr(d, "active_for_sow", False)]

    deal_value = f" worth {top_money}" if top_money else ""
    site_phrase = f"{site_count} confirmed site(s)" if site_count else "no confirmed sites yet"
    workstream_phrase = (
        f" covering {', '.join(workstreams[:3])}" if workstreams else ""
    )
    headline = (
        f"**{case_id}**: deal{deal_value} across {site_phrase}{workstream_phrase}."
    )

    if status == "red":
        health = (
            f"Status is **RED**: {blocker_count} blocker(s) and "
            f"{warning_count} warning(s) need PM resolution before SOW lock."
        )
        next_action = (
            "Resolve the blocker checklist below and confirm the customer "
            "clarifications email starter. Do not publish a SOW until blockers clear."
        )
    elif status == "yellow":
        health = (
            f"Status is **YELLOW**: {warning_count} warning(s) need PM review. "
            f"{high_risks} high-priority risk(s) tracked in the register."
        )
        next_action = (
            "Walk the warnings checklist below, then proceed to SOW drafting "
            "with the auto-generated SOW_DRAFT.md as the starting point."
        )
    else:
        health = (
            f"Status is **GREEN**: intake is clean against the current "
            f"rulebook. {high_risks} high-priority risk(s) being tracked."
        )
        next_action = (
            "Proceed to SOW drafting. Use SOW_DRAFT.md as the starting "
            "point and confirm pricing + signatures before customer review."
        )

    return ExecutiveSummary(
        headline=headline,
        health_line=health,
        next_action=next_action,
    )


# ────────────────────────────── B10 compliance callouts ──────────────────────────────


@dataclass(frozen=True)
class ComplianceCallout:
    """One compliance/legal flag the PM should route to legal review.

    Pulled from atoms that mention named frameworks (SOC2, ISO 27001,
    HIPAA, PCI-DSS, GDPR, CCPA, NIST, FedRAMP, FERPA, ...) or generic
    legal/compliance language (warranty, indemnification, audit).
    The callout carries the atom's text snippet + source file so
    legal review can verify the language verbatim.
    """

    framework: str  # canonical framework name e.g. "SOC 2", "HIPAA", "Legal review"
    snippet: str
    source: str
    severity: str = "info"  # "blocker" if from a blocker gap, else "info"


# Compliance frameworks we name-match against. Each entry maps a
# canonical display name to a list of regex-ready aliases. We match
# case-insensitively and require word boundaries so "soc" doesn't
# false-match inside "socket".
_COMPLIANCE_FRAMEWORKS: dict[str, tuple[str, ...]] = {
    "SOC 2": (r"\bSOC\s?2\b", r"\bSOC-?II\b"),
    "ISO 27001": (r"\bISO\s?27001\b", r"\bISO\s?27002\b"),
    "ISO 9001": (r"\bISO\s?9001\b",),
    "HIPAA": (r"\bHIPAA\b", r"\bPHI\b\s+(?:data|disclosure|handling)"),
    "PCI-DSS": (r"\bPCI[\s\-]?DSS\b", r"\bPCI\s+compliant\b"),
    "GDPR": (r"\bGDPR\b", r"\bgeneral data protection\b"),
    "CCPA / CPRA": (r"\bCCPA\b", r"\bCPRA\b"),
    "NIST 800-53 / CSF": (r"\bNIST\s?800-?53\b", r"\bNIST\s?CSF\b", r"\bNIST\s?cybersecurity framework\b"),
    "FedRAMP": (r"\bFedRAMP\b",),
    "FERPA": (r"\bFERPA\b",),
    "HITRUST": (r"\bHITRUST\b",),
    "SOX (Sarbanes-Oxley)": (r"\bSOX\b", r"\bSarbanes[\s\-]?Oxley\b"),
    "CMMC": (r"\bCMMC\b",),
    "Indemnification": (r"\bindemnif(?:y|ication|ies|ied)\b",),
    "Warranty": (r"\bwarrant(?:y|ies|ed)\b",),
    "Audit rights": (r"\baudit(?:s|ing)?\s+(?:rights|clause|requirement|obligation)?\b",),
    "Insurance": (r"\b(?:cyber\s+)?insurance\b", r"\bliability\s+coverage\b"),
    "Data residency": (r"\bdata\s+residency\b", r"\bdata\s+sovereignty\b"),
    "Right to terminate": (r"\bright\s+to\s+terminat(?:e|ion)\b",),
    "Force majeure": (r"\bforce\s+majeure\b",),
    "Confidentiality / NDA": (r"\bNDA\b", r"\bnon-?disclosure\b", r"\bconfidentiality\s+(?:agreement|clause|obligation)\b"),
    "MSA / Master agreement": (r"\bMSA\b", r"\bmaster\s+services?\s+agreement\b"),
    "Legal review required": (r"\blegal\s+review\b", r"\blegal\s+approval\b", r"\blegal\s+sign-?off\b"),
}

# Atoms we consider candidates for compliance callouts. Skip atom
# types that are unlikely to carry contract language (e.g. quantity,
# entity-only, action_item).
_COMPLIANCE_ATOM_TYPES: frozenset[str] = frozenset({
    "constraint", "exclusion", "scope_item", "decision",
    "assumption", "customer_instruction",
})


def build_compliance_callouts(report: dict[str, Any]) -> list[ComplianceCallout]:
    """Scan atoms for named compliance frameworks + generic legal cues.

    Returns one ``ComplianceCallout`` per framework × atom hit.
    De-duplicated by (framework, snippet) so an exact quote
    appearing in two atoms only surfaces once.
    """
    seen: set[tuple[str, str]] = set()
    out: list[ComplianceCallout] = []
    import re as _re
    compiled = {
        name: [_re.compile(p, _re.IGNORECASE) for p in patterns]
        for name, patterns in _COMPLIANCE_FRAMEWORKS.items()
    }
    for atom, filename in _iter_atoms_with_files(report):
        if atom.get("atom_type") not in _COMPLIANCE_ATOM_TYPES:
            continue
        text = atom.get("text") or ""
        if not text:
            continue
        for framework, regexes in compiled.items():
            if not any(rx.search(text) for rx in regexes):
                continue
            snippet = text.strip().replace("\n", " ")[:240]
            key = (framework, snippet)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                ComplianceCallout(
                    framework=framework,
                    snippet=snippet,
                    source=filename,
                    severity="info",
                )
            )
    out.sort(key=lambda c: (c.framework, c.source))
    return out


# ────────────────────────────── B3 action items ──────────────────────────────


@dataclass(frozen=True)
class ActionItem:
    """One PM-actionable item with owner + optional due date.

    Built from the union of: gaps, risk-register rows, and
    schedule phases. Each contributes a tracked task the PM can
    drop straight into their PM tool. No LLM, no inference — the
    text comes from the parser-extracted fields.
    """

    kind: str  # "gap" / "risk" / "phase"
    label: str
    owner: str = ""
    due: str = ""  # ISO date when known
    severity: str = ""  # "blocker" / "warning" / "" — only meaningful for gap items


# Parser-os internal correctness questions that should NOT show up in the
# PM action checklist — they are SA / developer concerns ("verify each
# published site cluster carries kind=physical_site...") that leaked into
# the gap list. The customer-email renderer filters these too. Keep the
# two filters in sync.
_INTERNAL_GAP_TOKENS = (
    "verify",
    "synthesis rendering",
    "model is broken",
    "promotion path",
    "site reality v",
    "parser-os",
    "orbitbrief",
    "publish as a physical-site cluster",
    "kind=physical_site",
    "member_atom_ids",
    "artifact_ids",
)


def _is_internal_gap(gap: Any) -> bool:
    text = (
        (getattr(gap, "suggested_open_question", "") or "")
        + " "
        + (getattr(gap, "message", "") or "")
    ).lower()
    return any(token in text for token in _INTERNAL_GAP_TOKENS)


def _normalize_action_label(label: str) -> str:
    """Normalized form used for action-item deduplication.

    Strips leading verb / "Resolve / Confirm / Track / Phase:" prefix,
    collapses whitespace, lowercases. Two action items with the
    same normalized form are considered duplicates and only the
    highest-severity one is kept.
    """
    s = (label or "").lower().strip()
    # Strip leading verb prefixes
    s = re.sub(
        r"^(?:resolve|confirm|track|phase|action|review|verify)"
        r"\s*\([^)]*\)?\s*[:\-]?\s*",
        "",
        s,
    )
    s = re.sub(r"\s+", " ", s)
    return s[:200]


def build_action_items(
    *,
    gaps: list[Any],
    risk_rows: list["RiskRow"],
    schedule_phases: list["SchedulePhase"],
) -> list[ActionItem]:
    """Roll gaps + risks + phases into one PM checklist.

    Ordering: blockers first, then warnings, then risks sorted by
    priority (already pre-sorted in risk_rows), then phases sorted
    by start (already pre-sorted in schedule_phases). Owner=""
    means the PM has to assign the action manually.

    Audit fix: parser-os internal correctness questions (Site
    Reality v5 promotion, "kind=physical_site" verification, etc.)
    are filtered out — they belong on the SA review lane, not in
    the PM's action queue.
    """
    items: list[ActionItem] = []
    for g in gaps:
        sev = getattr(g, "severity", "")
        if sev not in {"blocker", "warning"}:
            continue
        if _is_internal_gap(g):
            continue
        label = getattr(g, "suggested_open_question", "") or getattr(g, "message", "")
        prefix = "Resolve" if sev == "blocker" else "Confirm"
        domain = getattr(g, "domain_label", "")
        full = f"{prefix} ({domain}): {label}" if domain else f"{prefix}: {label}"
        items.append(ActionItem(kind="gap", label=full, severity=sev))
    for r in risk_rows:
        if not r.risk_id:
            continue
        items.append(
            ActionItem(
                kind="risk",
                label=f"Track {r.risk_id} ({r.description}) — mitigation: {r.mitigation}",
                owner=r.owner,
            )
        )
    for p in schedule_phases:
        if not p.start:
            continue
        items.append(
            ActionItem(
                kind="phase",
                label=f"Phase: {p.phase} (kickoff {p.start})",
                owner=p.owner,
                due=p.start,
            )
        )
    # Audit fix: dedup. Same action surfacing via gap + risk + phase
    # would otherwise appear 3 times. Pick the highest-severity copy
    # of each unique action and drop the rest.
    severity_rank = {"blocker": 3, "warning": 2, "info": 1, "": 0}
    by_norm: dict[str, ActionItem] = {}
    for it in items:
        norm = _normalize_action_label(it.label)
        if not norm:
            continue
        existing = by_norm.get(norm)
        if existing is None:
            by_norm[norm] = it
            continue
        # Keep the one with higher severity; tie → keep the first
        if severity_rank.get(it.severity, 0) > severity_rank.get(existing.severity, 0):
            by_norm[norm] = it
    # Preserve insertion order for stable rendering
    seen_norms: set[str] = set()
    out: list[ActionItem] = []
    for it in items:
        norm = _normalize_action_label(it.label)
        if not norm or norm in seen_norms:
            continue
        seen_norms.add(norm)
        out.append(by_norm[norm])
    return out


# ────────────────────────────── B6 polish: per-site $ arithmetic ──────────────────────────────


@dataclass(frozen=True)
class SiteAllocationLine:
    """One line item allocated across sites, with computed per-site cost.

    Built from atoms whose text matches the BOM allocation pattern:

        <device>: <total> units x $<price> | allocated <SITE> <n>, <SITE> <n>, ...

    Each allocation produces one ``SiteAllocationLine`` per site with
    the count, the unit price, and the computed extended cost. The PM
    rollup table groups these by site so totals are visible.
    """

    site: str  # the SITE code as it appeared in the text (e.g. "ATL-HQ")
    device: str  # the line-item description (e.g. "Wi-Fi 7 APs")
    quantity: int
    unit_price: int  # in dollars (no cents — matches money_mentions canonical)
    extended: int  # quantity × unit_price
    source: str = ""  # C3 source-provenance click-through


# Pattern: a device name, then "X units x $Y", then "| allocated SITE n, SITE n, ..."
# We tolerate whitespace, plus signs in device names ("PoE++"), and
# both bare $ and currency-suffixed forms. The unit_price comma
# separators ($6,125) are stripped before parsing.
_ALLOCATION_RE = re.compile(
    r"""
    (?P<device>[A-Za-z][A-Za-z0-9 +\-/]{2,40}?)   # device name (greedy but bounded)
    \s*:\s*
    (?P<total>\d+(?:,\d{3})*)                      # total units
    \s+units?\s*x\s*\$?
    (?P<price>\d+(?:,\d{3})*(?:\.\d+)?)            # unit price
    [^|]*?\|\s*allocated\s+
    (?P<alloc>[A-Z][A-Z0-9\-]+\s+\d+
        (?:\s*,\s*[A-Z][A-Z0-9\-]+\s+\d+)*)        # SITE n[, SITE n]...
    """,
    re.IGNORECASE | re.VERBOSE,
)


def parse_bom_allocations(report: dict[str, Any]) -> list[SiteAllocationLine]:
    """Parse explicit BOM allocation lines into per-site cost rows.

    Only the explicit ``allocated SITE n, SITE n`` shape is parsed
    here — the natural-language "two at HQ, one at Westside" form
    is left for a future revision (it requires resolving HQ to a
    canonical site key, which depends on the project's entity
    resolution context).
    """
    out: list[SiteAllocationLine] = []
    for atom, filename in _iter_atoms_with_files(report):
        text = atom.get("text") or ""
        if "allocated" not in text.lower():
            continue
        for m in _ALLOCATION_RE.finditer(text):
            device = m.group("device").strip().rstrip(".")
            try:
                unit_price = int(float(m.group("price").replace(",", "")))
            except ValueError:
                continue
            alloc_str = m.group("alloc")
            for piece in alloc_str.split(","):
                piece = piece.strip()
                pair = piece.split()
                if len(pair) < 2:
                    continue
                site = pair[0]
                try:
                    qty = int(pair[-1])
                except ValueError:
                    continue
                if qty <= 0 or unit_price <= 0:
                    continue
                out.append(
                    SiteAllocationLine(
                        site=site,
                        device=device,
                        quantity=qty,
                        unit_price=unit_price,
                        extended=qty * unit_price,
                        source=filename,
                    )
                )
    return out


# ────────────────────────────── B6 per-site rollup ──────────────────────────────


@dataclass(frozen=True)
class SiteRollup:
    """Aggregated evidence touching one site.

    Per-site allocations are usually tangled inside paragraph text
    ("ATL-HQ 52, ATL-WEST 27, ATL-AIR 15") that the parser captures
    as a single atom with multiple ``site:*`` entity_keys. Rather
    than re-parse that free text, this rollup gives the PM the
    full evidence picture for each site: distinct devices,
    distinct money values, distinct dates, distinct
    stakeholders, and the atom count.

    The PM can scan the table to confirm "did every site get
    its budget / device list / stakeholder coverage?"
    """

    site_key: str  # canonical key e.g. "atl_hq"
    site_name: str  # human display
    atom_count: int
    devices: list[str] = field(default_factory=list)
    money_values: list[str] = field(default_factory=list)  # display strings
    dates: list[str] = field(default_factory=list)
    stakeholders: list[str] = field(default_factory=list)


def _humanize_canonical(canonical: str) -> str:
    """``atl_west`` -> ``ATL-WEST``; ``main_campus`` -> ``Main Campus``."""
    if not canonical:
        return ""
    parts = canonical.split("_")
    if all(len(p) <= 4 for p in parts) and len(parts) <= 4:
        return "-".join(p.upper() for p in parts if p)
    return " ".join(p.capitalize() for p in parts if p)


_ZONE_LIKE_SITE_RE = re.compile(
    r"\b(zones?|areas?|regions?|office\s+areas?|warehouse\s+zones?)\b",
    re.I,
)

_VENDOR_SITE_RE = re.compile(
    r"purtera|amber\s*park|11720|alpharetta.*30009",
    re.I,
)


def _is_zone_like_site_key(site_key: str) -> bool:
    """Coverage zones (warehouse zones, office areas) are not physical sites."""
    return bool(_ZONE_LIKE_SITE_RE.search(site_key.replace("_", " ")))


def _is_vendor_site_key(site_key: str) -> bool:
    """PurTera corporate / letterhead addresses must not publish as job sites."""
    return bool(_VENDOR_SITE_RE.search(site_key.replace("_", " ")))


def _physical_site_slugs(report: dict[str, Any]) -> set[str]:
    slugs: set[str] = set()
    indexes = report.get("indexes") or {}
    for slug in indexes.get("physical_site_slugs") or ():
        if isinstance(slug, str) and slug.strip():
            slugs.add(slug.strip())
    for atom, _filename in _iter_atoms_with_files(report):
        if atom.get("atom_type") != "physical_site":
            continue
        for key in atom.get("entity_keys") or ():
            if isinstance(key, str) and key.startswith("site:"):
                slugs.add(key.split(":", 1)[1])
    return slugs


def build_site_rollups(report: dict[str, Any]) -> list[SiteRollup]:
    """Group every atom by every ``site:*`` entity_key it carries.

    Output is sorted by site_key for stable ordering. Devices /
    money / dates / stakeholders are de-duped per site.
    """
    by_site_devices: dict[str, set[str]] = defaultdict(set)
    by_site_money: dict[str, set[int]] = defaultdict(set)
    by_site_dates: dict[str, set[str]] = defaultdict(set)
    by_site_stake: dict[str, set[str]] = defaultdict(set)
    by_site_count: dict[str, int] = defaultdict(int)
    physical_slugs = _physical_site_slugs(report)

    for atom, _filename in _iter_atoms_with_files(report):
        sites = [
            k.split(":", 1)[1]
            for k in atom.get("entity_keys") or ()
            if isinstance(k, str) and k.startswith("site:")
        ]
        if not sites:
            continue
        for site in sites:
            by_site_count[site] += 1
            for k in atom.get("entity_keys") or ():
                if not isinstance(k, str) or ":" not in k:
                    continue
                kind, raw = k.split(":", 1)
                if kind == "device":
                    by_site_devices[site].add(raw.replace("_", " "))
                elif kind == "money":
                    try:
                        by_site_money[site].add(int(raw))
                    except ValueError:
                        pass
                elif kind == "date":
                    by_site_dates[site].add(raw)
                elif kind == "stakeholder":
                    by_site_stake[site].add(raw.replace("_", " ").title())

    rollups: list[SiteRollup] = []
    for site in sorted(by_site_count):
        if _is_zone_like_site_key(site):
            continue
        if _is_vendor_site_key(site):
            continue
        if site not in physical_slugs:
            continue
        # Suppress single-atom sites here. parser-os alias fusion
        # usually merges N surface names into one canonical site,
        # but any name that didn't fuse will appear with one atom
        # and zero device / money / date / stakeholder coverage.
        # Those rows are noise at the PM layer; the canonical
        # site already appears with full coverage.
        atom_count = by_site_count[site]
        has_coverage = (
            by_site_devices[site]
            or by_site_money[site]
            or by_site_dates[site]
            or by_site_stake[site]
        )
        if atom_count < 2 and not has_coverage:
            continue
        rollups.append(
            SiteRollup(
                site_key=site,
                site_name=_humanize_canonical(site),
                atom_count=atom_count,
                devices=sorted(by_site_devices[site]),
                money_values=[_display_money(v) for v in sorted(by_site_money[site], reverse=True)],
                dates=sorted(by_site_dates[site]),
                stakeholders=sorted(by_site_stake[site]),
            )
        )
    return rollups


# ────────────────────────────── B5 schedule / Gantt ──────────────────────────────


@dataclass(frozen=True)
class SchedulePhase:
    """One project-schedule row pulled from atoms.

    Parser-os emits these from the project-schedule workbook with
    structured ``start`` / ``end`` / ``phase`` fields. The
    PM_HANDOFF renders them as a mermaid Gantt block.
    """

    phase: str
    start: str  # ISO YYYY-MM-DD or empty
    end: str
    owner: str = ""
    source: str = ""


def _coerce_date_iso(value: Any) -> str:
    """Return an ISO YYYY-MM-DD or empty if the value is not parsable.

    Parser-os usually emits ISO already; accept a few common
    workbook shapes (``2026-08-14``, ``2026/08/14``,
    ``08/14/2026``). Anything else returns empty so the Gantt
    block silently skips the row instead of producing garbage.
    """
    if not value:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    import re as _re
    m = _re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", s)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        return f"{y:04d}-{mo:02d}-{d:02d}"
    m = _re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        mo, d, y = (int(x) for x in m.groups())
        return f"{y:04d}-{mo:02d}-{d:02d}"
    return ""


def build_schedule_phases(report: dict[str, Any]) -> list[SchedulePhase]:
    """Pull schedule rows from any atom whose ``canonical_cells``
    expose both a start *and* an end date.

    parser-os doesn't currently emit a dedicated ``schedule_phase``
    atom_type — schedule rows ride in as ``scope_item`` /
    ``table_row``-structured atoms whose canonical_cells include
    ``start_date`` + ``end_date``. We detect "this is a schedule
    row" structurally (presence of both dated fields) rather than
    by atom_type, so future parser-os work can add a dedicated
    atom_type without breaking this projection.

    Sorted by start date so the Gantt block reads chronologically.
    """
    phases: list[SchedulePhase] = []
    for atom, filename in _iter_atoms_with_files(report):
        structured = atom.get("structured") or {}
        if not isinstance(structured, dict):
            continue
        cells = structured.get("canonical_cells") or structured.get("cells") or {}
        if not isinstance(cells, dict):
            continue
        start = _coerce_date_iso(
            cells.get("start") or cells.get("start_date") or cells.get("Start")
        )
        end = _coerce_date_iso(
            cells.get("end") or cells.get("end_date") or cells.get("Finish")
        )
        # Structural gate: a schedule row must have BOTH dates.
        # Otherwise the row is a checklist / cutover step / risk
        # register entry that happens to live in the same workbook.
        if not (start and end):
            continue
        # Prefer human-readable name fields over numeric "phase: 2"
        # ordinals; fall back to ordinal only when no name is present.
        phase = str(
            cells.get("name")
            or cells.get("Name")
            or cells.get("Task")
            or cells.get("task_name")
            or cells.get("phase_name")
            or cells.get("phase")
            or cells.get("Phase")
            or ""
        )
        if not phase:
            continue
        phases.append(
            SchedulePhase(
                phase=phase[:80],
                start=start,
                end=end,
                owner=str(cells.get("owner") or "")[:60],
                source=filename,
            )
        )
    phases.sort(key=lambda p: (p.start or "9999", p.phase))
    return phases

