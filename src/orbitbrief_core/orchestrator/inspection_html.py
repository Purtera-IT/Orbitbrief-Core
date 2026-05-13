"""Render :func:`build_inspection_report` output to a single-page HTML view.

Designed for "scroll top-to-bottom and see the whole pipeline" rather
than rich interactivity. One file, no JS dependencies, hand-rolled
CSS, deterministic layout. Reviewers can save the page, diff two runs
in plain text, or paste sections into a SOW review email.

Sections (in order):

1. **Header** — case identity, model, runtime, funnel one-liner.
2. **Pipeline funnel** — visual attrition (sources → atoms → packets →
   bundle → brain → composed brief) with per-pack splits.
3. **Pack prior** — top-N domain scores + matched keywords.
4. **Site reality** — clusters, member atoms, cross-artifact reach.
5. **Per-source artifact** — for each parsed file, raw content preview
   on the LEFT, the atoms parser-os extracted from it on the RIGHT,
   each atom decorated with downstream survival flags.
6. **GNN graph** — the entity + edge structure (deduplicated entities
   showing how parser-os normalized identity across artifacts; edges
   showing same_as / supports / contradicts / etc.).
7. **Packet ledger** — every packet with its atom citations and
   downstream survival path (bundled? cited? in brief?).
8. **Brain outputs** — per-domain emitted items with verdict.
9. **Validator + calibrator + queue** — quality gates + review queue.
10. **Composed brief summary** — what landed in the final document.
"""
from __future__ import annotations

import html
import json
from typing import Any


def render_inspection_html(report: dict[str, Any]) -> str:
    project = report.get("project_id") or "?"
    compile_id = report.get("compile_id") or "?"
    funnel = report.get("funnel") or {}
    parts: list[str] = []
    parts.append(_HEAD)
    parts.append(_header_block(project, compile_id, funnel, report))
    parts.append(_funnel_block(funnel))
    parts.append(_pack_prior_block(report.get("pack_prior") or {}))
    parts.append(_site_reality_block(report.get("site_reality") or {}))
    parts.append(_artifacts_block(report.get("artifacts") or []))
    parts.append(_graph_block(report.get("entities") or [], report.get("edges") or []))
    parts.append(_packets_block(report.get("packets") or []))
    parts.append(_brain_outputs_block(report.get("brain_items") or {}, report.get("validations") or {}, report.get("calibrations") or {}))
    parts.append(_composed_summary_block(report.get("composed_brief_summary") or {}))
    parts.append(_review_queue_block(report.get("review_queue") or {}))
    parts.append(_pipeline_log_block(report.get("pipeline_log") or []))
    parts.append("</main></body></html>")
    return "\n".join(parts)


# ────────────────────────────── helpers ────────────────────────────────


def _esc(s: Any) -> str:
    return html.escape(str(s)) if s is not None else ""


def _flag_badge(label: str, on: bool) -> str:
    cls = "flag-on" if on else "flag-off"
    return f'<span class="flag {cls}">{_esc(label)}</span>'


def _section(title: str, body: str, *, anchor: str = "") -> str:
    aid = f' id="{anchor}"' if anchor else ""
    return f'<section{aid}><h2>{_esc(title)}</h2>{body}</section>'


# ────────────────────────────── blocks ─────────────────────────────────


def _header_block(project: str, compile_id: str, funnel: dict, report: dict) -> str:
    rb = report.get("refined_brief") or {}
    manifest = report.get("manifest") or {}
    return f"""
<header>
  <h1>OrbitBrief inspection — <code>{_esc(project)}</code></h1>
  <div class="muted">
    Compile <code>{_esc(compile_id)}</code> ·
    Generated <code>{_esc(manifest.get("generated_at") or "?")}</code> ·
    Planner model <code>{_esc(rb.get("model_used") or "—")}</code>
    ({_esc(rb.get("tier") or "—")}) ·
    Total tokens <code>{_esc((rb.get("token_cost") or {}).get("total_tokens", "—"))}</code>
  </div>
  <nav class="anchors">
    <a href="#funnel">Funnel</a>
    <a href="#pack-prior">Pack prior</a>
    <a href="#site-reality">Site reality</a>
    <a href="#artifacts">Source artifacts</a>
    <a href="#graph">GNN graph</a>
    <a href="#packets">Packets</a>
    <a href="#brains">Brains</a>
    <a href="#composed">Composed brief</a>
    <a href="#queue">Review queue</a>
    <a href="#pipeline">Pipeline log</a>
  </nav>
</header>
"""


