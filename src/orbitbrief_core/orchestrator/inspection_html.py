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


def render_inspection_html(report: dict[str, Any], pm_handoff: dict[str, Any] | None = None) -> str:
    project = report.get("project_id") or "?"
    compile_id = report.get("compile_id") or "?"
    funnel = report.get("funnel") or {}
    manifest = report.get("manifest") or {}
    parts: list[str] = []
    parts.append(_HEAD)
    parts.append(_header_block(project, compile_id, funnel, report, has_pm=bool(pm_handoff)))
    # PM final layer first — the audience that opens this page first
    # is usually a PM, not an engineer. The engineering inspection
    # follows below for substrate-level audit.
    if pm_handoff:
        parts.append(_pm_handoff_block(pm_handoff))
    parts.append(_funnel_block(funnel))
    parts.append(_verification_block(report.get("verification") or {}))
    parts.append(_pack_prior_block(report.get("pack_prior") or {}))
    parts.append(_site_reality_block(report.get("site_reality") or {}))
    parts.append(_artifacts_block(report.get("artifacts") or []))
    parts.append(_graph_block(report.get("entities") or [], report.get("edges") or []))
    parts.append(_packets_block(report.get("packets") or []))
    parts.append(_brain_outputs_block(report.get("brain_items") or {}, report.get("validations") or {}, report.get("calibrations") or {}, manifest))
    parts.append(_composed_summary_block(report.get("composed_brief_summary") or {}, manifest))
    parts.append(_review_queue_block(report.get("review_queue") or {}, manifest))
    parts.append(_pipeline_log_block(report.get("pipeline_log") or [], manifest))
    parts.append("</main></body></html>")
    return "\n".join(parts)


def _run_mode(manifest: dict[str, Any]) -> dict[str, Any]:
    """Derive a simple run-mode descriptor from the manifest.

    Returns a dict with ``mode`` (``"llm"`` | ``"substrate"`` | ``"unknown"``),
    a short human label, and a ``reason`` explaining why brains may be empty.
    """
    skipped = bool(manifest.get("skipped_brains_no_chat"))
    brains_run = list(manifest.get("brains_run") or [])
    active_packs = list(manifest.get("active_packs") or [])
    if skipped:
        return {
            "mode": "substrate",
            "label": "Substrate-only run (no LLM)",
            "css": "warn",
            "reason": (
                "This engagement was compiled without an Ollama chat client, "
                "so stages 30/40/60 (planner / brains / calibrator) were skipped "
                "by design. The deterministic substrate (parser-os, pack prior, "
                "site reality, validator, PM handoff) still ran. "
                "Re-run with <code>--ollama --chat-model qwen3:14b</code> to populate brains."
            ),
        }
    if brains_run:
        return {
            "mode": "llm",
            "label": f"LLM run · brains: {', '.join(brains_run)}",
            "css": "ok",
            "reason": "",
        }
    if active_packs:
        return {
            "mode": "llm",
            "label": "LLM run · brains attempted but emitted no items",
            "css": "warn",
            "reason": (
                "Chat client was wired and packs were active, but no brain emitted any items "
                "for this engagement. Check pack prior confidence, retrieval bundles, and the "
                "brain stage entries in <code>pipeline_log.json</code>."
            ),
        }
    return {
        "mode": "unknown",
        "label": "Run mode: unknown",
        "css": "muted",
        "reason": "",
    }


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


