"""B8: Vendor RFP packet auto-generation.

Produces an ``RFP_DRAFT.md`` file that the PM can split into
per-vendor RFP sections. Every line item is real (parsed from
``vendor_line_item`` atoms); categories are inferred from
descriptions so the RFP groups naturally even when the source
BOM has no material_family column.

What lands:

  Header: project name + sites + headline figures + submission
  due date (from the schedule's discovery phase, when present).

  One section per inferred category. Each section has:
    - Scope blurb (what kinds of items vendors should quote on)
    - Line-item table (part_number, description, qty, unit_price,
      lead_time)
    - Required compliance frameworks (pulled from the handoff's
      compliance_callouts)
    - Acceptance criteria (the relevant slice of handoff
      acceptance_checks)
    - Submission instructions (boilerplate)

The PM still needs to fill in the cover letter and submission
deadline; the rest is auto-generated from the intake atoms.
"""
from __future__ import annotations

from collections import OrderedDict, defaultdict
from typing import Any

from orbitbrief_core.pm_handoff.models import PMHandoff


_SUBMISSION_BOILERPLATE = """\
**Submission instructions**

- Pricing must be in USD, valid for 60 days from submission.
- Substitutions require written approval; mark "Same as Specified" \
or include a proposed alternate part with full technical equivalence.
- Lead-time commitments are binding.
- Include warranty terms, support tier, and any included \
professional services.
- Submit one PDF per category to procurement@<customer>.example with \
the subject line: "RFP — <project name> — <category>".
"""


def render_rfp_draft(handoff: PMHandoff) -> str:
    """Produce the ``RFP_DRAFT.md`` text from a PM handoff.

    Returns an empty string when there are no vendor line items
    to RFP — the caller can skip writing the file in that case.
    """
    items = [RFPLineLike(d) for d in (handoff.__dict__.get("rfp_line_items") or [])]
    # Note: rfp_line_items lives on the dict version of the
    # handoff (added in models.py). We unbox via __dict__ so this
    # module is robust to dataclass-vs-dict variations.
    raw = handoff.__dict__.get("rfp_line_items") or []
    if not raw:
        return ""
    lines: list[str] = [
        f"# Request for Proposal (RFP) — DRAFT",
        f"## Project: {handoff.case_id}",
        "",
        f"> **Status: DRAFT.** Auto-generated from the intake "
        f"package. PM must fill the cover letter, set the "
        f"submission deadline, attach NDAs / MSA references, "
        f"and verify each category section against the master BOM "
        f"before sending to vendors.",
        "",
        f"_{handoff.one_line_summary}_",
        "",
    ]

    # Header summary
    sites = ", ".join(s.name for s in handoff.sites if s.publishable) or "[TBD]"
    lines.extend([
        "## Project overview",
        "",
        f"- **Sites in scope:** {sites}",
    ])
    money = handoff.money_mentions or []
    if money:
        top = ", ".join(m.get("display", "") for m in money[:3] if int(m.get("value", 0)) >= 10_000)
        if top:
            lines.append(f"- **Headline contract figures referenced in intake:** {top}")
    if handoff.schedule_phases:
        first_phase = handoff.schedule_phases[0]
        lines.append(
            f"- **Earliest required start:** {first_phase.get('start','TBD')} "
            f"(phase: {first_phase.get('phase','')})"
        )
    lines.append("")
    lines.append("**Submission deadline:** [TBD] — PM to confirm before sending.")
    lines.append("")

    # Compliance pull-up (used by every category section)
    compliance_frameworks: list[str] = []
    seen_f: set[str] = set()
    for c in handoff.compliance_callouts or []:
        f = c.get("framework", "")
        if f and f not in seen_f:
            seen_f.add(f)
            compliance_frameworks.append(f)

    # Group items by category, preserving the category order in
    # _RFP_CATEGORY_KEYWORDS so the RFP reads in a consistent shape.
    by_cat: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for it in raw:
        by_cat.setdefault(it.get("category", "Miscellaneous"), []).append(it)

    for category, rows in by_cat.items():
        lines.append("---")
        lines.append("")
        lines.append(f"## {category}")
        lines.append("")
        subtotal = sum(int(r.get("quantity", 0)) * int(r.get("unit_price", 0)) for r in rows)
        lines.append(
            f"_{len(rows)} line item(s). Indicative subtotal (qty × unit "
            f"price as referenced in intake): ${subtotal:,}._"
        )
        lines.append("")
        lines.extend([
            "| # | Part # | Description | Qty | Unit price | Lead time | Notes |",
            "|--:|---|---|---:|---:|---|---|",
        ])
        for i, r in enumerate(sorted(rows, key=lambda x: -(int(x.get("quantity", 0)) * int(x.get("unit_price", 0)))), 1):
            qty = int(r.get("quantity", 0))
            up = int(r.get("unit_price", 0))
            up_disp = f"${up:,}" if up else "[TBD]"
            notes = (r.get("notes") or "").replace("|", "\\|")
            desc = (r.get("description") or "").replace("|", "\\|")
            lines.append(
                f"| {i} | `{r.get('part_number','')}` | {desc} | {qty} | "
                f"{up_disp} | {r.get('lead_time','') or '—'} | {notes} |"
            )
        lines.append("")
        if compliance_frameworks:
            lines.append("**Compliance / contractual references applicable to this category:**")
            lines.append("")
            for f in compliance_frameworks:
                lines.append(f"- {f}")
            lines.append("")
        # Acceptance criteria slice — include all phase-level checks
        # so the responding vendor sees the phase-exit definitions
        # they'll be measured against.
        accept_checks = handoff.acceptance_checks or []
        phase_checks = [
            c for c in accept_checks
            if not str(c.get("phase_or_step", "")).startswith("Step ")
        ]
        if phase_checks:
            lines.append("**Acceptance criteria the vendor's work must satisfy:**")
            lines.append("")
            for c in phase_checks:
                ph = c.get("phase_or_step", "")
                crit = c.get("criterion", "")
                lines.append(f"- **{ph}** — {crit}")
            lines.append("")
        lines.append(_SUBMISSION_BOILERPLATE)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


class RFPLineLike:
    """Adapter so ``render_rfp_draft`` can take either a dict or
    a dataclass for each line item without an explicit import
    of the dataclass type.
    """

    def __init__(self, payload: Any) -> None:
        if isinstance(payload, dict):
            self._d = payload
        else:
            self._d = getattr(payload, "__dict__", {}) or {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._d.get(key, default)