def _funnel_block(funnel: dict) -> str:
    rows = [
        ("Source artifacts", funnel.get("source_artifacts")),
        ("Atoms extracted", funnel.get("atoms_extracted")),
        ("Entities normalized", funnel.get("entities_normalized")),
        ("Edges built (GNN)", funnel.get("edges_built")),
        ("Packets certified", funnel.get("packets_certified")),
        ("Packets bundled (total)", funnel.get("bundled_packets_total")),
        ("Packets cited by brain(s)", funnel.get("brain_cited_packets")),
        ("Atoms cited by brain(s)", funnel.get("brain_cited_atoms")),
        ("Brain items emitted", sum((funnel.get("brain_items_per_pack") or {}).values()) if funnel.get("brain_items_per_pack") else 0),
        ("Composed-brief items", funnel.get("composed_brief_items")),
    ]
    table_rows = "\n".join(
        f"<tr><td>{_esc(label)}</td><td class='num'>{_esc(value if value is not None else '—')}</td></tr>"
        for label, value in rows
    )
    pct_rows = ""
    if (funnel.get("atoms_extracted") or 0):
        pct_rows = f"""
<div class="kpi">
  <div><strong>{_esc(funnel.get('atoms_to_brief_pct'))}%</strong> of atoms reach the brief</div>
  <div><strong>{_esc(funnel.get('packets_to_brief_pct'))}%</strong> of packets reach the brief</div>
</div>
"""
    per_pack = funnel.get("bundled_packets_per_pack") or {}
    per_pack_rows = "\n".join(
        f"<tr><td>{_esc(p)}</td><td class='num'>{_esc(c)}</td><td class='num'>{_esc((funnel.get('brain_items_per_pack') or {}).get(p, 0))}</td></tr>"
        for p, c in sorted(per_pack.items())
    ) or "<tr><td colspan='3' class='muted'>(no active packs)</td></tr>"

    body = f"""
<div class="cols">
  <div>
    <table>
      <thead><tr><th>Stage</th><th class='num'>Count</th></tr></thead>
      <tbody>{table_rows}</tbody>
    </table>
    {pct_rows}
  </div>
  <div>
    <table>
      <thead><tr><th>Pack</th><th class='num'>Bundled packets</th><th class='num'>Brain items</th></tr></thead>
      <tbody>{per_pack_rows}</tbody>
    </table>
  </div>
</div>
"""
    return _section("Pipeline funnel", body, anchor="funnel")


def _pack_prior_block(pp: dict) -> str:
    rows = "\n".join(
        f"<tr><td><code>{_esc(s.get('pack_id'))}</code></td>"
        f"<td class='num'>{_esc(s.get('raw_score'))}</td>"
        f"<td class='num'>{_esc(s.get('confidence'))}</td>"
        f"<td><code>{_esc(', '.join(s.get('matched_keywords') or []))}</code></td></tr>"
        for s in pp.get("top_scores") or []
    ) or "<tr><td colspan='4' class='muted'>(no pack scores)</td></tr>"
    body = f"""
<div class="muted">
  Top: <code>{_esc(pp.get('top_pack_id'))}</code> ({_esc(pp.get('top_confidence'))}) ·
  Runner-up: <code>{_esc(pp.get('runner_up_pack_id'))}</code> ({_esc(pp.get('runner_up_confidence'))}) ·
  Margin: {_esc(pp.get('margin'))} ·
  Tokens considered: {_esc(pp.get('tokens_considered'))} ·
  Escalated to LLM: {_esc(pp.get('escalated'))}
</div>
<table class="wide">
  <thead><tr><th>Pack</th><th class='num'>Raw score</th><th class='num'>Confidence</th><th>Matched keywords</th></tr></thead>
  <tbody>{rows}</tbody>
</table>
"""
    return _section("Pack prior — domain routing", body, anchor="pack-prior")