def _header_block(project: str, compile_id: str, funnel: dict, report: dict, has_pm: bool = False) -> str:
    rb = report.get("refined_brief") or {}
    manifest = report.get("manifest") or {}
    pm_anchor = '<a href="#pm-handoff" class="pm-anchor">PM handoff</a>' if has_pm else ""
    mode = _run_mode(manifest)
    planner_model = rb.get("model_used") or ("substrate-only" if mode["mode"] == "substrate" else "—")
    planner_tier = rb.get("tier") or ("—" if mode["mode"] != "substrate" else "n/a")
    total_tokens = (rb.get("token_cost") or {}).get("total_tokens")
    if total_tokens in (None, ""):
        total_tokens = "0" if mode["mode"] == "substrate" else "—"
    mode_badge = (
        f'<span class="mode-badge mode-{mode["css"]}">{_esc(mode["label"])}</span>'
    )
    return f"""
<header>
  <h1>OrbitBrief inspection — <code>{_esc(project)}</code></h1>
  <div class="muted">
    Compile <code>{_esc(compile_id)}</code> ·
    Generated <code>{_esc(manifest.get("generated_at") or "?")}</code> ·
    Planner model <code>{_esc(planner_model)}</code>
    ({_esc(planner_tier)}) ·
    Total tokens <code>{_esc(total_tokens)}</code>
    &nbsp;{mode_badge}
  </div>
  <nav class="anchors">
    {pm_anchor}
    <a href="#funnel">Funnel</a>
    <a href="#verification">Verification</a>
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


def _pm_handoff_block(handoff: dict) -> str:
    """Render the PM final layer as the first section of the
    inspection page. Reads a ``PMHandoff.to_dict()`` payload."""
    status = (handoff.get("status") or "unknown").lower()
    status_label = handoff.get("status_label") or status.upper()
    status_emoji = {"red": "🔴", "yellow": "🟡", "green": "🟢"}.get(status, "⚪")
    status_cls = f"pm-status pm-status-{status}"
    summary = handoff.get("one_line_summary") or ""
    metrics = handoff.get("metrics") or {}

    metric_rows = "\n".join(
        f"<tr><td>{_esc(label)}</td><td class='num'>{_esc(metrics.get(key, '—'))}</td></tr>"
        for label, key in [
            ("Source files read", "source_files_read"),
            ("Evidence items extracted", "evidence_items_extracted"),
            ("Confirmed physical sites", "confirmed_physical_sites"),
            ("SOW blocker questions", "sow_blocker_questions"),
            ("SOW warning questions", "sow_warning_questions"),
            ("Top workstream", "top_workstream"),
        ]
    )

    sites = handoff.get("sites") or []
    if sites:
        site_rows = "\n".join(
            f"<tr><td>{_esc(s.get('name'))}</td>"
            f"<td><code>{_esc(s.get('kind'))}</code></td>"
            f"<td>{'✓' if s.get('publishable') else '✗'}</td>"
            f"<td class='num'>{_esc(s.get('member_evidence_count'))}</td>"
            f"<td class='num'>{_esc(s.get('artifact_count'))}</td></tr>"
            for s in sites
        )
        sites_table = f"""
<table>
  <thead><tr><th>Site</th><th>Kind</th><th>Confirmed</th><th class='num'>Evidence items</th><th class='num'>Source files</th></tr></thead>
  <tbody>{site_rows}</tbody>
</table>"""
    else:
        sites_table = '<p class="muted">No publishable physical-site cluster.</p>'

    domains = handoff.get("domains") or []
    if domains:
        dom_rows = "\n".join(
            f"<tr><td>{_esc(d.get('label'))}</td>"
            f"<td>{'✓' if d.get('routed') else ''}</td>"
            f"<td>{'✓' if d.get('sow_active') else ''}</td>"
            f"<td class='num'>{_esc(d.get('blockers'))}</td>"
            f"<td class='num'>{_esc(d.get('warnings'))}</td></tr>"
            for d in domains
        )
        dom_table = f"""
<table>
  <thead><tr><th>Workstream</th><th>Routed?</th><th>SOW active?</th><th class='num'>Blockers</th><th class='num'>Warnings</th></tr></thead>
  <tbody>{dom_rows}</tbody>
