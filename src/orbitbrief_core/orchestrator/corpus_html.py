"""Render :class:`CorpusReport` as a single-page cross-case dashboard.

Sections in display order:

1. **Header** — corpus identity, case count, total atoms processed,
   total runtime, model used.
2. **KPI strip** — total cases, total composed items, total queue
   items, total atoms processed.
3. **Pack-routing distribution** — which packs activated in how many
   cases (heatmap-ish bar chart).
4. **Brain health** — per-brain OK/fallback rate across the corpus.
5. **Stage timing** — median + p95 + max per pipeline stage so the
   bottleneck is obvious at a glance.
6. **Top "interesting" findings** — biggest atom counts, highest
   contradictions, multi-domain cases, fallback hotspots.
7. **Per-case scoreboard** — one row per case with status, counts,
   timing, links to the per-case inspection report + composed brief.
"""
from __future__ import annotations

import html
import json
from typing import Any

from orbitbrief_core.orchestrator.corpus import CaseScore, CorpusReport


def render_corpus_html(report: CorpusReport) -> str:
    cases = report.cases
    agg = report.aggregates()
    parts: list[str] = []
    parts.append(_HEAD)
    parts.append(_header_block(report, agg))
    parts.append(_kpi_strip(agg))
    parts.append(_pack_distribution(agg))
    parts.append(_brain_health(agg))
    parts.append(_stage_timing(agg))
    parts.append(_interesting_findings(agg))
    parts.append(_case_scoreboard(cases))
    parts.append("</main></body></html>")
    return "\n".join(parts)


def _esc(s: Any) -> str:
    return html.escape(str(s)) if s is not None else ""


def _section(title: str, body: str, *, anchor: str = "") -> str:
    aid = f' id="{anchor}"' if anchor else ""
    return f'<section{aid}><h2>{_esc(title)}</h2>{body}</section>'


def _header_block(report: CorpusReport, agg: dict) -> str:
    return f"""
<header>
  <h1>OrbitBrief corpus dashboard</h1>
  <div class="muted">
    Root <code>{_esc(report.corpus_root)}</code> ·
    {_esc(agg.get('total_cases', 0))} case(s) ·
    {_esc(agg.get('total_atoms_processed', 0)):>0} atoms processed ·
    {_esc(agg.get('total_runtime_seconds', 0))}s total runtime
  </div>
  <nav class="anchors">
    <a href="#kpi">KPIs</a>
    <a href="#packs">Pack routing</a>
    <a href="#brains">Brain health</a>
    <a href="#timing">Stage timing</a>
    <a href="#interesting">Findings</a>
    <a href="#cases">Per-case</a>
  </nav>
</header>
"""


def _kpi_strip(agg: dict) -> str:
    body = f"""
<div class="kpi-strip">
  <div><span class="kpi-num">{_esc(agg.get('total_cases', 0))}</span><span class="kpi-lbl">cases</span></div>
  <div><span class="kpi-num">{_esc(agg.get('total_atoms_processed', 0))}</span><span class="kpi-lbl">total atoms</span></div>
  <div><span class="kpi-num">{_esc(agg.get('total_composed_items', 0))}</span><span class="kpi-lbl">brief items composed</span></div>
  <div><span class="kpi-num">{_esc(agg.get('total_queued_for_review', 0))}</span><span class="kpi-lbl">items queued for review</span></div>
  <div><span class="kpi-num">{_esc(agg.get('mean_atoms_per_case', 0))}</span><span class="kpi-lbl">avg atoms / case</span></div>
  <div><span class="kpi-num">{_esc(agg.get('max_atoms_per_case', 0))}</span><span class="kpi-lbl">peak atoms / case</span></div>
  <div><span class="kpi-num">{_esc(agg.get('total_runtime_seconds', 0))}s</span><span class="kpi-lbl">total runtime</span></div>
</div>
"""
    return _section("Corpus KPIs", body, anchor="kpi")