def _site_reality_block(sr: dict) -> str:
    clusters = sr.get("clusters") or []
    rows = "\n".join(
        f"<tr><td><code>{_esc(c.get('cluster_id'))}</code></td>"
        f"<td>{_esc(c.get('canonical_name'))}</td>"
        f"<td><code>{_esc(', '.join(c.get('site_keys') or []))}</code></td>"
        f"<td class='num'>{_esc(len(c.get('member_atom_ids') or []))}</td>"
        f"<td><code>{_esc(', '.join(c.get('artifact_ids') or []))}</code></td>"
        f"<td>{_flag_badge('LLM-resolved', bool(c.get('name_resolved_by_llm')))}</td></tr>"
        for c in clusters
    ) or "<tr><td colspan='6' class='muted'>(no site clusters)</td></tr>"
    body = f"""
<div class="muted">
  {_esc(sr.get('cluster_count', 0))} cluster(s) · {_esc(sr.get('merged_keys', 0))} key(s) merged
</div>
<table class="wide">
  <thead><tr><th>Cluster</th><th>Canonical name</th><th>Site keys</th><th class='num'>Member atoms</th><th>Artifacts</th><th>LLM</th></tr></thead>
  <tbody>{rows}</tbody>
</table>
"""
    return _section("Site reality — physical-site clustering", body, anchor="site-reality")


def _artifacts_block(artifacts: list[dict]) -> str:
    if not artifacts:
        return _section("Source artifacts", "<p class='muted'>(none)</p>", anchor="artifacts")
    blocks: list[str] = []
    for art in artifacts:
        atoms_html = _atoms_table(art.get("atoms") or [])
        truncated = art.get("atoms_truncated") or 0
        if truncated:
            atoms_html += f'<p class="muted">… {truncated} more atom(s) hidden (cap reached)</p>'
        preview = art.get("preview") or {}
        body = f"""
<div class="art-card" id="art-{_esc(art.get('artifact_id'))}">
  <div class="art-head">
    <div>
      <strong>{_esc(art.get('filename'))}</strong>
      <span class="muted">·  type=<code>{_esc(art.get('artifact_type'))}</code> ·  parser=<code>{_esc(art.get('parser_name'))}/{_esc(art.get('parser_version'))}</code></span>
    </div>
    <div class="muted">
      {_esc(art.get('atom_count', 0))} atoms ·
      {_esc(art.get('atoms_in_bundle', 0))} bundled ·
      {_esc(art.get('atoms_cited_by_brain', 0))} cited by brain ·
      <strong>{_esc(art.get('atoms_in_composed_brief', 0))} in brief</strong>
    </div>
  </div>
  <div class="cols sxs">
    <div class="art-preview">
      <div class="muted small">Source preview ({_esc(preview.get('kind') or 'raw')})</div>
      <pre>{_esc(preview.get('body') or '(no preview)')}</pre>
    </div>
    <div class="art-atoms">
      <div class="muted small">Extracted atoms</div>
      {atoms_html}
    </div>
  </div>
</div>
"""
        blocks.append(body)
    return _section("Source artifacts — raw vs extracted", "\n".join(blocks), anchor="artifacts")


def _atoms_table(atoms: list[dict]) -> str:
    if not atoms:
        return "<p class='muted'>(no atoms)</p>"
    rows = []
    for a in atoms:
        loc = a.get("locator") or {}
        loc_str = " ".join(f"{k}={v}" for k, v in loc.items() if v not in (None, ""))
        flags = []
        flags.append(_flag_badge("bundled", bool(a.get("in_bundle"))))
        flags.append(_flag_badge("brain", bool(a.get("cited_by_brain"))))
        flags.append(_flag_badge("brief", bool(a.get("in_composed_brief"))))
        rows.append(
            f"<tr>"
            f"<td><code class='aid'>{_esc(a.get('id'))}</code></td>"
            f"<td>{_esc(a.get('atom_type'))}</td>"
            f"<td>{_esc(a.get('authority_class'))}</td>"
            f"<td class='num'>{_esc(a.get('confidence'))}</td>"
            f"<td>{_esc(a.get('verified'))}</td>"
            f"<td><code>{_esc(loc_str)}</code></td>"
            f"<td>{_esc(a.get('text'))}</td>"
            f"<td>{''.join(flags)}</td>"
            f"</tr>"
        )
    return f"""
<table class="atoms">
  <thead><tr>
    <th>id</th><th>type</th><th>authority</th><th class='num'>conf</th><th>replay</th>
    <th>locator</th><th>text</th><th>downstream</th>
  </tr></thead>
  <tbody>{''.join(rows)}</tbody>
</table>
"""


