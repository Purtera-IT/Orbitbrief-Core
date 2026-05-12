"""Render :class:`ComposedBrief` to operator-friendly Markdown.

Stable, deterministic output — same brief in produces same Markdown
out so docs can be version-controlled and diffed across pipeline
runs.
"""
from __future__ import annotations

from typing import Iterable

from orbitbrief_core.calibrator.verdict import Verdict
from orbitbrief_core.composer.composer import (
    ComposedBrief,
    DomainGroup,
    DomainSection,
    DomainSectionItem,
)


_VERDICT_BADGE = {
    Verdict.AUTO_ACCEPT: "[OK]",
    Verdict.NEEDS_REVIEW: "[REVIEW]",
    Verdict.REJECT: "[REJECT]",
}


def render_markdown(brief: ComposedBrief) -> str:
    """Return a Markdown string ready for the reviewer UI / handoff."""
    lines: list[str] = []
    lines.append(f"# OrbitBrief — {brief.summary.project_id}")
    lines.append("")
    lines.append(f"_Compile_: `{brief.summary.compile_id}`  ·  _Generated_: {brief.summary.generated_at}")
    lines.append("")

    lines.append("## Executive Summary")
    lines.append("")
    lines.append(_summary_table(brief))
    lines.append("")

    if brief.sites:
        lines.append("## Sites")
        lines.append("")
        lines.append("| Cluster | Name | Role |")
        lines.append("|---|---|---|")
        for s in brief.sites:
            lines.append(f"| `{s.cluster_id}` | {s.canonical_name} | {s.role} |")
        lines.append("")

    for group in brief.domains:
        lines.append(_render_domain(group))
        lines.append("")

    if brief.open_questions:
        lines.append("## Open Questions Across All Domains")
        lines.append("")
        for it in brief.open_questions:
            lines.append(f"- {_VERDICT_BADGE.get(it.verdict, '')} {it.statement}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ────────────────────────────── helpers ────────────────────────────────


def _summary_table(brief: ComposedBrief) -> str:
    s = brief.summary
    rows = [
        ("Active Packs", ", ".join(s.active_packs) if s.active_packs else "—"),
        ("Sites", str(s.site_count)),
        ("Contradictions", str(s.contradiction_count)),
        ("Review Flags", str(s.review_flag_count)),
        ("Planner Model", s.planner_model or "—"),
        ("Planner Tier", s.planner_tier or "—"),
        ("Auto-accepted Items", str(brief.auto_accept_count)),
        ("Items Needing Review", str(brief.review_count)),
        ("Items Rejected", str(brief.blocker_count)),
    ]
    out = ["| Field | Value |", "|---|---|"]
    for k, v in rows:
        out.append(f"| {k} | {v} |")
    return "\n".join(out)


def _render_domain(group: DomainGroup) -> str:
    out: list[str] = []
    badge = " (fallback)" if group.fallback_used else ""
    out.append(f"## {group.display_name}{badge}")
    out.append("")
    out.append(f"_Brain_: `{group.brain}`  ·  _Pack_: `{group.pack_id}`")
    out.append("")

    nonempty = [s for s in group.sections if s.items]
    if not nonempty:
        out.append("_(no items emitted)_")
        return "\n".join(out)

    for section in nonempty:
        out.append(_render_section(section))
        out.append("")
    return "\n".join(out).rstrip()


def _render_section(section: DomainSection) -> str:
    out: list[str] = []
    out.append(f"### {section.display_name}")
    out.append("")
    for item in section.items:
        out.append(_render_item(item))
        out.append("")
    return "\n".join(out).rstrip()


def _render_item(item: DomainSectionItem) -> str:
    badge = _VERDICT_BADGE.get(item.verdict, "")
    conf = f"_calibrated {item.calibrated_confidence:.2f} · raw {item.raw_confidence:.2f}_"
    out = [f"- {badge} **{item.statement}**", f"  - {conf}"]
    if item.supporting_packet_ids:
        out.append(f"  - packets: {', '.join(f'`{p}`' for p in item.supporting_packet_ids)}")
    if item.supporting_atom_ids:
        out.append(f"  - atoms: {', '.join(f'`{a}`' for a in item.supporting_atom_ids)}")
    if item.metadata:
        meta = "; ".join(f"{k}={v}" for k, v in sorted(item.metadata.items()))
        out.append(f"  - metadata: {meta}")
    if item.reasons:
        out.append(f"  - reasons: {', '.join(r.value for r in item.reasons)}")
    if item.validation_failures:
        for f in item.validation_failures:
            out.append(f"  - flag: `{f['rule_id']}` ({f['severity']}) — {f['message']}")
    return "\n".join(out)