def _pack_distribution(agg: dict) -> str:
    pack_app = agg.get("pack_appearance") or {}
    pack_top = agg.get("pack_top_count") or {}
    if not pack_app:
        return _section("Pack routing", "<p class='muted'>(no pack data)</p>", anchor="packs")

    max_count = max(pack_app.values()) if pack_app else 1
    rows = []
    for pack, count in pack_app.items():
        top_count = pack_top.get(pack, 0)
        bar_pct = int(100 * count / max_count)
        rows.append(
            f'<tr>'
            f'<td><code>{_esc(pack)}</code></td>'
            f'<td class="num">{_esc(count)}</td>'
            f'<td class="num">{_esc(top_count)}</td>'
            f'<td><div class="bar" style="width: {bar_pct}%"></div></td>'
            f'</tr>'
        )
    body = f"""
<p class="muted">"Active in" = number of cases where this pack was selected to run a brain. "Top pick" = number of cases where this pack scored #1 in pack_prior.</p>
<table class="wide">
  <thead><tr>
    <th>Pack</th><th class="num">Active in (cases)</th><th class="num">Top pick (cases)</th><th>Distribution</th>
  </tr></thead>
  <tbody>{"".join(rows)}</tbody>
</table>
"""
    return _section("Pack routing across the corpus", body, anchor="packs")


def _brain_health(agg: dict) -> str:
    health = agg.get("brain_health") or {}
    if not health:
        return _section("Brain health", "<p class='muted'>(no brain runs yet — run with --ollama to populate)</p>", anchor="brains")
    rows = []
    for brain, info in health.items():
        ok_pct = info.get("ok_rate_pct", 0)
        bar_color = "ok" if ok_pct >= 80 else ("warn" if ok_pct >= 50 else "bad")
        bar_pct = int(ok_pct)
        rows.append(
            f'<tr>'
            f'<td><code>{_esc(brain)}</code></td>'
            f'<td class="num">{_esc(info.get("total_runs", 0))}</td>'
            f'<td class="num">{_esc(info.get("ok_runs", 0))}</td>'
            f'<td class="num">{_esc(info.get("fallback_runs", 0))}</td>'
            f'<td><div class="bar bar-{bar_color}" style="width: {bar_pct}%"></div> {_esc(ok_pct)}%</td>'
            f'</tr>'
        )
    body = f"""
<table class="wide">
  <thead><tr>
    <th>Brain</th><th class="num">Total runs</th><th class="num">OK</th><th class="num">Fallback</th><th>OK rate</th>
  </tr></thead>
  <tbody>{"".join(rows)}</tbody>
</table>
"""
    return _section("Brain health across the corpus", body, anchor="brains")


def _stage_timing(agg: dict) -> str:
    timing = agg.get("stage_timing_summary") or {}
    if not timing:
        return _section("Stage timing", "<p class='muted'>(no timing data)</p>", anchor="timing")
    rows = []
    for stage, info in timing.items():
        rows.append(
            f'<tr>'
            f'<td><code>{_esc(stage)}</code></td>'
            f'<td class="num">{_esc(info.get("n", 0))}</td>'
            f'<td class="num">{_esc(info.get("median_ms", 0))}</td>'
            f'<td class="num">{_esc(info.get("p95_ms", 0))}</td>'
            f'<td class="num">{_esc(info.get("max_ms", 0))}</td>'
            f'</tr>'
        )
    body = f"""
<p class="muted">Where is the time going? Median + p95 + max per stage across all cases.</p>
<table class="wide">
  <thead><tr>
    <th>Stage</th><th class="num">n</th><th class="num">median ms</th><th class="num">p95 ms</th><th class="num">max ms</th>
  </tr></thead>
  <tbody>{"".join(rows)}</tbody>
</table>
"""
    return _section("Stage timing aggregates", body, anchor="timing")