def _graph_block(entities: list[dict], edges: list[dict]) -> str:
    ent_rows = "\n".join(
        f"<tr>"
        f"<td><code>{_esc(e.get('canonical_key'))}</code></td>"
        f"<td>{_esc(e.get('canonical_name'))}</td>"
        f"<td>{_esc(e.get('entity_type'))}</td>"
        f"<td><code>{_esc(', '.join(e.get('aliases') or []))}</code></td>"
        f"<td class='num'>{_esc(len(e.get('source_atom_ids') or []))}</td>"
        f"<td><code>{_esc(', '.join(e.get('artifact_ids') or []))}</code></td>"
        f"<td>{_esc(e.get('review_status'))}</td>"
        f"</tr>"
        for e in entities
    ) or "<tr><td colspan='7' class='muted'>(no entities)</td></tr>"

    by_type: dict[str, int] = {}
    for ed in edges:
        by_type[ed.get("edge_type", "?")] = by_type.get(ed.get("edge_type", "?"), 0) + 1
    edge_summary = ", ".join(
        f"<code>{_esc(t)}</code>×{c}" for t, c in sorted(by_type.items())
    ) or "<span class='muted'>(no edges)</span>"

    edge_rows = "\n".join(
        f"<tr>"
        f"<td><code>{_esc(e.get('edge_type'))}</code></td>"
        f"<td><code class='aid'>{_esc(e.get('from_atom_id'))}</code></td>"
        f"<td><code class='aid'>{_esc(e.get('to_atom_id'))}</code></td>"
        f"<td class='num'>{_esc(e.get('confidence'))}</td>"
        f"<td>{_esc(e.get('cross_artifact'))}</td>"
        f"<td>{_esc(e.get('reason'))}</td>"
        f"</tr>"
        for e in edges[:200]
    ) or "<tr><td colspan='6' class='muted'>(no edges)</td></tr>"
    edge_truncated = max(0, len(edges) - 200)
    edge_truncated_html = (
        f"<p class='muted'>… {edge_truncated} more edge(s) hidden (cap reached)</p>"
        if edge_truncated else ""
    )

    body = f"""
<div class="muted">{len(entities)} entities · {len(edges)} edges · types: {edge_summary}</div>
<h3 class="sub">Entities (cross-artifact identity normalization)</h3>
<table class="wide">
  <thead><tr><th>canonical_key</th><th>name</th><th>type</th><th>aliases</th><th class='num'>source atoms</th><th>artifacts</th><th>review status</th></tr></thead>
  <tbody>{ent_rows}</tbody>
</table>

<h3 class="sub">Edges (parser-os GNN structure)</h3>
<table class="wide">
  <thead><tr><th>edge_type</th><th>from_atom</th><th>to_atom</th><th class='num'>conf</th><th>cross-artifact</th><th>reason</th></tr></thead>
  <tbody>{edge_rows}</tbody>
</table>
{edge_truncated_html}
"""
    return _section("GNN graph — entities + edges", body, anchor="graph")


def _packets_block(packets: list[dict]) -> str:
    by_family: dict[str, int] = {}
    for p in packets:
        by_family[p.get("family", "?")] = by_family.get(p.get("family", "?"), 0) + 1
    family_summary = ", ".join(
        f"<code>{_esc(f)}</code>×{c}" for f, c in sorted(by_family.items())
    ) or "<span class='muted'>(no packets)</span>"

    rows = "\n".join(
        f"<tr>"
        f"<td><code>{_esc(p.get('id'))}</code></td>"
        f"<td><code>{_esc(p.get('family'))}</code></td>"
        f"<td>{_esc(p.get('anchor_key'))}</td>"
        f"<td class='num'>{_esc(p.get('confidence'))}</td>"
        f"<td><code class='aid'>{_esc(', '.join((p.get('governing_atom_ids') or [])[:4]))}</code></td>"
        f"<td>"
        f"{_flag_badge('bundled', (p.get('downstream') or {}).get('bundled', False))}"
        f"{_flag_badge('brain', (p.get('downstream') or {}).get('cited_by_brain', False))}"
        f"{_flag_badge('brief', (p.get('downstream') or {}).get('in_composed_brief', False))}"
        f"</td>"
        f"<td><code>{_esc(', '.join((p.get('downstream') or {}).get('cited_by_packs') or []))}</code></td>"
        f"</tr>"
        for p in packets
    ) or "<tr><td colspan='7' class='muted'>(no packets)</td></tr>"
    body = f"""
<div class="muted">{len(packets)} packet(s) · families: {family_summary}</div>
<table class="wide">
  <thead><tr><th>packet_id</th><th>family</th><th>anchor</th><th class='num'>conf</th><th>governing atoms</th><th>downstream</th><th>cited by packs</th></tr></thead>
  <tbody>{rows}</tbody>
</table>
"""
    return _section("Packet ledger — survival through the pipeline", body, anchor="packets")


