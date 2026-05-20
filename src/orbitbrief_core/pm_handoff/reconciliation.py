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
    """
    items: list[ActionItem] = []
    for g in gaps:
        sev = getattr(g, "severity", "")
        if sev not in {"blocker", "warning"}:
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
    return items


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

