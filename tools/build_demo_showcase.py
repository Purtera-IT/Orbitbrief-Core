#!/usr/bin/env python3
"""build_demo_showcase.py — generate a single-file boss demo HTML.

Reads a completed pm_handoff.sh output directory + the original case
directory, picks compelling examples from the run, and emits a
self-contained ``BOSS_DEMO.html`` that walks a non-technical exec
through the whole pipeline in one scroll.

The story arc:

    1. Hero — what we did, in one breath.
    2. Input — the raw customer files.
    3. Parser-os — N atomic facts extracted (with hand-picked examples).
    4. Knowledge graph — entities + edges as inline SVG.
    5. Pack prior — which AI specialists woke up for this case.
    6. Brain outputs — best items per active brain.
    7. PM handoff — the executive verdict.
    8. By the numbers — wall-clock, parser health, etc.

Usage::

    python3 tools/build_demo_showcase.py \\
        --out-dir /tmp/COPPER_001_demo \\
        --case-dir /Users/.../parser-os-repo/real_data_cases/COPPER_001_SPRING_LAKE_AUDITORIUM \\
        --runtime-s 251

The script is self-contained — no third-party deps. The output HTML
is also self-contained (inline CSS + inline SVG). Open it locally or
hand the file to anyone via email.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# ────────────────────────────── data loaders ───────────────────────────


def _safe_load(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _esc(s: Any) -> str:
    return html.escape(str(s)) if s is not None else ""


def _fmt_int(n: Any) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


def _shorten(s: str, n: int) -> str:
    s = (s or "").strip()
    s = " ".join(s.split())
    return (s[: n - 1] + "…") if len(s) > n else s


# ────────────────────────────── content selection ──────────────────────


# These are the atom types that are most "wow" for a non-technical
# reader — they map cleanly to natural-language stories ("we counted
# things, we caught exclusions, we found vendor parts, we noticed an
# unanswered question").
_HEADLINE_ATOM_TYPES: tuple[tuple[str, str, str], ...] = (
    ("quantity", "Counted things", "tag-quant"),
    ("exclusion", "Caught what's NOT included", "tag-excl"),
    ("vendor_line_item", "Identified vendor parts", "tag-vendor"),
    ("open_question", "Flagged unanswered questions", "tag-question"),
    ("customer_instruction", "Captured customer directives", "tag-direct"),
    ("constraint", "Surfaced binding constraints", "tag-constraint"),
    ("decision", "Recorded settled decisions", "tag-decision"),
    ("compliance", "Linked compliance standards", "tag-compliance"),
)


def _pick_headline_atoms(envelope: dict[str, Any]) -> list[dict[str, Any]]:
    """Return one best-in-class atom per headline atom_type."""
    atoms = envelope.get("atoms") or []
    by_type: dict[str, list[dict[str, Any]]] = {}
    for a in atoms:
        t = a.get("atom_type")
        if not t:
            continue
        by_type.setdefault(t, []).append(a)
    picked: list[dict[str, Any]] = []
    for atom_type, label, css in _HEADLINE_ATOM_TYPES:
        candidates = by_type.get(atom_type) or []
        # Sort by confidence descending, then text length (richer text
        # tends to be more interesting demo material).
        candidates.sort(
            key=lambda a: (-(a.get("confidence") or 0.0), -len(a.get("text") or "")),
        )
        for c in candidates:
            text = (c.get("text") or "").strip()
            if 30 <= len(text) <= 360:
                picked.append({**c, "_label": label, "_css": css})
                break
    return picked[:6]


def _pick_brain_highlights(brain_outputs: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """For each brain, pick 3 highest-confidence items across non-empty sections."""
    sections = (
        "scope_overview",
        "detailed_scope_of_services",
        "deliverables",
        "assumptions",
        "customer_responsibilities",
        "out_of_scope",
        "risks_or_dependencies",
        "completion_criteria",
        "open_items",
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for pack, data in brain_outputs.items():
        pool: list[dict[str, Any]] = []
        for section in sections:
            for item in data.get(section) or []:
                stmt = (item.get("statement") or "").strip()
                if 40 <= len(stmt) <= 400:
                    pool.append({"section": section, **item})
        pool.sort(key=lambda i: -(i.get("confidence") or 0.0))
        out[pack] = pool[:3]
    return out


# ────────────────────────────── GNN graph ──────────────────────────────


# Color palette per entity type, with a fallback. Picked to feel
# bright on a dark canvas without being garish.
_ENTITY_COLORS: dict[str, str] = {
    "site": "#5BE3C5",
    "part_number": "#F472B6",
    "manufacturer": "#FB923C",
    "vendor": "#FB923C",
    "person": "#A78BFA",
    "organization": "#60A5FA",
    "compliance_standard": "#FACC15",
    "vendor_part": "#F472B6",
    "addendum": "#94A3B8",
    "document": "#94A3B8",
    "open_question": "#EF4444",
    "_default": "#7DD3FC",
}


def _color_for_entity(ent: dict[str, Any]) -> str:
    t = (ent.get("entity_type") or "").lower()
    if t in _ENTITY_COLORS:
        return _ENTITY_COLORS[t]
    # Fallback: hash by first letter for stable but distinct hue.
    return _ENTITY_COLORS["_default"]


@dataclass
class _GraphNode:
    id: str
    label: str
    color: str
    radius: float
    x: float = 0.0
    y: float = 0.0


def _build_graph_svg(
    entities: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    width: int = 920,
    height: int = 540,
    max_nodes: int = 48,
) -> tuple[str, dict[str, int]]:
    """Render a deterministic force-directed-ish graph as inline SVG.

    Picks the most-connected entities up to ``max_nodes`` so the visual
    is dense but readable. Layout uses concentric rings grouped by
    entity_type with a tiny jitter so the result feels alive without
    needing an actual physics simulation.

    Returns (svg_string, type_counts) — type_counts powers the legend.
    """
    if not entities:
        return ("<svg></svg>", {})

    # Connectivity-rank entities so the picked subset shows real hubs.
    edge_count: dict[str, int] = {}
    for e in edges:
        for end in (e.get("source"), e.get("target"), e.get("from"), e.get("to")):
            if end:
                edge_count[end] = edge_count.get(end, 0) + 1
    ranked = sorted(
        entities,
        key=lambda x: -edge_count.get(x.get("id") or "", 0),
    )
    picked = ranked[:max_nodes]
    picked_ids = {e.get("id") for e in picked}

    # Group by entity type for ring placement.
    by_type: dict[str, list[dict[str, Any]]] = {}
    for ent in picked:
        t = (ent.get("entity_type") or "other").lower()
        by_type.setdefault(t, []).append(ent)
    type_counts = {t: len(v) for t, v in by_type.items()}

    # Layout: outer ring per type, slight jitter on radius for organic feel.
    cx, cy = width / 2.0, height / 2.0
    nodes: dict[str, _GraphNode] = {}
    rng = random.Random(42)
    type_order = sorted(by_type, key=lambda t: -len(by_type[t]))
    n_types = max(1, len(type_order))
    for ti, etype in enumerate(type_order):
        ring_r = 90 + ti * (min(width, height) * 0.18)
        ring_r = min(ring_r, min(cx, cy) - 30)
        ents_in = by_type[etype]
        n = max(1, len(ents_in))
        # Phase offset per ring so rings don't all align at 12 o'clock.
        phase = (ti / n_types) * math.pi * 0.7
        for i, ent in enumerate(ents_in):
            theta = phase + (2 * math.pi * i / n)
            jitter_r = rng.uniform(-12, 12)
            x = cx + (ring_r + jitter_r) * math.cos(theta)
            y = cy + (ring_r + jitter_r) * math.sin(theta)
            label = (
                ent.get("canonical_name")
                or ent.get("canonical_key")
                or ent.get("id")
                or "?"
            )
            label = _shorten(str(label), 28)
            radius = 4 + min(8, edge_count.get(ent.get("id") or "", 0) * 0.3)
            nodes[ent.get("id") or ""] = _GraphNode(
                id=ent.get("id") or "?",
                label=label,
                color=_color_for_entity(ent),
                radius=radius,
                x=x,
                y=y,
            )

    # Edges between picked nodes only — keep the visual digestible.
    edge_lines: list[str] = []
    for e in edges:
        s = e.get("source") or e.get("from")
        t = e.get("target") or e.get("to")
        if s in nodes and t in nodes and s != t:
            ns, nt = nodes[s], nodes[t]
            edge_lines.append(
                f'<line x1="{ns.x:.1f}" y1="{ns.y:.1f}" '
                f'x2="{nt.x:.1f}" y2="{nt.y:.1f}" '
                f'stroke="rgba(125,211,252,0.10)" stroke-width="0.6"/>'
            )
    # Cap the edge count to keep file size reasonable.
    if len(edge_lines) > 600:
        edge_lines = edge_lines[:600]

    # Nodes (drawn last so they sit on top of the edge spaghetti).
    node_circles: list[str] = []
    node_labels: list[str] = []
    for n in nodes.values():
        node_circles.append(
            f'<circle cx="{n.x:.1f}" cy="{n.y:.1f}" r="{n.radius:.1f}" '
            f'fill="{n.color}" stroke="rgba(255,255,255,0.5)" stroke-width="0.6">'
            f'<title>{_esc(n.label)} — {_esc(n.id)}</title></circle>'
        )
        # Only label the larger (more connected) nodes to avoid clutter.
        if n.radius >= 6.5:
            node_labels.append(
                f'<text x="{n.x + n.radius + 3:.1f}" y="{n.y + 3:.1f}" '
                f'fill="rgba(229,231,235,0.85)" font-size="9" '
                f'font-family="ui-monospace, SFMono-Regular, monospace">'
                f'{_esc(n.label)}</text>'
            )

    svg = (
        f'<svg viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="Knowledge graph of extracted entities and their relationships">'
        f'<rect x="0" y="0" width="{width}" height="{height}" '
        f'fill="rgba(15,23,42,0.55)" rx="12"/>'
        + "".join(edge_lines)
        + "".join(node_circles)
        + "".join(node_labels)
        + "</svg>"
    )
    return svg, type_counts


# ────────────────────────────── HTML rendering ─────────────────────────


_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OrbitBrief — Live Demo</title>
<style>
:root {
  --bg-0: #05060a;
  --bg-1: #0b1020;
  --bg-2: #11172a;
  --fg: #e5e7eb;
  --muted: #94a3b8;
  --accent: #5be3c5;
  --accent-2: #a78bfa;
  --accent-3: #f472b6;
  --warn: #facc15;
  --bad: #ef4444;
  --good: #22d3ee;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: var(--bg-0); color: var(--fg);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  line-height: 1.55; -webkit-font-smoothing: antialiased; }
a { color: var(--accent); }
.container { max-width: 1180px; margin: 0 auto; padding: 0 28px; }
.hero {
  background:
    radial-gradient(1200px 600px at 80% -10%, rgba(167,139,250,0.25), transparent 60%),
    radial-gradient(1000px 600px at -10% 100%, rgba(91,227,197,0.18), transparent 60%),
    linear-gradient(180deg, #060a18 0%, #050810 100%);
  padding: 80px 0 64px 0; border-bottom: 1px solid rgba(148,163,184,0.10);
}
.hero h1 { font-size: 56px; line-height: 1.05; margin: 0 0 18px 0; font-weight: 800;
  letter-spacing: -0.02em;
  background: linear-gradient(90deg, #ffffff 0%, #c7f9ec 60%, #d8b4fe 100%);
  -webkit-background-clip: text; background-clip: text; color: transparent; }
.hero .eyebrow { color: var(--accent); font-weight: 700; letter-spacing: 0.18em;
  text-transform: uppercase; font-size: 12px; margin-bottom: 20px; }
.hero .lede { color: #cbd5e1; max-width: 780px; font-size: 19px; }
.hero .stats { margin-top: 48px; display: grid; gap: 16px;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); }
.hero .stat { background: rgba(15,23,42,0.55); border: 1px solid rgba(148,163,184,0.18);
  border-radius: 14px; padding: 22px 20px; backdrop-filter: blur(10px); }
.hero .stat .num { font-size: 38px; font-weight: 800; line-height: 1;
  background: linear-gradient(180deg, #ffffff, #a7f3d0); -webkit-background-clip: text;
  background-clip: text; color: transparent; }
.hero .stat .lab { color: var(--muted); font-size: 12px; text-transform: uppercase;
  letter-spacing: 0.1em; margin-top: 8px; }

section.act { padding: 88px 0 24px 0; border-top: 1px solid rgba(148,163,184,0.08); }
section.act .label { color: var(--accent); font-weight: 700; letter-spacing: 0.16em;
  text-transform: uppercase; font-size: 11px; margin-bottom: 10px; }
section.act h2 { font-size: 36px; line-height: 1.15; margin: 0 0 14px 0; font-weight: 700;
  letter-spacing: -0.01em; }
section.act .sub { color: var(--muted); font-size: 16px; max-width: 820px; margin-bottom: 36px; }

.cards { display: grid; gap: 18px; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }
.card {
  background: linear-gradient(180deg, rgba(17,23,42,0.85), rgba(11,16,32,0.85));
  border: 1px solid rgba(148,163,184,0.16); border-radius: 16px; padding: 22px;
  position: relative; overflow: hidden;
}
.card .tag { display: inline-block; padding: 3px 10px; border-radius: 999px;
  font-size: 10.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em;
  margin-bottom: 12px; }
.tag-quant { background: rgba(34,211,238,0.15); color: var(--good); }
.tag-excl { background: rgba(239,68,68,0.15); color: var(--bad); }
.tag-vendor { background: rgba(244,114,182,0.15); color: var(--accent-3); }
.tag-question { background: rgba(250,204,21,0.15); color: var(--warn); }
.tag-direct { background: rgba(167,139,250,0.15); color: var(--accent-2); }
.tag-constraint { background: rgba(96,165,250,0.15); color: #60A5FA; }
.tag-decision { background: rgba(91,227,197,0.15); color: var(--accent); }
.tag-compliance { background: rgba(250,204,21,0.15); color: var(--warn); }
.card .quote { font-size: 14.5px; color: #e5e7eb; line-height: 1.55; }
.card .meta { color: var(--muted); font-size: 11.5px; margin-top: 14px;
  border-top: 1px solid rgba(148,163,184,0.10); padding-top: 10px;
  font-family: ui-monospace, SFMono-Regular, monospace; }
.card .label { color: var(--muted); font-weight: 600; font-size: 11px;
  text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 8px; }

.files { list-style: none; padding: 0; margin: 0; display: grid; gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
.file { display: flex; align-items: flex-start; gap: 14px;
  background: rgba(17,23,42,0.6); border: 1px solid rgba(148,163,184,0.14);
  border-radius: 14px; padding: 16px 18px; }
.file .ico { font-size: 22px; line-height: 1; padding-top: 2px; opacity: 0.9; }
.file .name { font-weight: 600; }
.file .desc { color: var(--muted); font-size: 12.5px; margin-top: 2px; }

.graph-wrap { margin-top: 8px; border: 1px solid rgba(148,163,184,0.14);
  border-radius: 16px; overflow: hidden; background: linear-gradient(180deg, #0a1020, #060a18); }
.graph-legend { display: flex; flex-wrap: wrap; gap: 14px; padding: 14px 18px;
  border-top: 1px solid rgba(148,163,184,0.10); color: var(--muted); font-size: 12px; }
.graph-legend .swatch { display: inline-block; width: 10px; height: 10px;
  border-radius: 50%; vertical-align: middle; margin-right: 6px; }

.brain-block { background: rgba(11,16,32,0.65); border: 1px solid rgba(148,163,184,0.16);
  border-radius: 16px; padding: 22px 24px; margin-bottom: 18px; }
.brain-block .head { display: flex; flex-wrap: wrap; align-items: center; gap: 12px;
  margin-bottom: 14px; padding-bottom: 12px;
  border-bottom: 1px solid rgba(148,163,184,0.10); }
.brain-block .head h3 { margin: 0; font-size: 18px; font-weight: 700; }
.brain-block .head .pill { font-size: 11px; padding: 4px 10px; border-radius: 999px;
  background: rgba(91,227,197,0.15); color: var(--accent); font-weight: 700;
  letter-spacing: 0.06em; text-transform: uppercase; }
.brain-block .head .meta { color: var(--muted); font-size: 12px;
  font-family: ui-monospace, SFMono-Regular, monospace; }
.brain-item { padding: 14px 16px; border-radius: 12px; background: rgba(5,8,16,0.65);
  border-left: 3px solid var(--accent); margin-top: 10px; }
.brain-item .sec { color: var(--accent); font-size: 11px; text-transform: uppercase;
  letter-spacing: 0.08em; font-weight: 700; margin-bottom: 6px; }
.brain-item .stmt { font-size: 14.5px; }
.brain-item .conf { color: var(--muted); font-size: 11.5px; margin-top: 8px;
  font-family: ui-monospace, SFMono-Regular, monospace; }

.pm-status { padding: 18px 24px; border-radius: 16px; margin-bottom: 18px;
  border: 1px solid; display: flex; flex-wrap: wrap; gap: 18px; align-items: center; }
.pm-red    { background: rgba(239,68,68,0.10); border-color: rgba(239,68,68,0.45); }
.pm-yellow { background: rgba(250,204,21,0.10); border-color: rgba(250,204,21,0.45); }
.pm-green  { background: rgba(34,197,94,0.10); border-color: rgba(34,197,94,0.45); }
.pm-pill { padding: 8px 16px; border-radius: 999px; font-weight: 800;
  letter-spacing: 0.12em; text-transform: uppercase; font-size: 12px; }
.pm-pill.red    { background: var(--bad); color: #2c0808; }
.pm-pill.yellow { background: var(--warn); color: #2c1a08; }
.pm-pill.green  { background: #4ade80; color: #06210e; }

.gap-list { list-style: none; padding: 0; margin: 0; display: grid; gap: 10px; }
.gap { display: flex; gap: 14px; padding: 14px 16px; border-radius: 12px;
  background: rgba(11,16,32,0.65); border: 1px solid rgba(148,163,184,0.12); }
.gap .sev { flex-shrink: 0; padding: 4px 10px; border-radius: 999px;
  font-size: 10.5px; font-weight: 800; text-transform: uppercase;
  letter-spacing: 0.08em; height: fit-content; }
.gap .sev.blocker { background: rgba(239,68,68,0.20); color: #fca5a5; }
.gap .sev.warning { background: rgba(250,204,21,0.20); color: #fde68a; }
.gap .body { font-size: 14px; }
.gap .body .why { color: var(--muted); font-size: 12.5px; margin-top: 4px; }

.numbers { display: grid; gap: 16px;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); }
.numbers .num-card { background: linear-gradient(180deg, rgba(17,23,42,0.85), rgba(11,16,32,0.85));
  border: 1px solid rgba(148,163,184,0.16); border-radius: 16px; padding: 26px 22px; }
.numbers .num-card .big { font-size: 44px; font-weight: 800; line-height: 1;
  background: linear-gradient(180deg, #ffffff, #a7f3d0); -webkit-background-clip: text;
  background-clip: text; color: transparent; }
.numbers .num-card .lab { color: var(--muted); margin-top: 10px; font-size: 12px;
  text-transform: uppercase; letter-spacing: 0.1em; }
.numbers .num-card .note { color: #cbd5e1; margin-top: 12px; font-size: 13px; }

footer { text-align: center; padding: 60px 0 80px 0; color: var(--muted);
  font-size: 12px; border-top: 1px solid rgba(148,163,184,0.08); margin-top: 60px; }
footer code { background: rgba(15,23,42,0.6); padding: 2px 6px; border-radius: 4px; }
</style>
</head>
<body>
"""