def _brain_outputs_block(brain_items: dict, validations: dict, calibrations: dict) -> str:
    if not brain_items:
        return _section("Brain outputs", "<p class='muted'>(no brains ran for this engagement)</p>", anchor="brains")
    blocks: list[str] = []
    for pack, items in brain_items.items():
        val = validations.get(pack) or {}
        cal = calibrations.get(pack) or {}
        verdict_str = ", ".join(
            f"{k}={v}" for k, v in (cal.get("by_verdict_counts") or {}).items()
        ) or "—"
        rule_str = ", ".join(
            f"<code>{_esc(k)}</code>×{v}" for k, v in (val.get("rule_counts") or {}).items()
        ) or "(no rule firings)"

        item_rows = "\n".join(
            f"<tr>"
            f"<td>{_esc(it.get('section'))}</td>"
            f"<td><code>{_esc(it.get('id'))}</code></td>"
            f"<td>{_esc(it.get('statement'))}</td>"
            f"<td class='num'>{_esc(it.get('confidence'))}</td>"
            f"<td><code class='aid'>{_esc(', '.join(it.get('supporting_packet_ids') or []))}</code></td>"
            f"<td><code class='aid'>{_esc(', '.join(it.get('supporting_atom_ids') or []))}</code></td>"
            f"</tr>"
            for it in items
        ) or "<tr><td colspan='6' class='muted'>(no items emitted)</td></tr>"
        blocks.append(f"""
<div class="brain-card">
  <h3 class="sub">{_esc(pack)} brain</h3>
  <div class="muted">
    Validator: {_esc(val.get('passed_count', 0))} passed, {_esc(val.get('failed_count', 0))} failed,
    {_esc(val.get('blocker_count', 0))} blocker(s) — {rule_str}.
    Calibrator verdicts: {_esc(verdict_str)}.
    Mean calibrated confidence: {_esc(cal.get('mean_calibrated_confidence', '—'))}.
  </div>
  <table class="wide">
    <thead><tr><th>Section</th><th>id</th><th>Statement</th><th class='num'>conf</th><th>Packets</th><th>Atoms</th></tr></thead>
    <tbody>{item_rows}</tbody>
  </table>
</div>
""")
    return _section("Brain outputs — what each brain emitted", "\n".join(blocks), anchor="brains")


def _composed_summary_block(s: dict) -> str:
    if not s:
        return _section("Composed brief", "<p class='muted'>(no composed brief)</p>", anchor="composed")
    rows = "\n".join(
        f"<tr><td><code>{_esc(d.get('pack_id'))}</code></td>"
        f"<td>{_esc(d.get('brain'))}</td>"
        f"<td>{_flag_badge('fallback', bool(d.get('fallback_used')))}</td>"
        f"<td>{_esc(', '.join(f'{k}={v}' for k, v in (d.get('section_counts') or {}).items() if v))}</td></tr>"
        for d in (s.get("domains") or [])
    ) or "<tr><td colspan='4' class='muted'>(no domains)</td></tr>"
    body = f"""
<div class="muted">
  Domains: {_esc(s.get('domain_count', 0))} · Sites: {_esc(s.get('site_count', 0))} · Open questions: {_esc(s.get('open_question_count', 0))}
</div>
<div class="kpi">
  <div><strong class="ok">{_esc(s.get('auto_accept_count', 0))}</strong> auto-accept</div>
  <div><strong class="warn">{_esc(s.get('review_count', 0))}</strong> need review</div>
  <div><strong class="bad">{_esc(s.get('blocker_count', 0))}</strong> rejected</div>
</div>
<table class="wide">
  <thead><tr><th>pack</th><th>brain</th><th>status</th><th>section item counts</th></tr></thead>
  <tbody>{rows}</tbody>
</table>
"""
    return _section("Composed brief summary", body, anchor="composed")


def _review_queue_block(q: dict) -> str:
    body = f"""
<div class="kpi">
  <div><strong>{_esc(q.get('open_count', 0))}</strong> open in queue</div>
  <div><strong>{_esc(q.get('decided_count', 0))}</strong> decided</div>
  <div><strong>{_esc(q.get('decisions_logged', 0))}</strong> decisions logged → training</div>
</div>
"""
    return _section("Review queue", body, anchor="queue")