def _interesting_findings(agg: dict) -> str:
    blocks: list[str] = []

    # Biggest atom counts.
    top_atoms = agg.get("top_by_atom_count") or []
    if top_atoms:
        blocks.append(
            "<h3 class='sub'>Biggest engagements (by atom count)</h3>"
            "<ul>"
            + "".join(
                f'<li><a href="#case-{_esc(c["case_id"])}"><code>{_esc(c["case_id"])}</code></a> — {_esc(c["atom_count"])} atoms</li>'
                for c in top_atoms
            )
            + "</ul>"
        )

    # Highest contradictions.
    top_con = agg.get("top_by_contradictions") or []
    if top_con:
        blocks.append(
            "<h3 class='sub'>Highest contradiction count</h3>"
            "<ul>"
            + "".join(
                f'<li><a href="#case-{_esc(c["case_id"])}"><code>{_esc(c["case_id"])}</code></a> — {_esc(c["contradiction_count"])} contradicts</li>'
                for c in top_con
            )
            + "</ul>"
        )

    # Multi-domain cases.
    multi = agg.get("multi_domain_cases") or []
    if multi:
        blocks.append(
            "<h3 class='sub'>Multi-domain engagements (≥ 2 brains ran)</h3>"
            "<ul>"
            + "".join(
                f'<li><a href="#case-{_esc(c["case_id"])}"><code>{_esc(c["case_id"])}</code></a> — brains: {_esc(", ".join(c["brains_run"]))}</li>'
                for c in multi
            )
            + "</ul>"
        )

    # Fallback hotspots.
    fb = agg.get("fallback_cases") or []
    if fb:
        blocks.append(
            "<h3 class='sub'>Cases with brain fallbacks</h3>"
            "<ul>"
            + "".join(
                f'<li><a href="#case-{_esc(c["case_id"])}"><code>{_esc(c["case_id"])}</code></a> — fallback brains: {_esc(", ".join(c["fallback_brains"]))}</li>'
                for c in fb
            )
            + "</ul>"
        )

    if not blocks:
        return _section("Interesting findings", "<p class='muted'>(no notable patterns yet)</p>", anchor="interesting")
    return _section("Interesting findings", "\n".join(blocks), anchor="interesting")


def _case_scoreboard(cases: list[CaseScore]) -> str:
    if not cases:
        return _section("Per-case scoreboard", "<p class='muted'>(no cases yet)</p>", anchor="cases")
    rows = []
    for c in cases:
        # Status lights.
        status_bits = []
        if c.has_inspection_report:
            status_bits.append('<span class="badge ok">insp</span>')
        if c.has_composed_brief:
            status_bits.append('<span class="badge ok">brief</span>')
        if c.brain_fallbacks:
            status_bits.append(f'<span class="badge bad">{len(c.brain_fallbacks)} fallback</span>')
        elif c.brains_run:
            status_bits.append(f'<span class="badge ok">{len(c.brains_run)} brain(s)</span>')
        if c.queued_for_review:
            status_bits.append(f'<span class="badge warn">{c.queued_for_review} queued</span>')

        # Per-case anchors + drill-down links.
        insp_link = (
            f' · <a href="file://{_esc(c.artifacts_dir)}/91_inspection_report.html">inspection</a>'
            if c.has_inspection_report else ""
        )
        brief_link = (
            f' · <a href="file://{_esc(c.artifacts_dir)}/81_composed_brief.md">brief</a>'
            if c.has_composed_brief else ""
        )

        runtime_s = c.total_runtime_ms / 1000 if c.total_runtime_ms else 0
        rows.append(
            f'<tr id="case-{_esc(c.case_id)}">'
            f'<td><strong><code>{_esc(c.case_id)}</code></strong>'
            f'<div class="muted small">{insp_link}{brief_link}</div></td>'
            f'<td class="num">{_esc(c.source_artifact_count)}</td>'
            f'<td class="num">{_esc(c.atom_count)}</td>'
            f'<td class="num">{_esc(c.packet_count)}</td>'
            f'<td class="num">{_esc(c.contradiction_count)}</td>'
            f'<td><code>{_esc(c.pack_prior_top or "-")}</code><div class="muted small">margin {_esc(c.pack_prior_margin)}</div></td>'
            f'<td><code>{_esc(", ".join(c.brains_run) or "-")}</code></td>'
            f'<td class="num">{_esc(c.composed_items)}</td>'
            f'<td class="num">{_esc(round(runtime_s, 1))}s</td>'
            f'<td>{"".join(status_bits)}</td>'
            f'</tr>'
        )
    body = f"""
<table class="wide cases">
  <thead><tr>
    <th>Case</th><th class="num">files</th><th class="num">atoms</th>
    <th class="num">packets</th><th class="num">contra</th>
    <th>Top pack</th><th>Brains</th>
    <th class="num">items</th><th class="num">runtime</th><th>Status</th>
  </tr></thead>
  <tbody>{"".join(rows)}</tbody>
</table>
"""
    return _section("Per-case scoreboard", body, anchor="cases")


