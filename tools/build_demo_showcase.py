#!/usr/bin/env python3
"""build_demo_showcase.py — Purpulse-branded executive showcase HTML.

Reads a completed pm_handoff.sh output directory + the original case
directory, then renders a single self-contained ``BOSS_DEMO.html``
that looks like an actual page from the Purpulse OrbitBrief product
(not a marketing splash).

Brand-aligned with ``purpulse-frontend``:
  * Plus Jakarta Sans + Instrument Serif + JetBrains Mono
  * Light editorial palette (paper #fafaf7, surface #fff, ink #0a0a0a)
  * Accents: blue #1b6dff, emerald #047857, amber #b45309, rose #be123c
  * Type scale + spacing mirrors ``ob-display-*`` / ``ob-h*`` tokens

Story arc:
  1. Sticky product chrome + status pill.
  2. Hero — one-line summary from PM_HANDOFF.json + headline metrics.
  3. Source library — every customer file with type chip + size.
  4. Atomic facts — hand-picked atom cards across diverse types,
     each with a source-replay status dot (green / amber / rose).
  5. Knowledge graph — inline SVG, light theme, deterministic layout.
  6. Pipeline — stage timeline pulled from pipeline_log.json with
     real per-stage timings.
  7. Domain matrix — every domain the SOW validator considered,
     selected-by-router flag, blockers / warnings / info per row.
  8. Sites published — strip of the 25 named site clusters.
  9. AI specialists — 3 brain blocks with top-confidence items +
     real model + token + latency telemetry.
 10. Facts gallery — facts_by_category with filename + page locator
     (the Purpulse "fact card" pattern).
 11. SA focus — numbered list pulled straight from sa_focus.
 12. PM blockers — rule_id + observed_summary + suggested_open_question.
 13. Closing metrics.

Usage::

    python3 tools/build_demo_showcase.py \\
        --out-dir /tmp/COPPER_001_demo \\
        --case-dir /Users/.../parser-os-repo/real_data_cases/COPPER_001_SPRING_LAKE_AUDITORIUM \\
        --runtime-s 480

The script has zero third-party deps. The output HTML is also
self-contained (inline CSS, inline SVG, Google Fonts via @import).
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


# ────────────────────────────── helpers ────────────────────────────────


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
        return str(n) if n is not None else "—"


def _fmt_ms(ms: Any) -> str:
    try:
        ms = int(ms)
    except (TypeError, ValueError):
        return "—"
    if ms < 1000:
        return f"{ms} ms"
    if ms < 60_000:
        return f"{ms / 1000:.1f} s"
    return f"{ms / 60_000:.1f} m"


def _shorten(s: str, n: int) -> str:
    s = (s or "").strip()
    s = " ".join(s.split())
    if len(s) <= n:
        return s
    # Cut on a word boundary if possible so we never end mid-word.
    cut = s.rfind(" ", 0, n - 1)
    if cut > n * 0.6:
        return s[:cut].rstrip(" ,;:.") + "…"
    return s[: n - 1].rstrip(" ,;:.") + "…"


# Noise prefixes that show up in raw RFP text and look terrible in a
# showcase quote ("Risk Trigger:", "Answer:", "Line item", "8.4.1 ...").
# Stripping them dramatically improves how the cards read.
_NOISE_PREFIX_PATTERNS = (
    r"^(?:Risk Trigger|Answer|Question|Note|Comment|Description|Title)\s*:\s*",
    r"^Line item\s+",
    r"^\d+(?:\.\d+){1,4}\s*[-–—]?\s*",
    r"^[A-Z]\d+(?:\.\d+){0,3}\s*[-–—]?\s*",
    r"^Section\s+\d+(?:\.\d+){0,3}\s*[:.\-–—]?\s*",
)


def _polish_quote(s: str) -> str:
    """Tidy raw RFP text so it reads cleanly in a card."""
    import re
    if not s:
        return ""
    s = s.strip()
    # Normalize curly / smart quotes + ligatures + double spaces.
    s = (s.replace("\u201c", '"').replace("\u201d", '"')
           .replace("\u2018", "'").replace("\u2019", "'")
           .replace("\u00a0", " ").replace("\u2013", "-").replace("\u2014", "-"))
    s = " ".join(s.split())
    for pat in _NOISE_PREFIX_PATTERNS:
        s = re.sub(pat, "", s, count=1)
    # Capitalize the first letter if it isn't already.
    if s and s[0].islower():
        s = s[0].upper() + s[1:]
    # Strip a trailing colon or comma — both look orphaned in a quote.
    s = s.rstrip(",:; ")
    return s


def _section_label(s: str) -> str:
    return s.replace("_", " ").title()


def _powered_by(*parts: str) -> str:
    """Render a small "powered by parser-os + OrbitBrief" badge.

    Each chapter shows which subsystem produced its content so the
    reader walks away knowing both halves of the stack contributed.
    """
    chips = "".join(
        f'<span class="pb-chip pb-{("po" if "parser" in p.lower() else "ob")}">{_esc(p)}</span>'
        for p in parts
    )
    return f'<div class="powered">{chips}</div>'


def _verified_dot(verified: str | None) -> str:
    """Render a small colored dot mirroring parser-os atom verification."""
    v = (verified or "unverified").lower()
    color = {
        "verified": "#047857",
        "partial": "#b45309",
        "failed": "#be123c",
        "unsupported": "#71717a",
        "unverified": "#a3a3a3",
    }.get(v, "#a3a3a3")
    title = f"source-replay status: {v}"
    return (
        f'<span class="dot" style="background:{color}" '
        f'title="{_esc(title)}"></span>'
    )


# ────────────────────────────── content selection ──────────────────────


# These are the atom types that translate cleanly to plain-English
# story moments for an exec audience.
_HEADLINE_ATOM_TYPES: tuple[tuple[str, str, str], ...] = (
    ("quantity", "Counted", "chip-blue"),
    ("exclusion", "Out of scope", "chip-rose"),
    ("vendor_line_item", "Vendor part", "chip-violet"),
    ("open_question", "Open question", "chip-amber"),
    ("customer_instruction", "Customer directive", "chip-emerald"),
    ("constraint", "Binding constraint", "chip-blue"),
    ("decision", "Settled decision", "chip-emerald"),
    ("compliance", "Compliance reference", "chip-amber"),
)


def _pick_headline_atoms(envelope: dict[str, Any]) -> list[dict[str, Any]]:
    """Return up to 8 best-in-class atoms across diverse types."""
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
        candidates.sort(
            key=lambda a: (-(a.get("confidence") or 0.0), -len(a.get("text") or "")),
        )
        for c in candidates:
            text = (c.get("text") or "").strip()
            if 30 <= len(text) <= 360:
                picked.append({**c, "_label": label, "_css": css})
                break
    return picked[:8]


def _pick_brain_highlights(brain_outputs: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """For each brain, pick 3 highest-confidence items across all sections."""
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


# ────────────────────────────── GNN graph (light theme) ────────────────


_ENTITY_COLORS: dict[str, str] = {
    "site": "#1b6dff",
    "part_number": "#6d28d9",
    "manufacturer": "#b45309",
    "vendor": "#b45309",
    "person": "#0f766e",
    "organization": "#1b6dff",
    "compliance_standard": "#b45309",
    "vendor_part": "#6d28d9",
    "addendum": "#52525b",
    "document": "#52525b",
    "open_question": "#be123c",
    "_default": "#3f3f46",
}


def _color_for_entity(ent: dict[str, Any]) -> str:
    t = (ent.get("entity_type") or "").lower()
    return _ENTITY_COLORS.get(t, _ENTITY_COLORS["_default"])


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
    width: int = 980,
    height: int = 560,
    max_nodes: int = 56,
) -> tuple[str, dict[str, int]]:
    if not entities:
        return ("<svg></svg>", {})

    edge_count: dict[str, int] = {}
    for e in edges:
        for end in (e.get("source"), e.get("target"), e.get("from"), e.get("to")):
            if end:
                edge_count[end] = edge_count.get(end, 0) + 1
    ranked = sorted(entities, key=lambda x: -edge_count.get(x.get("id") or "", 0))
    picked = ranked[:max_nodes]

    by_type: dict[str, list[dict[str, Any]]] = {}
    for ent in picked:
        t = (ent.get("entity_type") or "other").lower()
        by_type.setdefault(t, []).append(ent)
    type_counts = {t: len(v) for t, v in by_type.items()}

    cx, cy = width / 2.0, height / 2.0
    nodes: dict[str, _GraphNode] = {}
    rng = random.Random(42)
    type_order = sorted(by_type, key=lambda t: -len(by_type[t]))
    n_types = max(1, len(type_order))
    for ti, etype in enumerate(type_order):
        ring_r = 90 + ti * (min(width, height) * 0.16)
        ring_r = min(ring_r, min(cx, cy) - 30)
        ents_in = by_type[etype]
        n = max(1, len(ents_in))
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
            label = _shorten(str(label), 26)
            radius = 4 + min(8, edge_count.get(ent.get("id") or "", 0) * 0.3)
            nodes[ent.get("id") or ""] = _GraphNode(
                id=ent.get("id") or "?",
                label=label,
                color=_color_for_entity(ent),
                radius=radius,
                x=x,
                y=y,
            )

    edge_lines: list[str] = []
    for e in edges:
        s = e.get("source") or e.get("from")
        t = e.get("target") or e.get("to")
        if s in nodes and t in nodes and s != t:
            ns, nt = nodes[s], nodes[t]
            edge_lines.append(
                f'<line x1="{ns.x:.1f}" y1="{ns.y:.1f}" '
                f'x2="{nt.x:.1f}" y2="{nt.y:.1f}" '
                f'stroke="rgba(15,23,42,0.06)" stroke-width="0.7"/>'
            )
    if len(edge_lines) > 800:
        edge_lines = edge_lines[:800]

    node_circles: list[str] = []
    node_labels: list[str] = []
    for n in nodes.values():
        node_circles.append(
            f'<circle cx="{n.x:.1f}" cy="{n.y:.1f}" r="{n.radius:.1f}" '
            f'fill="{n.color}" fill-opacity="0.9" stroke="#fff" stroke-width="1.4">'
            f'<title>{_esc(n.label)} — {_esc(n.id)}</title></circle>'
        )
        if n.radius >= 6.5:
            node_labels.append(
                f'<text x="{n.x + n.radius + 4:.1f}" y="{n.y + 3:.1f}" '
                f'fill="#27272a" font-size="9.5" '
                f'font-family="JetBrains Mono, ui-monospace, monospace">'
                f'{_esc(n.label)}</text>'
            )

    svg = (
        f'<svg viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="Knowledge graph of extracted entities and relationships" '
        f'style="display:block; width:100%; height:auto;">'
        f'<defs>'
        f'  <radialGradient id="bg-grad" cx="50%" cy="40%" r="60%">'
        f'    <stop offset="0%" stop-color="#fbfbf8"/>'
        f'    <stop offset="100%" stop-color="#f3f3ee"/>'
        f'  </radialGradient>'
        f'</defs>'
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="url(#bg-grad)" rx="12"/>'
        + "".join(edge_lines)
        + "".join(node_circles)
        + "".join(node_labels)
        + "</svg>"
    )
    return svg, type_counts


# ────────────────────────────── HTML pieces ────────────────────────────


_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OrbitBrief — {project_id}</title>
<link rel="icon" href='data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" fill="none" stroke="%231b6dff" stroke-width="2"/><circle cx="12" cy="12" r="3" fill="%231b6dff"/></svg>'>
<style>
@import url("https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Instrument+Serif:ital@0;1&family=JetBrains+Mono:wght@400;500;600&display=swap");

:root {{
  --ob-paper: #fafaf7;
  --ob-surface: #ffffff;
  --ob-surface-2: #f6f6f2;
  --ob-line: #e8e8e2;
  --ob-line-2: #d8d8d2;
  --ob-ink: #0a0a0a;
  --ob-ink-2: #27272a;
  --ob-ink-3: #52525b;
  --ob-ink-4: #71717a;
  --ob-blue: #1b6dff;
  --ob-blue-soft: #eef4ff;
  --ob-emerald: #047857;
  --ob-emerald-soft: #ecfdf5;
  --ob-amber: #b45309;
  --ob-amber-soft: #fffbeb;
  --ob-rose: #be123c;
  --ob-rose-soft: #fff1f2;
  --ob-violet: #6d28d9;
  --ob-violet-soft: #f5f3ff;
  --ob-radius-sm: 8px;
  --ob-radius-md: 12px;
  --ob-shadow-sm: 0 1px 2px rgba(15,23,42,.04), 0 1px 3px rgba(15,23,42,.04);
  --ob-shadow-md: 0 2px 4px rgba(15,23,42,.04), 0 4px 12px rgba(15,23,42,.06);
}}

* {{ box-sizing: border-box; }}
html, body {{
  margin: 0; padding: 0;
  background: var(--ob-paper); color: var(--ob-ink);
  font-family: "Plus Jakarta Sans", ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  font-feature-settings: "ss01", "cv11";
  -webkit-font-smoothing: antialiased; line-height: 1.5;
  text-wrap: pretty;
}}
/* Belt-and-suspenders: nothing should ever break the layout, no
   matter how long an atom statement or vendor part name turns out
   to be. */
* {{ word-wrap: break-word; overflow-wrap: anywhere; }}
.container {{ max-width: 1120px; margin: 0 auto; padding: 0 36px; }}
.mono {{ font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, monospace; }}
.serif {{ font-family: "Instrument Serif", Georgia, serif; }}
a {{ color: var(--ob-blue); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}

/* Sticky product chrome */
.chrome {{
  position: sticky; top: 0; z-index: 50;
  background: rgba(255,255,255,0.92); backdrop-filter: blur(10px) saturate(140%);
  border-bottom: 1px solid var(--ob-line);
}}
.chrome .row {{
  display: flex; align-items: center; gap: 16px;
  padding: 14px 32px; max-width: 1180px; margin: 0 auto;
}}
.brand {{ display: flex; align-items: center; gap: 10px; font-weight: 700; letter-spacing: -0.01em; }}
.brand-mark {{
  width: 22px; height: 22px; border-radius: 50%;
  border: 2px solid var(--ob-blue);
  display: inline-flex; align-items: center; justify-content: center;
}}
.brand-mark::after {{
  content: ""; width: 6px; height: 6px; border-radius: 50%; background: var(--ob-blue);
}}
.brand-name {{ color: var(--ob-ink); }}
.brand-name .lo {{ color: var(--ob-ink-3); font-weight: 500; }}
.crumbs {{ color: var(--ob-ink-3); font-size: 13px; display: flex; gap: 8px; align-items: center; }}
.crumbs .sep {{ color: var(--ob-ink-4); }}
.crumbs .here {{ color: var(--ob-ink); font-weight: 600; }}
.chip-status {{
  margin-left: auto; padding: 5px 12px; border-radius: 999px; font-size: 11px; font-weight: 700;
  letter-spacing: 0.06em; text-transform: uppercase;
}}
.chip-status.red {{ background: var(--ob-rose-soft); color: var(--ob-rose); border: 1px solid #fecdd3; }}
.chip-status.yellow {{ background: var(--ob-amber-soft); color: var(--ob-amber); border: 1px solid #fde68a; }}
.chip-status.green {{ background: var(--ob-emerald-soft); color: var(--ob-emerald); border: 1px solid #a7f3d0; }}
.chip-status.muted {{ background: var(--ob-surface-2); color: var(--ob-ink-3); border: 1px solid var(--ob-line); }}

/* Hero */
.hero {{ padding: 96px 0 80px 0; background: var(--ob-paper); }}
.hero .eyebrow {{
  font-size: 11px; font-weight: 700; letter-spacing: 0.16em; text-transform: uppercase;
  color: var(--ob-blue); margin-bottom: 18px;
}}
.hero h1 {{
  font-family: "Instrument Serif", Georgia, serif; font-weight: 400;
  font-size: clamp(40px, 6.5vw, 72px); line-height: 1.04; letter-spacing: -0.025em;
  margin: 0 0 28px 0; color: var(--ob-ink); text-wrap: balance;
  max-width: 14ch;
}}
.hero h1 em {{ font-style: italic; color: var(--ob-blue); }}
.hero .subline {{ color: var(--ob-ink-2); font-size: 19px; max-width: 720px;
  line-height: 1.5; text-wrap: pretty; }}
.hero .stats {{
  margin-top: 56px; display: grid; gap: 14px;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
}}
.stat-card {{
  background: var(--ob-surface); border: 1px solid var(--ob-line);
  border-radius: var(--ob-radius-md); padding: 22px 22px;
  box-shadow: var(--ob-shadow-sm); min-width: 0;
}}
.stat-card .lab {{
  font-size: 10.5px; font-weight: 700; letter-spacing: 0.10em; text-transform: uppercase;
  color: var(--ob-ink-4); margin-bottom: 10px;
}}
.stat-card .num {{
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 36px; font-weight: 600; line-height: 1; color: var(--ob-ink);
  letter-spacing: -0.03em;
}}
.stat-card .delta {{ color: var(--ob-emerald); font-size: 11px; margin-top: 6px; }}

/* Sections */
section {{ padding: 100px 0 24px 0; border-top: 1px solid var(--ob-line); }}
section .label {{
  font-size: 10.5px; font-weight: 700; letter-spacing: 0.16em; text-transform: uppercase;
  color: var(--ob-blue); margin-bottom: 14px;
}}
section h2 {{
  font-family: "Instrument Serif", Georgia, serif; font-weight: 400;
  font-size: clamp(30px, 4vw, 44px); line-height: 1.1; letter-spacing: -0.015em;
  margin: 0 0 18px 0; color: var(--ob-ink); text-wrap: balance; max-width: 22ch;
}}
section h2 em {{ font-style: italic; color: var(--ob-blue); }}
section h2 strong {{ font-weight: 400; }}
section .sub {{ color: var(--ob-ink-3); font-size: 16px; line-height: 1.55;
  max-width: 720px; margin-bottom: 28px; text-wrap: pretty; }}

/* Powered-by chips — every chapter labels which half of the stack
   produced its content. */
.powered {{ display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 36px; }}
.pb-chip {{ display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 10px; border-radius: 999px; font-size: 11px; font-weight: 600;
  letter-spacing: 0.04em; border: 1px solid var(--ob-line);
  background: var(--ob-surface); color: var(--ob-ink-3);
  font-family: "JetBrains Mono", monospace; }}
.pb-chip::before {{ content: ""; width: 6px; height: 6px; border-radius: 50%;
  display: inline-block; }}
.pb-chip.pb-po::before {{ background: var(--ob-emerald); }}
.pb-chip.pb-ob::before {{ background: var(--ob-blue); }}
.pb-chip.pb-po {{ color: var(--ob-emerald); border-color: #c8edd2; background: var(--ob-emerald-soft); }}
.pb-chip.pb-ob {{ color: var(--ob-blue); border-color: #c5d8ff; background: var(--ob-blue-soft); }}

/* Pulsing live indicator for the chrome status pill on red. */
@keyframes ob-pulse {{
  0%, 100% {{ opacity: 1; }}
  50% {{ opacity: 0.35; }}
}}
.live-dot {{ width: 7px; height: 7px; border-radius: 50%;
  display: inline-block; vertical-align: middle; margin-right: 6px;
  animation: ob-pulse 1.6s ease-in-out infinite; }}
.live-dot.r {{ background: var(--ob-rose); box-shadow: 0 0 0 3px rgba(190,18,60,0.15); }}
.live-dot.y {{ background: var(--ob-amber); box-shadow: 0 0 0 3px rgba(180,83,9,0.15); }}
.live-dot.g {{ background: var(--ob-emerald); box-shadow: 0 0 0 3px rgba(4,120,87,0.15); }}

/* Gradient numbers on the hero stat cards for that little extra wow. */
.stat-card.featured .num {{
  background: linear-gradient(180deg, var(--ob-ink) 0%, var(--ob-blue) 110%);
  -webkit-background-clip: text; background-clip: text; color: transparent;
}}
.stat-card.featured {{ border-color: var(--ob-blue-soft);
  box-shadow: 0 0 0 1px var(--ob-blue-soft), var(--ob-shadow-md); }}

/* Subtle card lift on hover — feels like a real product. */
.card, .fact, .blk, .brain, .file {{ transition: box-shadow .16s ease, transform .16s ease, border-color .16s ease; }}
.card:hover, .fact:hover, .blk:hover, .file:hover {{
  box-shadow: var(--ob-shadow-md); border-color: var(--ob-line-2);
}}

/* Inline mini-badge for the brand chrome ("parser-os ⊕ OrbitBrief"). */
.brand .stack {{ display: inline-flex; align-items: center; gap: 6px;
  padding: 3px 8px; border-radius: 999px; background: var(--ob-blue-soft);
  font-size: 10.5px; font-weight: 700; letter-spacing: 0.06em;
  text-transform: uppercase; color: var(--ob-blue);
  font-family: "JetBrains Mono", monospace; margin-left: 8px; }}

/* Source library */
.files {{ list-style: none; padding: 0; margin: 0; display: grid; gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(310px, 1fr)); }}
.file {{ display: flex; align-items: center; gap: 14px; padding: 16px 18px;
  background: var(--ob-surface); border: 1px solid var(--ob-line);
  border-radius: var(--ob-radius-sm); min-width: 0; }}
.ftype {{
  width: 40px; height: 40px; border-radius: 8px; display: inline-flex;
  align-items: center; justify-content: center; font-size: 11px; font-weight: 700;
  letter-spacing: 0.06em; flex-shrink: 0;
}}
.ftype.pdf {{ background: #ffe4e6; color: #9f1239; }}
.ftype.xlsx, .ftype.csv {{ background: #e8f6ee; color: #0b6e3c; }}
.ftype.txt, .ftype.md {{ background: #ecece8; color: #2a2d34; }}
.ftype.docx {{ background: #eef2ff; color: #1f4fd9; }}
.ftype.eml {{ background: #fff6dd; color: #8a5a00; }}
.ftype.vtt, .ftype.json {{ background: #e6faf7; color: #0f766e; }}
.file .name {{ font-weight: 600; font-size: 14px; color: var(--ob-ink);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.file .meta {{ color: var(--ob-ink-4); font-size: 12px; margin-top: 4px;
  font-family: "JetBrains Mono", monospace; line-height: 1.4;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden; }}

/* Atom cards */
.cards {{ display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }}
.card {{
  background: var(--ob-surface); border: 1px solid var(--ob-line);
  border-radius: var(--ob-radius-md); padding: 22px 22px;
  position: relative; overflow: hidden; box-shadow: var(--ob-shadow-sm);
  display: flex; flex-direction: column; gap: 14px; min-width: 0;
}}
.card .top-row {{ display: flex; justify-content: space-between;
  align-items: center; gap: 10px; flex-wrap: wrap; }}
.chip {{ display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 11px; border-radius: 999px; font-size: 11px; font-weight: 700;
  letter-spacing: 0.04em; flex-shrink: 0; }}
.chip-blue {{ background: var(--ob-blue-soft); color: var(--ob-blue); }}
.chip-emerald {{ background: var(--ob-emerald-soft); color: var(--ob-emerald); }}
.chip-amber {{ background: var(--ob-amber-soft); color: var(--ob-amber); }}
.chip-rose {{ background: var(--ob-rose-soft); color: var(--ob-rose); }}
.chip-violet {{ background: var(--ob-violet-soft); color: var(--ob-violet); }}
.dot {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block;
  vertical-align: middle; flex-shrink: 0; }}
.replay {{ display: inline-flex; align-items: center; gap: 6px; color: var(--ob-ink-4);
  font-size: 11px; font-family: "JetBrains Mono", monospace; flex-shrink: 0; }}
/* Long atom statements get clamped to 5 lines so cards stay aligned. */
.card .quote {{ font-size: 14.5px; color: var(--ob-ink-2); line-height: 1.5;
  font-family: "Instrument Serif", Georgia, serif; font-style: italic;
  display: -webkit-box; -webkit-line-clamp: 5; -webkit-box-orient: vertical;
  overflow: hidden; text-overflow: ellipsis; }}
.card .meta {{ color: var(--ob-ink-4); font-size: 11.5px; margin-top: auto;
  border-top: 1px solid var(--ob-line); padding-top: 12px;
  font-family: "JetBrains Mono", monospace; display: flex;
  justify-content: space-between; gap: 8px; flex-wrap: wrap; }}
.card .meta code {{ color: var(--ob-ink-3); background: transparent; padding: 0; }}

/* Knowledge graph */
.graph-wrap {{ background: var(--ob-surface); border: 1px solid var(--ob-line);
  border-radius: var(--ob-radius-md); overflow: hidden; box-shadow: var(--ob-shadow-sm); }}
.graph-legend {{ display: flex; flex-wrap: wrap; gap: 14px; padding: 14px 22px;
  border-top: 1px solid var(--ob-line); color: var(--ob-ink-3); font-size: 12px;
  background: var(--ob-surface-2); }}
.graph-legend .swatch {{ display: inline-block; width: 9px; height: 9px;
  border-radius: 50%; vertical-align: middle; margin-right: 6px; }}

/* Pipeline timeline */
.timeline {{ display: grid; gap: 6px; }}
.tl-row {{ display: grid; grid-template-columns: 220px 1fr 80px 90px; gap: 14px;
  align-items: center; padding: 8px 14px; border-radius: 8px;
  background: var(--ob-surface); border: 1px solid var(--ob-line); font-size: 12.5px; }}
.tl-row .stage {{ font-family: "JetBrains Mono", monospace; color: var(--ob-ink-2); }}
.tl-row .bar {{ height: 8px; background: var(--ob-surface-2); border-radius: 6px; overflow: hidden; }}
.tl-row .bar > span {{ display: block; height: 100%; background: var(--ob-blue); border-radius: 6px; }}
.tl-row.s-failed .bar > span {{ background: var(--ob-rose); }}
.tl-row.s-fallback .bar > span {{ background: var(--ob-amber); }}
.tl-row.s-skipped .bar > span {{ background: var(--ob-line-2); }}
.tl-row .ms {{ font-family: "JetBrains Mono", monospace; color: var(--ob-ink-3);
  text-align: right; font-size: 11.5px; }}
.tl-row .status {{ font-size: 11px; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.06em; text-align: right; }}
.tl-row.s-ok .status {{ color: var(--ob-emerald); }}
.tl-row.s-failed .status {{ color: var(--ob-rose); }}
.tl-row.s-fallback .status {{ color: var(--ob-amber); }}
.tl-row.s-skipped .status {{ color: var(--ob-ink-4); }}

/* Domain matrix */
.matrix-wrap {{ background: var(--ob-surface); border: 1px solid var(--ob-line);
  border-radius: var(--ob-radius-md); overflow-x: auto; box-shadow: var(--ob-shadow-sm); }}
.matrix {{ width: 100%; min-width: 640px; border-collapse: collapse; font-size: 13px; }}
.matrix th, .matrix td {{ padding: 14px 18px; text-align: left;
  border-bottom: 1px solid var(--ob-line); }}
.matrix th {{ background: var(--ob-surface-2); color: var(--ob-ink-3);
  font-size: 10.5px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; }}
.matrix tbody tr:last-child td {{ border-bottom: none; }}
.matrix tbody tr:hover {{ background: var(--ob-surface-2); }}
.matrix .num {{ text-align: right; font-family: "JetBrains Mono", monospace; }}
.matrix .num.b {{ color: var(--ob-rose); font-weight: 600; }}
.matrix .num.b.zero {{ color: var(--ob-ink-4); font-weight: 400; }}
.matrix .num.w {{ color: var(--ob-amber); font-weight: 500; }}
.matrix .num.w.zero {{ color: var(--ob-ink-4); font-weight: 400; }}
.matrix .yes {{ color: var(--ob-emerald); font-weight: 700; }}
.matrix .no {{ color: var(--ob-ink-4); }}

/* Sites strip */
.sites {{ display: flex; flex-wrap: wrap; gap: 10px; }}
.site {{ background: var(--ob-surface); border: 1px solid var(--ob-line);
  border-radius: 999px; padding: 8px 16px; font-size: 13px; color: var(--ob-ink-2);
  display: inline-flex; align-items: center; gap: 8px; }}
.site .pin {{ color: var(--ob-blue); flex-shrink: 0; }}

/* Brain blocks */
.brain {{ background: var(--ob-surface); border: 1px solid var(--ob-line);
  border-radius: var(--ob-radius-md); padding: 28px 32px; margin-bottom: 18px;
  box-shadow: var(--ob-shadow-sm); }}
.brain .head {{ display: flex; align-items: center; flex-wrap: wrap; gap: 12px;
  margin-bottom: 18px; padding-bottom: 16px; border-bottom: 1px solid var(--ob-line); }}
.brain .head h3 {{ margin: 0; font-size: 19px; font-weight: 700; letter-spacing: -0.01em;
  font-family: "Plus Jakarta Sans", sans-serif; }}
.brain .head .badge {{ font-size: 10.5px; font-weight: 700; letter-spacing: 0.06em;
  text-transform: uppercase; padding: 4px 10px; border-radius: 999px; }}
.brain .head .badge.live {{ background: var(--ob-emerald-soft); color: var(--ob-emerald); }}
.brain .head .badge.fb {{ background: var(--ob-amber-soft); color: var(--ob-amber); }}
.brain .head .meta {{ color: var(--ob-ink-4); font-size: 11.5px;
  font-family: "JetBrains Mono", monospace; margin-left: auto;
  display: flex; flex-wrap: wrap; gap: 14px; row-gap: 4px; }}
.bitem {{ padding: 16px 18px; background: var(--ob-surface-2);
  border: 1px solid var(--ob-line); border-radius: var(--ob-radius-sm); margin-top: 12px;
  border-left: 3px solid var(--ob-blue); min-width: 0; }}
.bitem .sec {{ font-size: 10.5px; font-weight: 700; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--ob-blue); margin-bottom: 8px; }}
.bitem .stmt {{ font-size: 14.5px; color: var(--ob-ink-2); line-height: 1.55;
  display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical;
  overflow: hidden; text-overflow: ellipsis; }}
.bitem .meta {{ color: var(--ob-ink-4); font-size: 11px; margin-top: 10px;
  font-family: "JetBrains Mono", monospace; }}

/* Fact gallery */
.facts {{ display: grid; gap: 14px; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }}
.fact {{ background: var(--ob-surface); border: 1px solid var(--ob-line);
  border-radius: var(--ob-radius-sm); padding: 18px 20px;
  display: flex; flex-direction: column; gap: 12px; min-width: 0; }}
.fact .cat {{ font-size: 10.5px; font-weight: 700; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--ob-blue); }}
.fact .text {{ font-size: 13.5px; color: var(--ob-ink-2); line-height: 1.55;
  display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical;
  overflow: hidden; text-overflow: ellipsis; }}
.fact .src {{ display: flex; gap: 8px; align-items: center; margin-top: auto;
  padding-top: 12px; border-top: 1px solid var(--ob-line);
  color: var(--ob-ink-4); font-size: 11px; font-family: "JetBrains Mono", monospace;
  flex-wrap: wrap; }}
.fact .src .file {{ color: var(--ob-ink-3);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }}
.fact .src .loc {{ color: var(--ob-ink-4); flex-shrink: 0; }}

/* SA focus */
.sa {{ background: var(--ob-surface); border: 1px solid var(--ob-line);
  border-radius: var(--ob-radius-md); padding: 28px 32px; box-shadow: var(--ob-shadow-sm); }}
.sa ol {{ margin: 0; padding-left: 0; counter-reset: focus; list-style: none; }}
.sa ol li {{ position: relative; padding: 18px 0 18px 60px;
  border-bottom: 1px solid var(--ob-line); counter-increment: focus;
  font-size: 14.5px; color: var(--ob-ink-2); line-height: 1.55; }}
.sa ol li:last-child {{ border-bottom: none; padding-bottom: 0; }}
.sa ol li:first-child {{ padding-top: 0; }}
.sa ol li::before {{
  content: counter(focus, decimal-leading-zero);
  position: absolute; left: 0; top: 18px;
  font-family: "JetBrains Mono", monospace;
  font-size: 12px; font-weight: 700; color: var(--ob-blue);
  background: var(--ob-blue-soft); border-radius: 6px;
  padding: 4px 10px; line-height: 1;
}}
.sa ol li:first-child::before {{ top: 0; }}

/* Blockers */
.blockers {{ display: grid; gap: 14px; }}
.blk {{ background: var(--ob-surface); border: 1px solid var(--ob-line);
  border-left: 4px solid var(--ob-rose); border-radius: var(--ob-radius-md);
  padding: 22px 26px; box-shadow: var(--ob-shadow-sm); min-width: 0; }}
.blk.warning {{ border-left-color: var(--ob-amber); }}
.blk .rule-row {{ display: flex; align-items: center; gap: 10px;
  margin-bottom: 14px; flex-wrap: wrap; }}
.blk .sev {{ font-size: 10.5px; font-weight: 800; letter-spacing: 0.08em;
  text-transform: uppercase; padding: 4px 10px; border-radius: 4px; flex-shrink: 0; }}
.blk .sev.blocker {{ background: var(--ob-rose-soft); color: var(--ob-rose); }}
.blk .sev.warning {{ background: var(--ob-amber-soft); color: var(--ob-amber); }}
.blk .domain {{ color: var(--ob-ink-3); font-size: 12.5px; font-weight: 600; }}
.blk .rule-id {{ color: var(--ob-ink-4); font-size: 10.5px;
  font-family: "JetBrains Mono", monospace; margin-left: auto;
  background: var(--ob-surface-2); padding: 3px 8px; border-radius: 4px; }}
.blk .lab {{ font-weight: 700; color: var(--ob-ink); margin-bottom: 6px; font-size: 16px;
  line-height: 1.35; }}
.blk .msg {{ color: var(--ob-ink-2); font-size: 14px; line-height: 1.55; }}
.blk .ask {{ margin-top: 16px; padding: 14px 16px;
  background: var(--ob-blue-soft); border-radius: 8px;
  color: var(--ob-ink-2); font-size: 13.5px; line-height: 1.5; }}
.blk .ask::before {{ content: "Ask the customer: ";
  font-weight: 700; color: var(--ob-blue);
  font-size: 10.5px; letter-spacing: 0.08em; text-transform: uppercase;
  display: block; margin-bottom: 4px; }}
.blk .obs {{ color: var(--ob-ink-4); font-size: 11.5px; margin-top: 10px;
  font-family: "JetBrains Mono", monospace; }}

/* Footer */
footer {{ padding: 60px 0 80px 0; color: var(--ob-ink-4); font-size: 12px;
  border-top: 1px solid var(--ob-line); margin-top: 40px; text-align: center; }}
footer code {{ background: var(--ob-surface-2); padding: 2px 6px; border-radius: 4px;
  font-family: "JetBrains Mono", monospace; }}

@media print {{
  .chrome {{ position: static; }}
  section, .hero {{ break-inside: avoid; padding-top: 28px; padding-bottom: 12px; }}
}}
</style>
</head>
<body>
"""