_FOOTER_TEMPLATE = """
<footer>
  <div class="container">
    Generated by <code>tools/build_demo_showcase.py</code> from the
    OrbitBrief pipeline output at <code>{out_dir}</code>.<br>
    Compile id <code>{compile_id}</code> · {generated_at}
  </div>
</footer>
</body></html>
"""


def _file_icon(ext: str) -> str:
    ext = ext.lower().lstrip(".")
    return {
        "pdf": "📄",
        "xlsx": "📊",
        "csv": "📊",
        "txt": "📝",
        "md": "📝",
        "eml": "✉️",
        "docx": "📄",
        "vtt": "🎙️",
        "json": "🧾",
    }.get(ext, "📎")


def _file_summary(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower().lstrip(".")
    descr = {
        "pdf": "Customer document — preserved layout, tables, and form fields",
        "xlsx": "Workbook — multi-sheet rows extracted into structured atoms",
        "csv": "Tabular data — every row becomes a typed atom with locator",
        "txt": "Plain text — sectioned into scope items, exclusions, decisions",
        "md": "Markdown notes — meeting decisions and assumptions",
        "eml": "Customer email — sender, subject, scope clarifications",
        "docx": "Office document — body + tracked changes preserved",
        "vtt": "Meeting transcript — decisions, open questions, action items",
        "json": "Structured intake — pre-typed atoms passed straight through",
    }.get(suffix, "Customer artifact")
    return {
        "name": path.name,
        "ext": suffix,
        "icon": _file_icon(suffix),
        "size_kb": round(path.stat().st_size / 1024, 1) if path.is_file() else 0.0,
        "descr": descr,
    }


def _enumerate_case_files(case_dir: Path) -> list[dict[str, Any]]:
    artifact_dir = case_dir / "artifacts"
    candidates: list[Path] = []
    if artifact_dir.is_dir():
        for sub in ("public_sources", "extracted", "supplemental"):
            d = artifact_dir / sub
            if d.is_dir():
                for p in sorted(d.iterdir()):
                    if p.is_file() and p.suffix.lower() in {
                        ".pdf", ".xlsx", ".csv", ".txt", ".md", ".eml", ".docx", ".vtt"
                    }:
                        candidates.append(p)
    # Fallback: anything at the top of case_dir.
    if not candidates:
        for p in sorted(case_dir.iterdir()):
            if p.is_file():
                candidates.append(p)
    return [_file_summary(p) for p in candidates]


def _section_label(s: str) -> str:
    return s.replace("_", " ").title()


def _render_pm_block(pm: dict[str, Any]) -> str:
    status = (pm.get("status") or "unknown").lower()
    css = "pm-red" if status == "red" else ("pm-yellow" if status == "yellow" else "pm-green")
    pill_css = "red" if status == "red" else ("yellow" if status == "yellow" else "green")
    blockers = [g for g in (pm.get("gaps") or []) if g.get("severity") == "blocker"]
    warnings = [g for g in (pm.get("gaps") or []) if g.get("severity") == "warning"]

    head = (
        f'<div class="pm-status {css}">'
        f'<div class="pm-pill {pill_css}">{_esc(status.upper())}</div>'
        f'<div><strong>{_esc(pm.get("headline") or "Pipeline verdict")}</strong></div>'
        f'<div style="margin-left:auto; color: var(--muted); font-size: 13px;">'
        f'{len(blockers)} blocker · {len(warnings)} warning</div>'
        f'</div>'
    )

    def _gap_li(g: dict[str, Any]) -> str:
        sev = (g.get("severity") or "warning").lower()
        return (
            f'<li class="gap"><span class="sev {sev}">{_esc(sev)}</span>'
            f'<div class="body"><div>{_esc(g.get("title") or g.get("statement") or "—")}</div>'
            f'<div class="why">{_esc(_shorten(g.get("reason") or g.get("rationale") or "", 220))}</div>'
            f'</div></li>'
        )

    items_html = ""
    if blockers or warnings:
        items_html = (
            '<ul class="gap-list">'
            + "".join(_gap_li(g) for g in blockers[:5])
            + "".join(_gap_li(g) for g in warnings[:3])
            + "</ul>"
        )
    return head + items_html


def _render_brain_block(pack: str, items: list[dict[str, Any]], data: dict[str, Any]) -> str:
    tc = data.get("token_cost") or {}
    fb = bool(data.get("fallback_used"))
    pill = "fallback" if fb else "live"
    pill_css = (
        "background: rgba(250,204,21,0.18); color: var(--warn);"
        if fb else
        "background: rgba(91,227,197,0.18); color: var(--accent);"
    )
    item_html = "".join(
        f'<div class="brain-item">'
        f'<div class="sec">{_esc(_section_label(it.get("section") or ""))}</div>'
        f'<div class="stmt">{_esc(it.get("statement") or "")}</div>'
        f'<div class="conf">confidence {float(it.get("confidence") or 0):.2f} · '
        f'cites {len(it.get("supporting_packet_ids") or [])} packet(s) · '
        f'{len(it.get("supporting_atom_ids") or [])} atom(s)</div>'
        f'</div>'
        for it in items
    ) or '<div class="brain-item"><em>(no high-confidence items emitted by this brain on this case)</em></div>'
    return (
        f'<div class="brain-block">'
        f'<div class="head">'
        f'<h3>🧠 {_esc(_section_label(pack))} brain</h3>'
        f'<span class="pill" style="{pill_css}">{_esc(pill)}</span>'
        f'<span class="meta">model {_esc(data.get("model_used") or "—")} · '
        f'{_fmt_int(tc.get("total_tokens", 0))} tokens · '
        f'{_fmt_int(tc.get("latency_ms", 0))} ms</span>'
        f'</div>'
        f'{item_html}'
        f'</div>'
    )


def render_demo(*, out_dir: Path, case_dir: Path, runtime_s: float | None) -> str:
    envelope = _safe_load(out_dir / "00_envelope.json") or {}
    manifest = _safe_load(out_dir / "manifest.json") or {}
    pack_prior = _safe_load(out_dir / "10_pack_prior_state.json") or {}
    pm = _safe_load(out_dir / "PM_HANDOFF.json") or {}
    inspection = _safe_load(out_dir / "90_inspection_report.json") or {}

    project_id = envelope.get("project_id") or manifest.get("project_id") or case_dir.name
    compile_id = envelope.get("compile_id") or manifest.get("compile_id") or "—"
    generated_at = manifest.get("generated_at") or "—"

    n_docs = len(envelope.get("documents") or [])
    n_atoms = len(envelope.get("atoms") or [])
    n_entities = len(envelope.get("entities") or [])
    n_edges = len(envelope.get("edges") or [])
    n_packets = len(envelope.get("packets") or [])

    brains_run = list(manifest.get("brains_run") or [])
    brain_outputs: dict[str, dict[str, Any]] = {}
    brain_dir = out_dir / "40_brain_outputs"
    if brain_dir.is_dir():
        for f in sorted(brain_dir.glob("*.json")):
            data = _safe_load(f) or {}
            brain_outputs[f.stem] = data
    total_brain_items = sum(
        sum(len(d.get(s) or []) for s in (
            "scope_overview", "detailed_scope_of_services", "deliverables",
            "assumptions", "customer_responsibilities", "out_of_scope",
            "risks_or_dependencies", "completion_criteria", "open_items",
        ))
        for d in brain_outputs.values()
    )
    brain_highlights = _pick_brain_highlights(brain_outputs)

    headline_atoms = _pick_headline_atoms(envelope)
    case_files = _enumerate_case_files(case_dir)

    health_pct = float((inspection.get("verification") or {}).get("health_pct") or 0.0)

    runtime_str = f"{runtime_s:.0f}s" if runtime_s else "—"
    runtime_min = f"{runtime_s/60:.1f} min" if runtime_s else "—"

    # ────────────────────────────── Hero ──────────────────────────────
    hero = f"""
<div class="hero">
  <div class="container">
    <div class="eyebrow">OrbitBrief — live pipeline demo</div>
    <h1>From {n_docs} customer documents to a PM-ready brief in {runtime_min}.</h1>
    <p class="lede">
      We took the <strong>{_esc(project_id)}</strong> intake — RFPs, addendums, vendor quotes,
      kickoff notes, and customer emails — and ran it through the full OrbitBrief
      pipeline end-to-end. No human in the loop. The system extracted the facts,
      built the knowledge graph, woke up the right AI specialists, and produced
      a triaged PM handoff with hard blockers called out.
    </p>
    <div class="stats">
      <div class="stat"><div class="num">{_fmt_int(n_docs)}</div><div class="lab">Source docs</div></div>
      <div class="stat"><div class="num">{_fmt_int(n_atoms)}</div><div class="lab">Atomic facts extracted</div></div>
      <div class="stat"><div class="num">{_fmt_int(n_entities)}</div><div class="lab">Entities (knowledge graph)</div></div>
      <div class="stat"><div class="num">{_fmt_int(n_edges)}</div><div class="lab">Relationships</div></div>
      <div class="stat"><div class="num">{_fmt_int(len(brains_run))}</div><div class="lab">AI specialists fired</div></div>
      <div class="stat"><div class="num">{_fmt_int(total_brain_items)}</div><div class="lab">PM-grade scope items</div></div>
    </div>
  </div>
</div>
"""

    # ────────────────────────────── Act 1: Input ──────────────────────
    file_rows = "".join(
        f'<li class="file"><div class="ico">{f["icon"]}</div>'
        f'<div><div class="name">{_esc(f["name"])}</div>'
        f'<div class="desc">{_esc(f["descr"])} · {f["size_kb"]:.1f} KB</div></div></li>'
        for f in case_files
    )
    act1 = f"""
<section class="act">
  <div class="container">
    <div class="label">Act 1 · The intake</div>
    <h2>What the customer threw at us.</h2>
    <p class="sub">A normal commercial-cabling RFP package: original RFP, an addendum that overrides earlier
    language, a vendor quote, a customer email clarifying scope, internal kickoff notes, and the
    public-source PDFs. Today, a senior PM spends roughly a week absorbing this. We do it in minutes.</p>
    <ul class="files">{file_rows}</ul>
  </div>
</section>
"""

    # ────────────────────────────── Act 2: Atoms ──────────────────────
    atom_cards = "".join(
        f'<div class="card">'
        f'<span class="tag {a["_css"]}">{_esc(a["_label"])}</span>'
        f'<div class="quote">“{_esc(_shorten(a.get("text") or "", 320))}”</div>'
        f'<div class="meta">type: <code>{_esc(a.get("atom_type"))}</code> · '
        f'confidence {float(a.get("confidence") or 0):.2f} · '
        f'verified: {_esc(a.get("verified") or "—")}</div>'
        f'</div>'
        for a in headline_atoms
    )
    act2 = f"""
<section class="act">
  <div class="container">
    <div class="label">Act 2 · Parser-os</div>
    <h2>{_fmt_int(n_atoms)} atomic facts, every one with a source pointer.</h2>
    <p class="sub">parser-os is deterministic — no LLM in the hot path. It reads each file, types every
    fact (a count, an exclusion, a question, a vendor part…), and stamps each one with a
    confidence score and a locator that points back to the exact byte range in the source. Below are
    six hand-picked examples from this case.</p>
    <div class="cards">{atom_cards}</div>
  </div>
</section>
"""

    # ────────────────────────────── Act 3: Graph ──────────────────────
    svg, type_counts = _build_graph_svg(
        envelope.get("entities") or [], envelope.get("edges") or [],
    )
    legend = " ".join(
        f'<span><span class="swatch" style="background:{_ENTITY_COLORS.get(t, _ENTITY_COLORS["_default"])}"></span>'
        f'{_esc(_section_label(t))} ({n})</span>'
        for t, n in sorted(type_counts.items(), key=lambda kv: -kv[1])[:8]
    )
    act3 = f"""
<section class="act">
  <div class="container">
    <div class="label">Act 3 · Knowledge graph</div>
    <h2>The system stitches every fact into a {_fmt_int(n_entities)}-entity graph.</h2>
    <p class="sub">Every site, vendor, part number, addendum, customer question, and compliance
    standard becomes a node. Every "supports / contradicts / same-as / requires" relationship
    becomes an edge. {_fmt_int(n_edges)} relationships in total. This is what lets us notice that
    an addendum on page 14 contradicts a quantity on page 3 of the original RFP.</p>
    <div class="graph-wrap">
      {svg}
      <div class="graph-legend">{legend}</div>
    </div>
  </div>
</section>
"""

    # ────────────────────────────── Act 4: Pack prior ─────────────────
    top_pack = pack_prior.get("top_pack_id") or "—"
    selected = list(pack_prior.get("selected_pack_ids") or [])
    top_conf = pack_prior.get("top_confidence")
    margin = pack_prior.get("margin")
    act4 = f"""
<section class="act">
  <div class="container">
    <div class="label">Act 4 · Pack prior</div>
    <h2>The system decides which AI specialists to consult.</h2>
    <p class="sub">Before any LLM runs, a deterministic router scores the case against every
    domain pack. For this case it identified <strong>{_esc(top_pack)}</strong> as the dominant
    domain (confidence {float(top_conf or 0):.2f}, margin {float(margin or 0):.2f}) and selected
    {len(selected)} specialist(s) to run: <strong>{_esc(", ".join(selected) or "—")}</strong>.
    No money is wasted on irrelevant specialists.</p>
  </div>
</section>
"""

    # ────────────────────────────── Act 5: Brains ─────────────────────
    brain_blocks = "".join(
        _render_brain_block(pack, brain_highlights.get(pack) or [], data)
        for pack, data in sorted(brain_outputs.items())
    ) or "<p class='sub'>(no brains ran)</p>"
    act5 = f"""
<section class="act">
  <div class="container">
    <div class="label">Act 5 · The specialists</div>
    <h2>{_fmt_int(len(brain_outputs))} AI specialists wake up — one per active domain.</h2>
    <p class="sub">Each brain is a domain expert (electrical, low-voltage cabling,
    professional services, etc.) prompted with only the facts relevant to its
    domain — not the whole document mountain. Each emits a structured brief
    (scope, deliverables, assumptions, risks, open questions) with a citation
    back to the original atoms. Below: the highest-confidence items per
    specialist.</p>
    {brain_blocks}
  </div>
</section>
"""

    # ────────────────────────────── Act 6: PM ─────────────────────────
    pm_block = _render_pm_block(pm)
    act6 = f"""
<section class="act">
  <div class="container">
    <div class="label">Act 6 · The verdict</div>
    <h2>The PM handoff.</h2>
    <p class="sub">The composer rolls the specialists' outputs into a single executive brief and runs the
    SOW validator. If anything blocks signing — missing scope, contradictions, unanswered
    customer questions — it surfaces here, color-coded.</p>
    {pm_block}
  </div>
</section>
"""

    # ────────────────────────────── Closing ───────────────────────────
    closing = f"""
<section class="act">
  <div class="container">
    <div class="label">By the numbers</div>
    <h2>What this run cost us.</h2>
    <div class="numbers">
      <div class="num-card">
        <div class="big">{runtime_str}</div>
        <div class="lab">Total wall-clock</div>
        <div class="note">parser-os + 3 LLM brains + composer + validator on a Mac Studio.</div>
      </div>
      <div class="num-card">
        <div class="big">{health_pct:.1f}%</div>
        <div class="lab">Parser health</div>
        <div class="note">Atoms whose source bytes the parser could replay verbatim.</div>
      </div>
      <div class="num-card">
        <div class="big">{_fmt_int(n_packets)}</div>
        <div class="lab">Packets certified</div>
        <div class="note">Atom-level facts grouped into reviewable evidence packets.</div>
      </div>
      <div class="num-card">
        <div class="big">{_fmt_int(total_brain_items)}</div>
        <div class="lab">Brain-emitted scope items</div>
        <div class="note">Each one cites at least one packet and one atom — fully traceable.</div>
      </div>
    </div>
  </div>
</section>
"""

    body = hero + act1 + act2 + act3 + act4 + act5 + act6 + closing
    footer = _FOOTER_TEMPLATE.format(out_dir=str(out_dir), compile_id=_esc(compile_id),
                                    generated_at=_esc(generated_at))
    return _HEAD + body + footer


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="build_demo_showcase.py", description=__doc__)
    p.add_argument("--out-dir", required=True, type=Path,
                   help="pm_handoff.sh output directory.")
    p.add_argument("--case-dir", required=True, type=Path,
                   help="Original raw case directory (for source-file enumeration).")
    p.add_argument("--runtime-s", type=float, default=None,
                   help="Wall-clock seconds the run took (for the hero stat).")
    p.add_argument("--out", type=Path, default=None,
                   help="Output HTML path. Defaults to <out-dir>/BOSS_DEMO.html.")
    args = p.parse_args(argv)

    if not args.out_dir.is_dir():
        sys.exit(f"build_demo_showcase: out_dir not found: {args.out_dir}")
    if not args.case_dir.is_dir():
        sys.exit(f"build_demo_showcase: case_dir not found: {args.case_dir}")
    out_path = args.out or (args.out_dir / "BOSS_DEMO.html")

    html_str = render_demo(out_dir=args.out_dir, case_dir=args.case_dir,
                          runtime_s=args.runtime_s)
    out_path.write_text(html_str, encoding="utf-8")
    print(f"build_demo_showcase: wrote {out_path} ({len(html_str)/1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