</table>"""
    else:
        dom_table = '<p class="muted">No detected workstreams.</p>'

    gaps = handoff.get("gaps") or []
    blockers = [g for g in gaps if g.get("severity") == "blocker"]
    warnings = [g for g in gaps if g.get("severity") == "warning"]

    def _gap_li(g: dict) -> str:
        return (
            f"<li><strong>{_esc(g.get('domain_label') or g.get('domain_id'))} — "
            f"{_esc(g.get('label'))}:</strong> "
            f"{_esc(g.get('customer_question') or g.get('message'))}</li>"
        )

    blockers_html = (
        "<ul>" + "".join(_gap_li(g) for g in blockers) + "</ul>"
        if blockers
        else '<p class="muted">No blocker SOW questions.</p>'
    )
    warnings_html = (
        f"<details><summary>{len(warnings)} warning question(s) to clarify</summary>"
        f"<ul>" + "".join(_gap_li(g) for g in warnings) + "</ul></details>"
        if warnings
        else ""
    )

    body = f"""
<div class="{status_cls}">
  <div class="pm-banner">{status_emoji} {_esc(status_label)}</div>
  <div class="pm-summary">{_esc(summary)}</div>
  <div class="pm-links">
    <a href="PM_EXECUTIVE_SUMMARY.html">📄 PM Executive Summary</a>
    <a href="SA_REVIEW_PACKET.html">🛠️ Solution Architect Packet</a>
    <a href="PM_HANDOFF.html">🔗 Combined PM Handoff</a>
    <a href="PM_HANDOFF.json">{{ }} JSON payload</a>
  </div>
</div>

<h3 class="sub">PM scorecard</h3>
<table style="max-width: 520px;">
  <tbody>{metric_rows}</tbody>
</table>

<h3 class="sub">Confirmed physical sites</h3>
{sites_table}

<h3 class="sub">Detected workstreams</h3>
{dom_table}

<h3 class="sub">Must-resolve customer questions ({len(blockers)})</h3>
{blockers_html}
{warnings_html}
"""
    return _section("PM final layer — what the PM sees first", body, anchor="pm-handoff")


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


def _brain_outputs_block(brain_items: dict, validations: dict, calibrations: dict, manifest: dict | None = None) -> str:
    if not brain_items:
        mode = _run_mode(manifest or {})
        if mode["mode"] == "substrate":
            body = (
                f'<div class="empty-state">'
                f'<p><strong>Substrate-only run — LLM brains intentionally skipped.</strong></p>'
                f'<p class="muted">{mode["reason"]}</p>'
                f'<pre>PYTHONPATH=src python3 compile_brief.py &lt;case_dir&gt; \\\n'
                f'  --out &lt;out_dir&gt; --ollama \\\n'
                f'  --ollama-base-url http://localhost:11434 \\\n'
                f'  --chat-model qwen3:14b</pre>'
                f'</div>'
            )
        elif mode["mode"] == "llm":
            body = (
                '<div class="empty-state">'
                '<p><strong>Brains ran but emitted no items.</strong></p>'
                f'<p class="muted">{mode["reason"]}</p>'
                '</div>'
            )
        else:
            body = "<p class='muted'>(no brains ran for this engagement)</p>"
        return _section("Brain outputs", body, anchor="brains")
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


def _verification_block(v: dict) -> str:
    """Render the parser-os verified-status rollup.

    Surfaced near the top so reviewers see corpus-level parser health
    before they start clicking through individual atoms. The "top
    failed artifacts" table is the operator's first lead when the
    parser starts drifting on a customer's PDF/XLSX format.
    """
    if not v or not v.get("atom_total"):
        body = "<p class='muted'>(no verification telemetry — envelope had no atoms)</p>"
        return _section("Source verification", body, anchor="verification")
    health_pct = float(v.get("health_pct") or 0.0)
    failed = int(v.get("failed_count") or 0)
    partial = int(v.get("partial_count") or 0)
    verified = int(v.get("verified_count") or 0)
    unverified = int(v.get("unverified_count") or 0)
    unsupported = int(v.get("unsupported_count") or 0)
    total = int(v.get("atom_total") or 0)
    if health_pct >= 95:
        css, label = "ok", f"{health_pct:.1f}% atoms replayed clean"
    elif health_pct >= 80:
        css, label = "warn", f"{health_pct:.1f}% atoms replayed clean — look closely"
    else:
        css, label = "bad", (
            f"{health_pct:.1f}% atoms replayed clean — parser regression suspected"
        )
    badge = (
        f'<span class="mode-badge mode-{css}">{_esc(label)}</span>'
    )
    top_rows = "\n".join(
        f"<tr><td>{_esc(r.get('filename') or r.get('artifact_id'))}</td>"
        f"<td>{_esc(r.get('artifact_type'))}</td>"
        f"<td class='num'>{_esc(r.get('failed_atoms'))}</td>"
        f"<td class='num'>{_esc(r.get('atom_count'))}</td>"
        f"<td><code class='aid'>{_esc(r.get('artifact_id'))}</code></td></tr>"
        for r in (v.get("top_failed_artifacts") or [])
    ) or "<tr><td colspan='5' class='muted'>(no failed atoms — parser is clean on this corpus)</td></tr>"
    body = f"""