def _pipeline_log_block(log: list[dict]) -> str:
    rows = "\n".join(
        f"<tr><td><code>{_esc(r.get('stage'))}</code></td>"
        f"<td><span class='status status-{_esc(r.get('status'))}'>{_esc(r.get('status'))}</span></td>"
        f"<td class='num'>{_esc(r.get('duration_ms'))}</td>"
        f"<td><code>{_esc(json.dumps(r.get('detail') or {})[:200])}</code></td></tr>"
        for r in log
    ) or "<tr><td colspan='4' class='muted'>(no log)</td></tr>"
    body = f"""
<table class="wide">
  <thead><tr><th>Stage</th><th>Status</th><th class='num'>ms</th><th>Detail</th></tr></thead>
  <tbody>{rows}</tbody>
</table>
"""
    return _section("Pipeline log", body, anchor="pipeline")


# ────────────────────────────── chrome ─────────────────────────────────


_HEAD = """<!doctype html><html lang="en"><head>
<meta charset="utf-8">
<title>OrbitBrief inspection</title>
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
header { background: #0e1116; color: #fafbfc; padding: 18px 28px; border-bottom: 1px solid #000; }
header h1 { margin: 0 0 4px 0; font-size: 18px; font-weight: 600; }
header .muted { color: #8b94a3; font-size: 12px; }
header nav.anchors { margin-top: 10px; font-size: 12px; }
header nav.anchors a { color: #cdd6e0; margin-right: 12px; text-decoration: none; }
header nav.anchors a:hover { color: white; text-decoration: underline; }
main { max-width: 1280px; margin: 0 auto; padding: 24px; }
section { background: var(--card); border: 1px solid var(--border); border-radius: 6px; padding: 20px 24px; margin-bottom: 20px; }
section h2 { margin: 0 0 14px 0; font-size: 16px; font-weight: 600; padding-bottom: 8px; border-bottom: 1px solid var(--border); }
section h3.sub { margin: 18px 0 8px 0; font-size: 14px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; }
.muted { color: var(--muted); }
.muted.small { font-size: 12px; }
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.cols.sxs { grid-template-columns: 360px 1fr; gap: 18px; }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
table.wide { font-size: 12px; }
th, td { padding: 6px 8px; text-align: left; border-bottom: 1px solid var(--border); vertical-align: top; }
th { background: #f4f5f7; font-size: 11px; text-transform: uppercase; color: var(--muted); }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
code { background: #f4f5f7; padding: 1px 5px; border-radius: 3px; font-family: ui-monospace, SFMono-Regular, monospace; font-size: 11px; word-break: break-all; }
code.aid { color: var(--accent); }
pre { background: #f4f5f7; border: 1px solid var(--border); border-radius: 4px; padding: 10px 12px; overflow: auto; max-height: 460px; font-size: 11px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; }
.kpi { display: flex; gap: 18px; margin-top: 10px; flex-wrap: wrap; }
.kpi div { background: #f4f5f7; border-radius: 4px; padding: 6px 12px; }
.kpi strong { font-size: 16px; font-variant-numeric: tabular-nums; }
.kpi strong.ok { color: var(--ok); }
.kpi strong.warn { color: var(--warn); }
.kpi strong.bad { color: var(--bad); }
.flag { display: inline-block; padding: 1px 6px; border-radius: 10px; font-size: 10px; margin-right: 3px; font-weight: 600; text-transform: uppercase; }
.flag-on { background: rgba(44,138,77,0.15); color: var(--ok); }
.flag-off { background: #f4f5f7; color: var(--muted); opacity: 0.5; }
.art-card { border: 1px solid var(--border); border-radius: 4px; margin-bottom: 18px; padding: 14px 16px; }
.art-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 10px; }
table.atoms { font-size: 11px; }
table.atoms td { vertical-align: top; }
.brain-card { border: 1px solid var(--border); border-radius: 4px; margin-bottom: 16px; padding: 12px 16px; }
span.status { display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 11px; text-transform: uppercase; font-weight: 600; }
span.status-ok       { background: rgba(44,138,77,0.15); color: var(--ok); }
span.status-fallback { background: rgba(179,89,0,0.15); color: var(--warn); }
span.status-failed   { background: rgba(179,38,30,0.15); color: var(--bad); }
span.status-skipped  { background: #f4f5f7; color: var(--muted); }
</style>
</head>
<body>
<main>
"""