_HEAD = """<!doctype html><html lang="en"><head>
<meta charset="utf-8">
<title>OrbitBrief corpus dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root {
  --fg: #111;
  --muted: #6a737d;
  --bg: #fafbfc;
  --card: #fff;
  --border: #e1e4e8;
  --accent: #1f6feb;
  --ok: #2c8a4d;
  --warn: #b35900;
  --bad: #b3261e;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; line-height: 1.4; font-size: 14px; }
header { background: linear-gradient(135deg, #0e1116 0%, #1a2332 100%); color: #fafbfc; padding: 22px 32px; border-bottom: 1px solid #000; }
header h1 { margin: 0 0 6px 0; font-size: 22px; font-weight: 700; letter-spacing: -0.02em; }
header .muted { color: #8b94a3; font-size: 13px; }
header nav.anchors { margin-top: 12px; font-size: 12px; }
header nav.anchors a { color: #cdd6e0; margin-right: 14px; text-decoration: none; }
header nav.anchors a:hover { color: white; text-decoration: underline; }
main { max-width: 1400px; margin: 0 auto; padding: 28px; }
section { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 22px 26px; margin-bottom: 22px; box-shadow: 0 1px 0 rgba(0,0,0,.02); }
section h2 { margin: 0 0 16px 0; font-size: 17px; font-weight: 700; padding-bottom: 10px; border-bottom: 1px solid var(--border); letter-spacing: -0.01em; }
section h3.sub { margin: 18px 0 8px 0; font-size: 13px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: .07em; }
.muted { color: var(--muted); }
.muted.small { font-size: 11px; }

/* KPI strip */
.kpi-strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 14px; }
.kpi-strip > div { background: linear-gradient(135deg, #f4f5f7 0%, #fafbfc 100%); border: 1px solid var(--border); border-radius: 6px; padding: 14px 18px; text-align: center; }
.kpi-num { display: block; font-size: 28px; font-weight: 700; line-height: 1.1; font-variant-numeric: tabular-nums; color: var(--fg); }
.kpi-lbl { display: block; margin-top: 4px; font-size: 11px; text-transform: uppercase; color: var(--muted); letter-spacing: .06em; }

/* Tables */
table { width: 100%; border-collapse: collapse; font-size: 13px; }
table.wide th, table.wide td { padding: 8px 10px; text-align: left; border-bottom: 1px solid var(--border); vertical-align: top; }
table.wide th { background: #f4f5f7; font-size: 11px; text-transform: uppercase; color: var(--muted); letter-spacing: .04em; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
table.cases tbody tr:hover { background: #f8f9fa; }

/* Bars */
.bar { background: linear-gradient(90deg, var(--accent), #4a90ff); height: 14px; border-radius: 3px; min-width: 4px; display: inline-block; vertical-align: middle; }
.bar-ok    { background: linear-gradient(90deg, var(--ok), #4caf50); }
.bar-warn  { background: linear-gradient(90deg, var(--warn), #ff9800); }
.bar-bad   { background: linear-gradient(90deg, var(--bad), #f44336); }

/* Code + badges */
code { background: #f4f5f7; padding: 1px 6px; border-radius: 3px; font-family: ui-monospace, SFMono-Regular, monospace; font-size: 11px; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; margin-right: 4px; text-transform: uppercase; letter-spacing: .03em; }
.badge.ok    { background: rgba(44,138,77,0.12);  color: var(--ok); }
.badge.warn  { background: rgba(179,89,0,0.12);   color: var(--warn); }
.badge.bad   { background: rgba(179,38,30,0.12);  color: var(--bad); }

ul { margin: 6px 0 0 0; padding-left: 22px; }
ul li { margin: 3px 0; }
</style>
</head>
<body>
<main>
"""