<div style="margin-bottom: 8px;">{badge}</div>
<div class="kpi">
  <div><strong class="ok">{_esc(verified)}</strong> verified</div>
  <div><strong class="bad">{_esc(failed)}</strong> failed</div>
  <div><strong class="warn">{_esc(partial)}</strong> partial</div>
  <div><strong>{_esc(unverified)}</strong> unverified</div>
  <div><strong>{_esc(unsupported)}</strong> unsupported</div>
  <div class="muted">{_esc(total)} atoms total</div>
</div>
<h3 class="sub">Top artifacts by failed-atom count</h3>
<table class="wide">
  <thead><tr><th>Filename</th><th>Type</th><th class='num'>Failed</th><th class='num'>Total atoms</th><th>Artifact id</th></tr></thead>
  <tbody>{top_rows}</tbody>
</table>
<p class="muted small">
  <strong>How to read this:</strong> parser-os tags every extracted atom with a
  <code>verified</code> status by replaying the source bytes. <code>failed</code> means
  the bytes drifted from what was extracted (likely parser regression on this
  artifact). Click into the artifact row in the &quot;Source artifacts&quot; section
  below to see which specific atoms failed.
</p>
"""
    return _section("Source verification — parser-os atom replay", body, anchor="verification")


def _composed_summary_block(s: dict, manifest: dict | None = None) -> str:
    if not s:
        mode = _run_mode(manifest or {})
        if mode["mode"] == "substrate":
            body = (
                '<div class="empty-state">'
                '<p><strong>No composed brief — substrate-only run.</strong></p>'
                f'<p class="muted">{mode["reason"]}</p>'
                '</div>'
            )
        else:
            body = "<p class='muted'>(no composed brief)</p>"
        return _section("Composed brief", body, anchor="composed")
    mode = _run_mode(manifest or {})
    domains_list = s.get("domains") or []
    empty_domain_msg = (
        "(no domains — substrate-only run; no brains were composed)"
        if (not domains_list and mode["mode"] == "substrate")
        else "(no domains)"
    )
    rows = "\n".join(
        f"<tr><td><code>{_esc(d.get('pack_id'))}</code></td>"
        f"<td>{_esc(d.get('brain'))}</td>"
        f"<td>{_flag_badge('fallback', bool(d.get('fallback_used')))}</td>"
        f"<td>{_esc(', '.join(f'{k}={v}' for k, v in (d.get('section_counts') or {}).items() if v))}</td></tr>"
        for d in domains_list
    ) or f"<tr><td colspan='4' class='muted'>{_esc(empty_domain_msg)}</td></tr>"
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


def _review_queue_block(q: dict, manifest: dict | None = None) -> str:  # noqa: ARG001 - reserved for future banner
    body = f"""
<div class="kpi">
  <div><strong>{_esc(q.get('open_count', 0))}</strong> open in queue</div>
  <div><strong>{_esc(q.get('decided_count', 0))}</strong> decided</div>
  <div><strong>{_esc(q.get('decisions_logged', 0))}</strong> decisions logged → training</div>