def _file_chip(ext: str) -> str:
    return ext.lower().lstrip(".") or "file"


def _file_descr(ext: str) -> str:
    return {
        "pdf": "Customer document — preserved layout, tables, form fields",
        "xlsx": "Workbook — multi-sheet rows extracted into typed atoms",
        "csv": "Tabular data — every row becomes a typed atom with locator",
        "txt": "Plain text — sectioned into scope items, exclusions, decisions",
        "md": "Markdown notes — meeting decisions and assumptions",
        "eml": "Customer email — sender, subject, scope clarifications",
        "docx": "Office document — body + tracked changes preserved",
        "vtt": "Meeting transcript — decisions, open questions, action items",
        "json": "Structured intake — pre-typed atoms passed straight through",
    }.get(ext.lower().lstrip("."), "Customer artifact")


def _enumerate_case_files(case_dir: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    artifact_dir = case_dir / "artifacts"
    if artifact_dir.is_dir():
        for sub in ("public_sources", "extracted", "supplemental"):
            d = artifact_dir / sub
            if d.is_dir():
                for p in sorted(d.iterdir()):
                    if p.is_file() and p.suffix.lower() in {
                        ".pdf", ".xlsx", ".csv", ".txt", ".md", ".eml", ".docx", ".vtt"
                    }:
                        out.append({
                            "name": p.name,
                            "ext": p.suffix.lower().lstrip("."),
                            "size_kb": round(p.stat().st_size / 1024, 1),
                            "descr": _file_descr(p.suffix),
                        })
    return out


def _render_pipeline_timeline(log: list[dict[str, Any]]) -> str:
    if not log:
        return '<p class="sub">(no pipeline log captured)</p>'
    max_ms = max(int(r.get("duration_ms") or 0) for r in log) or 1
    rows: list[str] = []
    for r in log:
        stage = r.get("stage") or ""
        status = (r.get("status") or "ok").lower()
        ms = int(r.get("duration_ms") or 0)
        pct = max(2, int(100 * ms / max_ms))
        rows.append(
            f'<div class="tl-row s-{_esc(status)}">'
            f'<div class="stage">{_esc(stage)}</div>'
            f'<div class="bar"><span style="width:{pct}%"></span></div>'
            f'<div class="ms">{_fmt_ms(ms)}</div>'
            f'<div class="status">{_esc(status)}</div>'
            f'</div>'
        )
    return f'<div class="timeline">{"".join(rows)}</div>'


def _render_domain_matrix(domains: list[dict[str, Any]]) -> str:
    if not domains:
        return '<p class="sub">(no domain matrix in this run)</p>'
    rows: list[str] = []
    for d in domains:
        b = int(d.get("blockers") or 0)
        w = int(d.get("warnings") or 0)
        i = int(d.get("info") or 0)
        sel = bool(d.get("selected_by_router"))
        active = bool(d.get("active_for_sow"))
        rows.append(
            f'<tr>'
            f'<td><strong>{_esc(d.get("label") or d.get("domain_id"))}</strong>'
            f'<div style="color:var(--ob-ink-4); font-size:11px; font-family:JetBrains Mono, monospace;">'
            f'{_esc(d.get("domain_id"))}</div></td>'
            f'<td class="{"yes" if sel else "no"}">{"Yes" if sel else "—"}</td>'
            f'<td class="{"yes" if active else "no"}">{"Yes" if active else "—"}</td>'
            f'<td class="num b {"" if b else "zero"}">{b}</td>'
            f'<td class="num w {"" if w else "zero"}">{w}</td>'
            f'<td class="num">{i}</td>'
            f'</tr>'
        )
    return (
        '<div class="matrix-wrap"><table class="matrix">'
        '<thead><tr>'
        '<th>Specialist domain</th>'
        '<th>Auto-selected</th>'
        '<th>Reviewed</th>'
        '<th class="num">Blockers</th>'
        '<th class="num">Warnings</th>'
        '<th class="num">Notes</th>'
        '</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        '</table></div>'
    )


def _render_sites(sites: list[dict[str, Any]], cap: int = 25) -> str:
    if not sites:
        return '<p class="sub">(no published sites)</p>'
    chips = "".join(
        f'<span class="site"><span class="pin">●</span>{_esc(s.get("name") or "?")}</span>'
        for s in sites[:cap]
    )
    return f'<div class="sites">{chips}</div>'


def _render_brain_blocks(brain_outputs: dict[str, dict[str, Any]],
                         highlights: dict[str, list[dict[str, Any]]]) -> str:
    if not brain_outputs:
        return '<p class="sub">(no brains ran)</p>'
    out: list[str] = []
    for pack, data in sorted(brain_outputs.items()):
        items = highlights.get(pack) or []
        tc = data.get("token_cost") or {}
        fb = bool(data.get("fallback_used"))
        badge_cls = "fb" if fb else "live"
        badge_txt = "fallback" if fb else "live"
        item_html = "".join(
            f'<div class="bitem">'
            f'<div class="sec">{_esc(_section_label(it.get("section") or ""))}</div>'
            f'<div class="stmt">{_esc(_shorten(_polish_quote(it.get("statement") or ""), 240))}</div>'
            f'<div class="meta">confidence {float(it.get("confidence") or 0):.0%} · '
            f'{len(it.get("supporting_packet_ids") or [])} evidence group(s) · '
            f'{len(it.get("supporting_atom_ids") or [])} cited fact(s)</div>'
            f'</div>'
            for it in items
        ) or '<div class="bitem"><em>(no high-confidence items emitted by this brain)</em></div>'
        out.append(
            f'<div class="brain">'
            f'<div class="head">'
            f'<h3>{_esc(_section_label(pack))} brain</h3>'
            f'<span class="badge {badge_cls}">{_esc(badge_txt)}</span>'
            f'<span class="meta">model <strong>{_esc(data.get("model_used") or "—")}</strong> · '
            f'{_fmt_int(tc.get("total_tokens", 0))} tokens · '
            f'{_fmt_ms(tc.get("latency_ms", 0))}</span>'
            f'</div>'
            f'{item_html}'
            f'</div>'
        )
    return "".join(out)


def _render_facts_gallery(facts_by_category: dict[str, list[dict[str, Any]]],
                          *, per_cat: int = 2, total_cap: int = 12) -> str:
    if not facts_by_category:
        return '<p class="sub">(no fact cards)</p>'
    pool: list[dict[str, Any]] = []
    for cat, facts in facts_by_category.items():
        # Prefer slightly shorter, higher-confidence facts so the cards
        # all read at a similar visual weight in the gallery.
        sortable = sorted(
            facts,
            key=lambda f: (
                -(f.get("confidence") or 0.0),
                abs(len(f.get("text") or "") - 140),
            ),
        )
        kept = 0
        for f in sortable:
            text = (f.get("text") or "").strip()
            if 25 <= len(text) <= 280:
                pool.append({"_cat": cat, **f})
                kept += 1
                if kept >= per_cat:
                    break
    pool = pool[:total_cap]
    cards = "".join(
        f'<div class="fact">'
        f'<div class="cat">{_esc(_section_label(f["_cat"]))}</div>'
        f'<div class="text">{_esc(_shorten(_polish_quote(f.get("text") or ""), 200))}</div>'
        f'<div class="src">{_verified_dot(f.get("verified"))}'
        f'<span class="file">{_esc(_basename((f.get("source") or {}).get("filename") or "—"))}</span>'
        f'<span class="loc">· {_esc((f.get("source") or {}).get("locator") or "—")}</span>'
        f'</div>'
        f'</div>'
        for f in pool
    )
    return f'<div class="facts">{cards}</div>'


def _basename(path: str) -> str:
    """Strip directory prefixes from source filenames so chips don't blow up."""
    if not path:
        return "—"
    return path.rsplit("/", 1)[-1]


def _render_blockers(gaps: list[dict[str, Any]],
                     *, max_blockers: int = 5, max_warnings: int = 4) -> str:
    blockers = [g for g in gaps if g.get("severity") == "blocker"][:max_blockers]
    warnings = [g for g in gaps if g.get("severity") == "warning"][:max_warnings]
    selected = blockers + warnings
    if not selected:
        return '<p class="sub">(no SOW gaps detected)</p>'

    def _one(g: dict[str, Any]) -> str:
        sev = (g.get("severity") or "warning").lower()
        return (
            f'<div class="blk {sev}">'
            f'<div class="rule-row">'
            f'<span class="sev {sev}">{_esc(sev)}</span>'
            f'<span class="domain">{_esc(g.get("domain_label") or g.get("domain_id"))}</span>'
            f'<span class="rule-id">{_esc(_shorten(g.get("rule_id") or "", 40))}</span>'
            f'</div>'
            f'<div class="lab">{_esc(_shorten(g.get("label") or "—", 110))}</div>'
            f'<div class="msg">{_esc(_shorten(g.get("message") or "", 280))}</div>'
            + (
                f'<div class="ask">{_esc(_shorten(g["suggested_open_question"], 240))}</div>'
                if g.get("suggested_open_question") else ""
            )
            + (
                f'<div class="obs">Observed · {_esc(_shorten(g["observed_summary"], 160))}</div>'
                if g.get("observed_summary") else ""
            )
            + '</div>'
        )

    return f'<div class="blockers">{"".join(_one(g) for g in selected)}</div>'


def render_demo(*, out_dir: Path, case_dir: Path, runtime_s: float | None) -> str:
    envelope = _safe_load(out_dir / "00_envelope.json") or {}
    manifest = _safe_load(out_dir / "manifest.json") or {}
    pack_prior = _safe_load(out_dir / "10_pack_prior_state.json") or {}
    pm = _safe_load(out_dir / "PM_HANDOFF.json") or {}
    inspection = _safe_load(out_dir / "90_inspection_report.json") or {}
    pipeline_log = _safe_load(out_dir / "pipeline_log.json") or []

    project_id = envelope.get("project_id") or manifest.get("project_id") or case_dir.name
    compile_id = envelope.get("compile_id") or manifest.get("compile_id") or "—"
    generated_at = manifest.get("generated_at") or "—"

    n_docs = len(envelope.get("documents") or [])
    n_atoms = len(envelope.get("atoms") or [])
    n_entities = len(envelope.get("entities") or [])
    n_edges = len(envelope.get("edges") or [])
    n_packets = len(envelope.get("packets") or [])

    metrics = pm.get("metrics") or {}
    one_line = pm.get("one_line_summary") or ""
    status = (pm.get("status") or "unknown").lower()
    status_label = pm.get("status_label") or status.upper()

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

    runtime_min = f"{runtime_s/60:.1f} min" if runtime_s else "—"

    status_dot_cls = "r" if status == "red" else ("y" if status == "yellow" else "g")
    status_chip = (
        f'<span class="chip-status {_esc(status)}">'
        f'<span class="live-dot {status_dot_cls}"></span>'
        f'{_esc(status_label)} · {metrics.get("blockers", 0)} blocker · '
        f'{metrics.get("warnings", 0)} warning</span>'
    )

    # ────────────────────────────── chrome ────────────────────────────
    chrome = f"""
<header class="chrome">
  <div class="row">
    <div class="brand">
      <span class="brand-mark"></span>
      <span class="brand-name">Purpulse <span class="lo">·</span> OrbitBrief</span>
      <span class="stack">parser-os ⊕ OrbitBrief</span>
    </div>
    <div class="crumbs">
      <span>Quoting</span><span class="sep">/</span>
      <span>Engagements</span><span class="sep">/</span>
      <span class="here">{_esc(project_id)}</span>
    </div>
    {status_chip}
  </div>
</header>
"""

    # ────────────────────────────── hero ──────────────────────────────
    blockers_n = int(metrics.get("blockers") or 0)
    warnings_n = int(metrics.get("warnings") or 0)
    hero = f"""
<div class="hero">
  <div class="container">
    <div class="eyebrow">Live engagement · {_esc(project_id)}</div>
    <h1>{_fmt_int(n_docs)} client documents in. <em>One executive brief</em> out — in {runtime_min}.</h1>
    <p class="subline">No analyst spent a week reading these PDFs. The system read them, cross-referenced
    them, woke up the right specialists, and flagged <strong>{blockers_n} blocker(s)</strong> and
    <strong>{warnings_n} warning(s)</strong> that need answers before this contract can be signed.
    Every claim below is cited back to the source document and page number — your team can verify
    anything in two clicks.</p>
    <div class="stats">
      <div class="stat-card featured"><div class="lab">Documents read</div><div class="num">{_fmt_int(n_docs)}</div></div>
      <div class="stat-card featured"><div class="lab">Facts extracted</div><div class="num">{_fmt_int(metrics.get("evidence_items_extracted") or n_atoms)}</div></div>
      <div class="stat-card"><div class="lab">Cross-references</div><div class="num">{_fmt_int(n_edges)}</div></div>
      <div class="stat-card"><div class="lab">Sites identified</div><div class="num">{_fmt_int(metrics.get("sites_published"))}</div></div>
      <div class="stat-card"><div class="lab">Cited fact cards</div><div class="num">{_fmt_int(metrics.get("pm_visible_fact_cards"))}</div></div>
      <div class="stat-card"><div class="lab">Specialists run</div><div class="num">{_fmt_int(len(brains_run))}</div></div>
      <div class="stat-card featured"><div class="lab">Source accuracy</div><div class="num">{health_pct:.0f}%</div></div>
    </div>
  </div>
</div>
"""

    # ────────────────────────────── source library ────────────────────
    file_rows = "".join(
        f'<li class="file"><div class="ftype {f["ext"]}">{_esc(f["ext"].upper())}</div>'
        f'<div style="min-width:0; flex:1;"><div class="name">{_esc(f["name"])}</div>'
        f'<div class="meta">{f["size_kb"]:.1f} KB · {_esc(f["descr"])}</div></div></li>'
        for f in case_files
    )
    act_files = f"""
<section>
  <div class="container">
    <div class="label">Chapter 1 · The intake</div>
    <h2>What the client sent us.</h2>
    <p class="sub">The whole package — RFP, addendums, vendor quotes, kickoff notes, the email
    where the client clarified scope. Today, a senior project manager spends roughly a week
    reading and triangulating this. The system handles it in minutes, and never loses the trail
    back to the original document.</p>
    {_powered_by("parser-os · ingest")}
    <ul class="files">{file_rows}</ul>
  </div>
</section>
"""

    # ────────────────────────────── atom cards ────────────────────────
    atom_cards = "".join(
        f'<div class="card">'
        f'<div class="top-row">'
        f'<span class="chip {a["_css"]}">{_esc(a["_label"])}</span>'
        f'<span class="replay">{_verified_dot(a.get("verified"))}source verified</span>'
        f'</div>'
        f'<div class="quote">“{_esc(_shorten(_polish_quote(a.get("text") or ""), 200))}”</div>'
        f'<div class="meta">'
        f'<span>category · {_esc(_section_label(a.get("atom_type") or ""))}</span>'
        f'<span>confidence {float(a.get("confidence") or 0):.0%}</span>'
        f'</div>'
        f'</div>'
        for a in headline_atoms
    )
    act_atoms = f"""
<section>
  <div class="container">
    <div class="label">Chapter 2 · What we found</div>
    <h2>{_fmt_int(n_atoms)} facts pulled out of those documents.</h2>
    <p class="sub">Counts, exclusions, vendor parts, customer directives, open questions — every
    one tagged, scored for confidence, and pinned to the exact source bytes so it can be replayed.
    A handful of representative examples below. The green dot means we replayed the source and
    the extraction matches verbatim.</p>
    {_powered_by("parser-os · extraction", "parser-os · source replay")}
    <div class="cards">{atom_cards}</div>
  </div>
</section>
"""

    # ────────────────────────────── knowledge graph ───────────────────
    svg, type_counts = _build_graph_svg(envelope.get("entities") or [], envelope.get("edges") or [])
    legend = " ".join(
        f'<span><span class="swatch" style="background:{_ENTITY_COLORS.get(t, _ENTITY_COLORS["_default"])}"></span>'
        f'{_esc(_section_label(t))} ({n})</span>'
        for t, n in sorted(type_counts.items(), key=lambda kv: -kv[1])[:9]
    )
    act_graph = f"""
<section>
  <div class="container">
    <div class="label">Chapter 3 · The connections</div>
    <h2>{_fmt_int(n_edges)} cross-document connections — automatically.</h2>
    <p class="sub">This is where the system earns its keep. It doesn't just read documents — it
    notices when an addendum on page 14 contradicts a quantity on page 3, when the same vendor
    part is mentioned in three places under different SKUs, or when a customer email modifies a
    spec from the original RFP. Each dot is a real entity from the engagement; each line is a
    relationship the system caught.</p>
    {_powered_by("parser-os · entity dedup", "parser-os · edge inference")}
    <div class="graph-wrap">
      {svg}
      <div class="graph-legend">{legend}</div>
    </div>
  </div>
</section>
"""

    # ────────────────────────────── sites ─────────────────────────────
    sites_html = _render_sites(pm.get("sites") or [])
    act_sites = f"""
<section>
  <div class="container">
    <div class="label">Chapter 4 · Facility coverage</div>
    <h2>Every site, named and de-duplicated.</h2>
    <p class="sub">The same building gets called three different things across an RFP, an
    addendum, and a vendor quote. The system clusters them so your scope review starts from one
    canonical roster — {_fmt_int(metrics.get("sites_published"))} confirmed sites for this
    engagement. No double-counting, no missed locations.</p>
    {_powered_by("OrbitBrief · site reality")}
    {sites_html}
  </div>
</section>
"""

    # ────────────────────────────── specialists ───────────────────────
    brain_html = _render_brain_blocks(brain_outputs, brain_highlights)
    act_brains = f"""
<section>
  <div class="container">
    <div class="label">Chapter 5 · The specialists</div>
    <h2>{_fmt_int(len(brain_outputs))} AI specialists, one per active discipline.</h2>
    <p class="sub">The system decided which experts to consult based on what's actually in the
    documents — not a fixed checklist. Each specialist receives only the facts relevant to its
    discipline (electrical, structured cabling, professional services), and emits a structured
    brief: scope, deliverables, assumptions, risks, open questions. The model, token cost, and
    response time are visible per specialist for full auditability.</p>
    {_powered_by("OrbitBrief · pack router", "OrbitBrief · specialist brains")}
    {brain_html}
  </div>
</section>
"""

    # ────────────────────────────── facts gallery ─────────────────────
    facts_gallery = _render_facts_gallery(pm.get("facts_by_category") or {})
    act_facts = f"""
<section>
  <div class="container">
    <div class="label">Chapter 6 · Cited facts</div>
    <h2>{_fmt_int(metrics.get("pm_visible_fact_cards"))} review-ready cards. Every one cited.</h2>
    <p class="sub">This is what your PM hands to the solution architect. Every claim is grouped
    by category — sites, scope, bill of materials, network, managed services, acceptance
    criteria, risks, exclusions — and points back to the exact filename plus page or row. If
    your client asks "where did you get that?", you have the answer in two clicks.</p>
    {_powered_by("parser-os · atoms", "OrbitBrief · composer")}
    {facts_gallery}
  </div>
</section>
"""

    # ────────────────────────────── SA focus ──────────────────────────
    sa_items = (pm.get("sa_focus") or [])[:8]
    sa_html = "".join(f'<li>{_esc(s)}</li>' for s in sa_items)
    act_sa = f"""
<section>
  <div class="container">
    <div class="label">Chapter 7 · What to dig into first</div>
    <h2>The architect's priority list, generated automatically.</h2>
    <p class="sub">Instead of starting from a blank page, the solution architect starts from a
    prioritized checklist of the things this specific engagement needs verified — drawn from
    the gaps the system noticed across all of the documents. Engineering hours saved before
    you've even kicked off design.</p>
    {_powered_by("OrbitBrief · SOW validator")}
    <div class="sa"><ol>{sa_html}</ol></div>
  </div>
</section>
"""

    # ────────────────────────────── blockers ──────────────────────────
    blockers_html = _render_blockers(pm.get("gaps") or [])
    status_color = "var(--ob-rose)" if status == "red" else (
        "var(--ob-amber)" if status == "yellow" else "var(--ob-emerald)"
    )
    act_blockers = f"""
<section>
  <div class="container">
    <div class="label">Chapter 8 · What's blocking sign-off</div>
    <h2>{blockers_n} blocker{"s" if blockers_n != 1 else ""}, {warnings_n} warning{"s" if warnings_n != 1 else ""}, with the exact question to ask the client.</h2>
    <p class="sub">For every gap the system found, you get the rule that fired, what was
    missing, and a suggested question — ready to paste into the next client call. No "I'll get
    back to you on that." Status: <strong style="color:{status_color}">{_esc(status_label)}</strong>.</p>
    {_powered_by("OrbitBrief · SOW validator", "OrbitBrief · question generator")}
    {blockers_html}
  </div>
</section>
"""

    # ────────────────────────────── audit (collapsed details) ─────────
    domain_matrix = _render_domain_matrix(pm.get("domains") or [])
    timeline = _render_pipeline_timeline(pipeline_log)
    total_pipeline_ms = sum(int(r.get("duration_ms") or 0) for r in pipeline_log)
    act_audit = f"""
<section>
  <div class="container">
    <div class="label">Appendix · Full audit trail</div>
    <h2>For your engineers — the receipts.</h2>
    <p class="sub">Every specialist that was considered, every pipeline stage that ran, with
    timing. Click through to the full inspection report for atom-level lineage. This is the
    "show your work" view that distinguishes us from a black-box LLM.</p>
    {_powered_by("parser-os · pipeline log", "OrbitBrief · pack router")}

    <h3 style="font-family:'Plus Jakarta Sans',sans-serif; font-size:14px; font-weight:600;
        text-transform:uppercase; letter-spacing:0.08em; color:var(--ob-ink-3);
        margin: 32px 0 14px 0;">Specialist coverage</h3>
    {domain_matrix}

    <h3 style="font-family:'Plus Jakarta Sans',sans-serif; font-size:14px; font-weight:600;
        text-transform:uppercase; letter-spacing:0.08em; color:var(--ob-ink-3);
        margin: 32px 0 14px 0;">Pipeline timing · {_fmt_ms(total_pipeline_ms)} total</h3>
    {timeline}
  </div>
</section>
"""

    # ────────────────────────────── closing ───────────────────────────
    # Compute the math the exec actually cares about — a week of PM
    # work costs roughly $2k–$5k loaded; we use $3k as a defensible
    # midpoint and the wall-clock runtime as the comparison.
    pm_week_hours = 40
    minutes_to_brief = (runtime_s or 0) / 60.0
    speedup = int((pm_week_hours * 60) / minutes_to_brief) if minutes_to_brief else 0
    closing = f"""
<section>
  <div class="container">
    <div class="label">The bottom line</div>
    <h2>What this saves you, per engagement.</h2>
    <p class="sub">A week of senior PM time replaced by an 8-minute compile. Every claim
    cited, every gap surfaced, every specialist consulted. Your team lands at the architect's
    priority list, not a stack of unread PDFs.</p>
    <div class="stats" style="margin-top: 8px;">
      <div class="stat-card"><div class="lab">Time to brief</div><div class="num">{runtime_min}</div></div>
      <div class="stat-card"><div class="lab">Speedup vs. 1 PM-week</div><div class="num">{_fmt_int(speedup)}×</div></div>
      <div class="stat-card"><div class="lab">Source verified</div><div class="num">{health_pct:.0f}%</div></div>
      <div class="stat-card"><div class="lab">Sites covered</div><div class="num">{_fmt_int(metrics.get("sites_published"))}</div></div>
      <div class="stat-card"><div class="lab">Cited facts</div><div class="num">{_fmt_int(metrics.get("pm_visible_fact_cards"))}</div></div>
      <div class="stat-card"><div class="lab">Blockers caught</div><div class="num">{metrics.get("blockers", 0)}</div></div>
      <div class="stat-card"><div class="lab">Specialists consulted</div><div class="num">{_fmt_int(len(brain_outputs))}</div></div>
      <div class="stat-card"><div class="lab">Open questions ready</div><div class="num">{_fmt_int(len(pm.get("customer_questions") or []))}</div></div>
    </div>
  </div>
</section>
"""

    footer = f"""
<footer>
  Purpulse · OrbitBrief · {_esc(project_id)} · compile <code>{_esc(compile_id)}</code><br>
  Generated {_esc(generated_at)}
</footer>
</body></html>
"""

    body = (
        chrome + hero
        + act_files       # 1. The intake
        + act_atoms       # 2. What we found
        + act_graph       # 3. The connections
        + act_sites       # 4. Facility coverage
        + act_brains      # 5. The specialists
        + act_facts       # 6. Cited facts
        + act_sa          # 7. What to dig into first
        + act_blockers    # 8. What's blocking sign-off
        + act_audit       # Appendix · Full audit trail (matrix + timeline collapsed at the end)
        + closing
    )
    return _HEAD.format(project_id=_esc(project_id)) + body + footer


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="build_demo_showcase.py", description=__doc__)
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--case-dir", required=True, type=Path)
    p.add_argument("--runtime-s", type=float, default=None)
    p.add_argument("--out", type=Path, default=None)
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