</div>
"""
    return _section("Review queue", body, anchor="queue")


def _pipeline_log_block(log: list[dict], manifest: dict | None = None) -> str:
    if not log:
        mode = _run_mode(manifest or {})
        empty_msg = (
            "(no log — pipeline_log.json was empty for this engagement; "
            "this usually means the orchestrator wasn't run, or the bundle "
            "was assembled from partial outputs)"
            if mode["mode"] != "substrate"
            else "(no log — substrate-only run; pipeline_log.json should still exist on disk under the case out_dir)"
        )
        body = f"""
<table class="wide">
  <thead><tr><th>Stage</th><th>Status</th><th class='num'>ms</th><th>Detail</th></tr></thead>
  <tbody><tr><td colspan='4' class='muted'>{_esc(empty_msg)}</td></tr></tbody>
</table>
"""
        return _section("Pipeline log", body, anchor="pipeline")
    # Stage-status totals up top so reviewers see ok/skipped/fallback at a glance.
    counts: dict[str, int] = {}
    total_ms = 0
    for r in log:
        st = str(r.get("status") or "?")
        counts[st] = counts.get(st, 0) + 1
        try:
            total_ms += int(r.get("duration_ms") or 0)
        except (TypeError, ValueError):
            pass
    kpi_chunks = " · ".join(
        f"<span class='status status-{_esc(k)}'>{_esc(k)}</span>×{_esc(v)}"
        for k, v in counts.items()
    )
    rows = "\n".join(
        f"<tr><td><code>{_esc(r.get('stage'))}</code></td>"
        f"<td><span class='status status-{_esc(r.get('status'))}'>{_esc(r.get('status'))}</span></td>"
        f"<td class='num'>{_esc(r.get('duration_ms'))}</td>"
        f"<td><code>{_esc(json.dumps(r.get('detail') or {})[:200])}</code></td></tr>"
        for r in log
    )
    body = f"""
<div class="muted" style="margin-bottom: 8px;">
  {len(log)} stages · total {total_ms} ms · {kpi_chunks}
</div>
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

/* Run-mode badge in the header. */
.mode-badge { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; vertical-align: middle; }
.mode-ok    { background: rgba(44,138,77,0.20); color: #6ee7a3; }
.mode-warn  { background: rgba(179,89,0,0.25); color: #ffd591; }
.mode-bad   { background: rgba(179,38,30,0.25); color: #ff9e94; }
.mode-muted { background: #2d333b; color: #cdd6e0; }

/* Empty-state callouts (e.g. no brains because substrate-only). */
.empty-state { background: #fffaeb; border: 1px solid #f0d27a; border-radius: 6px; padding: 12px 16px; }
.empty-state p { margin: 0 0 6px 0; }
.empty-state pre { background: #fff; border: 1px solid #f0d27a; margin-top: 8px; }

/* PM final-layer block */
header nav.anchors a.pm-anchor { color: #fff; background: #1f6feb; padding: 2px 8px; border-radius: 4px; font-weight: 600; }
.pm-status { border-radius: 6px; padding: 14px 18px; margin-bottom: 14px; border: 1px solid; display: flex; flex-direction: column; gap: 8px; }
.pm-status-red    { background: #fff5f5; border-color: #f1b0a8; }
.pm-status-yellow { background: #fffaeb; border-color: #f0d27a; }
.pm-status-green  { background: #f1fbf3; border-color: #95d4a8; }
.pm-status .pm-banner { font-size: 18px; font-weight: 700; }
.pm-status-red    .pm-banner { color: var(--bad); }
.pm-status-yellow .pm-banner { color: var(--warn); }
.pm-status-green  .pm-banner { color: var(--ok); }
.pm-status .pm-summary { color: #333; font-size: 13px; }
.pm-status .pm-links { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 4px; }
.pm-status .pm-links a {
  background: #fff; border: 1px solid var(--border); padding: 6px 10px; border-radius: 4px;
  text-decoration: none; color: var(--accent); font-weight: 600; font-size: 12px;
}
.pm-status .pm-links a:hover { background: var(--accent); color: #fff; border-color: var(--accent); }
section ul li { margin: 4px 0; }
section details summary { cursor: pointer; font-weight: 600; color: var(--muted); margin: 12px 0 6px; }
</style>
</head>
<body>
<main>
"""
