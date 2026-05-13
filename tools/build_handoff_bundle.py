"""Build a corpus-wide handoff bundle: raw source ↔ extracted artifacts.

For each engagement case in a corpus results directory, generate a
self-contained folder that pairs:

* The original raw source artifacts (PDFs / CSVs / MDs / XLSXs).
* The atoms parser-os extracted from each, in markdown table form
  (atom_id, type, authority, confidence, verified, locator, text,
  in-brief flag).
* The pack-prior decision + site-reality clusters.
* Per-pack retrieval bundles (which packets the brain actually saw).
* Brain outputs in markdown.
* The final composed brief in markdown.
* The full inspection report (HTML + JSON).
* A pre-baked LLM review prompt that operators can paste into
  ChatGPT / Claude along with the case folder for instant analysis.

Plus one top-level README, corpus overview, and master LLM prompt.

Usage::

    python tools/build_handoff_bundle.py \\
        --corpus /tmp/orbitbrief_corpus_results \\
        --source /Users/purtera/dev/purtera/testing/managed_services_sow_artifact_pack \\
        --out ~/Desktop/orbitbrief_corpus_handoff
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# ────────────────────────────── helpers ────────────────────────────────


def _safe_load(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _truncate(s: Any, n: int = 240) -> str:
    if s is None:
        return ""
    s = str(s)
    s = " ".join(s.split())
    return (s[: n - 1] + "…") if len(s) > n else s


def _pct(n: int, d: int) -> str:
    if d <= 0:
        return "0.0%"
    return f"{100.0 * n / d:.1f}%"


# ────────────────────────────── per-case content ───────────────────────


def _per_case_readme(case_id: str, case_dir: Path, summary: dict[str, Any]) -> str:
    return f"""# Case: {case_id}

This folder is one engagement case from the OrbitBrief corpus, packaged
so any LLM (ChatGPT, Claude, etc.) or human reviewer can read it cold
and reason about what the system did.

## What's in this folder

* **raw/** — the original source artifacts copied verbatim
  (PDFs, CSVs, Markdown, XLSX). What parser-os ingested.
* **extraction/atoms.md** — every atom parser-os pulled out of the
  raw artifacts, with locator, type, authority, confidence, verified
  status, and a flag indicating whether the atom landed in the final
  brief.
* **extraction/packets.md** — packets parser-os certified from the
  atoms, organized by family.
* **extraction/entities_and_edges.md** — cross-artifact entity
  normalization + the edge graph (the "GNN structure").
* **synthesis/pack_prior.md** — which OrbitBrief domain packs scored
  highest; the LLM-routed brain selection.
* **synthesis/site_reality.md** — physical-site clustering.
* **synthesis/retrieval_bundles/** — per-pack packet bundles fed to
  each brain.
* **synthesis/brain_outputs/** — typed scope state each brain emitted.
* **brief.md** — the final PM-readable composed brief.
* **lineage/raw_vs_extracted.md** — for each source artifact, raw
  preview side-by-side with extracted atoms (the killer view).
* **lineage/inspection_report.html** — single-page lineage report
  (raw → atoms → packets → bundle → brain → brief).
* **inspection_report.json** — full lineage data for programmatic use.
* **pipeline_log.json** — per-stage StageRecord (status + ms + detail).
* **manifest.json** — run-level summary.
* **LLM_REVIEW_PROMPT.md** — pre-baked prompt to give to a frontier
  LLM along with this folder for an instant quality review.

## Quick stats

| | |
|---|---|
| Source artifacts | {summary.get('source_artifact_count', 0)} files |
| Atoms extracted | {summary.get('atom_count', 0):,} |
| Entities normalized | {summary.get('entity_count', 0):,} |
| Edges built | {summary.get('edge_count', 0):,} |
| Packets certified | {summary.get('packet_count', 0):,} |
| Active packs | {", ".join(f"`{p}`" for p in summary.get('active_packs') or [])} |
| Pack prior top | `{summary.get('pack_prior_top') or '—'}` |
| Composed brief items | {summary.get('composed_items', 0)} |
| Items queued for review | {summary.get('queued_for_review', 0)} |
| Total runtime | {summary.get('total_runtime_seconds', 0):.1f}s |
"""


def _atoms_table(envelope: dict, brain_cited_atoms: set[str], in_brief_atoms: set[str]) -> str:
    """Markdown table of every atom with its downstream survival."""
    atoms = envelope.get("atoms") or []
    if not atoms:
        return "_No atoms extracted._\n"
    rows: list[str] = []
    rows.append(f"_Showing {len(atoms)} atoms. Each row is one fact parser-os extracted from the raw artifacts._\n")
    rows.append("| atom_id | type | authority | conf | verified | source artifact | locator | text | brain | brief |")
    rows.append("|---|---|---|---:|---|---|---|---|:-:|:-:|")
    for a in atoms:
        aid = a.get("id", "")
        loc = a.get("locator") or {}
        loc_str = " ".join(f"{k}={v}" for k, v in loc.items() if v not in (None, ""))
        text = _truncate(a.get("text"), 200).replace("|", "\\|")
        brain_flag = "✓" if aid in brain_cited_atoms else ""
        brief_flag = "✓" if aid in in_brief_atoms else ""
        rows.append(
            f"| `{aid}` | {a.get('atom_type', '')} | {a.get('authority_class', '')} "
            f"| {a.get('confidence', '')} | {a.get('verified', '')} "
            f"| `{a.get('artifact_id', '')}` | `{loc_str}` "
            f"| {text} | {brain_flag} | {brief_flag} |"
        )
    return "\n".join(rows) + "\n"


def _packets_table(envelope: dict, brain_cited_packets: set[str]) -> str:
    packets = envelope.get("packets") or []
    if not packets:
        return "_No packets certified._\n"
    by_family: dict[str, list[dict]] = {}
    for p in packets:
        by_family.setdefault(p.get("family", "?"), []).append(p)
    out: list[str] = []
    out.append(
        f"_Packets are rolled-up findings: each one anchors to a "
        f"specific entity / topic and cites the supporting atoms. "
        f"{len(packets)} packets across {len(by_family)} families._\n"
    )
    for family in sorted(by_family):
        ps = by_family[family]
        cited_count = sum(1 for p in ps if p.get("id") in brain_cited_packets)
        out.append(f"\n### `{family}` — {len(ps)} packet(s), {cited_count} cited by a brain")
        out.append("\n| packet_id | anchor | conf | governing atoms | brain |")
        out.append("|---|---|---:|---|:-:|")
        for p in ps:
            pid = p.get("id", "")
            cited_flag = "✓" if pid in brain_cited_packets else ""
            gov = ", ".join(f"`{a}`" for a in (p.get("governing_atom_ids") or [])[:3])
            out.append(
                f"| `{pid}` | `{p.get('anchor_key', '')}` "
                f"| {p.get('confidence', '')} | {gov} | {cited_flag} |"
            )
    return "\n".join(out) + "\n"


def _entities_edges_md(envelope: dict) -> str:
    entities = envelope.get("entities") or []
    edges = envelope.get("edges") or []
    out: list[str] = []
    out.append(
        f"_Entity normalization deduplicates atoms that refer to the "
        f"same real-world thing across multiple source files. Edges "
        f"are the relationships parser-os inferred between atoms._\n"
    )
    out.append(f"\n## Entities ({len(entities)})\n")
    if entities:
        out.append("| canonical_key | name | type | aliases | source atoms | artifacts |")
        out.append("|---|---|---|---|---:|---|")
        for e in entities[:80]:
            aliases = ", ".join((e.get("aliases") or [])[:5])
            arts = ", ".join(f"`{a}`" for a in (e.get("artifact_ids") or [])[:4])
            out.append(
                f"| `{e.get('canonical_key', '')}` | {e.get('canonical_name', '')} "
                f"| {e.get('entity_type', '')} | {aliases} "
                f"| {len(e.get('source_atom_ids') or [])} | {arts} |"
            )
        if len(entities) > 80:
            out.append(f"\n_… {len(entities) - 80} more entities omitted; full list in envelope.json._\n")
    out.append(f"\n## Edges ({len(edges)})\n")
    if edges:
        from collections import Counter

        by_type = Counter(e.get("edge_type", "?") for e in edges)
        out.append("Edge type distribution:\n")
        out.append("| edge_type | count |")
        out.append("|---|---:|")
        for et, n in by_type.most_common():
            out.append(f"| `{et}` | {n} |")
        out.append("\n_Showing first 60 edges:_\n")
        out.append("| edge_type | from_atom | to_atom | conf | reason |")
        out.append("|---|---|---|---:|---|")
        for e in edges[:60]:
            out.append(
                f"| `{e.get('edge_type', '')}` "
                f"| `{e.get('from_atom_id', '')}` | `{e.get('to_atom_id', '')}` "
                f"| {e.get('confidence', '')} | {_truncate(e.get('reason'), 100)} |"
            )
        if len(edges) > 60:
            out.append(f"\n_… {len(edges) - 60} more edges omitted; full list in envelope.json._\n")
    return "\n".join(out) + "\n"


def _pack_prior_md(pp: dict) -> str:
    if not pp:
        return "_No pack-prior state._\n"
    out: list[str] = []
    out.append(
        f"_Pack prior is the deterministic keyword-density router that "
        f"picks which OrbitBrief domain pack(s) the engagement matches. "
        f"It runs BEFORE any LLM call._\n"
    )
    out.append(f"\n**Top pick:** `{pp.get('top_pack_id')}` (confidence {pp.get('top_confidence')})\n")
    out.append(f"**Runner-up:** `{pp.get('runner_up_pack_id')}` (confidence {pp.get('runner_up_confidence')})\n")
    out.append(f"**Margin:** {pp.get('margin')}  ·  **Tokens scored:** {pp.get('tokens_considered')}  ·  **LLM consulted:** {pp.get('escalated')}\n")
    out.append("\n## Top scores\n\n| pack | raw score | confidence | matched keywords |")
    out.append("|---|---:|---:|---|")
    for s in (pp.get("scores") or [])[:8]:
        kws = ", ".join(f"`{k}`" for k in (s.get("matched_keywords") or [])[:6])
        out.append(
            f"| `{s.get('pack_id')}` | {s.get('raw_score')} "
            f"| {s.get('confidence')} | {kws} |"
        )
    return "\n".join(out) + "\n"


def _site_reality_md(sr: dict) -> str:
    if not sr:
        return "_No site-reality state._\n"
    clusters = sr.get("clusters") or []
    out: list[str] = []
    out.append(
        f"_Site reality clusters atoms by physical-site identity using "
        f"a graph walk over the entity + edge structure. {len(clusters)} "
        f"cluster(s), {sr.get('merged_keys', 0)} key(s) merged._\n"
    )
    if clusters:
        out.append("\n| cluster_id | canonical_name | site_keys | member_atoms | artifacts | LLM-resolved |")
        out.append("|---|---|---|---:|---|:-:|")
        for c in clusters:
            out.append(
                f"| `{c.get('cluster_id')}` | {c.get('canonical_name')} "
                f"| `{', '.join(c.get('site_keys') or [])}` "
                f"| {len(c.get('member_atom_ids') or [])} "
                f"| `{', '.join(c.get('artifact_ids') or [])}` "
                f"| {'✓' if c.get('name_resolved_by_llm') else ''} |"
            )
    return "\n".join(out) + "\n"


def _brain_output_md(state: dict, pack_id: str) -> str:
    """Markdown render of one brain's typed output."""
    out: list[str] = []
    out.append(f"# Brain output: `{pack_id}`\n")
    out.append(f"**model_used:** `{state.get('model_used') or '?'}`  ·  ")
    out.append(f"**fallback_used:** {state.get('fallback_used', False)}  ·  ")
    cost = state.get("token_cost") or {}
    out.append(
        f"**token_cost:** prompt={cost.get('prompt_tokens', 0)} / "
        f"completion={cost.get('completion_tokens', 0)} / "
        f"total={cost.get('total_tokens', 0)}\n"
    )
    if state.get("unresolved_packet_ids"):
        out.append(
            f"\n**unresolved_packet_ids:** "
            f"{', '.join(f'`{p}`' for p in state['unresolved_packet_ids'])}\n"
        )

    section_keys = [
        # Briefing brain (9-section)
        "scope_overview",
        "detailed_scope_of_services",
        "deliverables",
        "assumptions",
        "customer_responsibilities",
        "out_of_scope",
        "risks_or_dependencies",
        "completion_criteria",
        "open_items",
        # Managed-services brain (7-section)
        "scope_items",
        "exclusions",
        "milestones",
        "dispatch_readiness_flags",
        "open_questions",
    ]
    for sec in section_keys:
        items = state.get(sec) or []
        if not items:
            continue
        out.append(f"\n## `{sec}` ({len(items)} item(s))\n")
        for it in items:
            md_meta = ""
            md_extras: list[str] = []
            for k in (
                "category", "rationale", "deadline_relative", "target_relative",
                "addressee", "severity", "status", "blocker_owner", "risk_if_false",
            ):
                v = it.get(k)
                if v not in (None, "", []):
                    md_extras.append(f"_{k}_={v}")
            if md_extras:
                md_meta = " · " + " · ".join(md_extras)
            out.append(f"\n### `{it.get('id')}`{md_meta}\n")
            out.append(f"> {it.get('statement', '')}\n")
            pkts = ", ".join(f"`{p}`" for p in (it.get("supporting_packet_ids") or []))
            atoms = ", ".join(f"`{a}`" for a in (it.get("supporting_atom_ids") or []))
            out.append(f"\n* **Supporting packets:** {pkts or '_none_'}")
            out.append(f"* **Supporting atoms:** {atoms or '_none_'}")
            out.append(f"* **Confidence:** {it.get('confidence')}")
    return "\n".join(out) + "\n"


def _retrieval_bundle_md(bundle: dict, pack_id: str) -> str:
    """Markdown render of one retrieval bundle."""
    fams = bundle.get("packets_by_family") or {}
    out: list[str] = []
    out.append(f"# Retrieval bundle: `{pack_id}`\n")
    out.append(
        f"_What the orchestrator pre-bundled and gave to the {pack_id} brain. "
        f"Filtered by per-pack keyword density so the brain only sees packets "
        f"relevant to its domain._\n"
    )
    total = sum(len(v or []) for v in fams.values())
    out.append(f"\n**{total} packet(s) across {len(fams)} family/families.**\n")
    for family in sorted(fams):
        out.append(f"\n## `{family}` ({len(fams[family])} packet(s))\n")
        out.append("\n| packet_id | anchor | conf | governing atoms | sample atom text |")
        out.append("|---|---|---:|---|---|")
        for p in fams[family]:
            atom_text = p.get("atom_text") or {}
            sample = next(iter(atom_text.values()), "") if atom_text else ""
            sample = _truncate(sample, 160).replace("|", "\\|")
            gov = ", ".join(f"`{a}`" for a in (p.get("governing_atom_ids") or [])[:3])
            out.append(
                f"| `{p.get('packet_id')}` | `{p.get('anchor_key', '')}` "
                f"| {p.get('confidence')} | {gov} | {sample} |"
            )
    return "\n".join(out) + "\n"


def _raw_vs_extracted_md(envelope: dict, raw_dir: Path, source_dir: Path | None,
                         brain_cited_atoms: set[str], in_brief_atoms: set[str]) -> str:
    """The killer view: per artifact, raw preview LEFT, extracted atoms RIGHT."""
    docs = envelope.get("documents") or []
    if not docs:
        return "_No source documents._\n"

    atoms_by_artifact: dict[str, list[dict]] = {}
    for a in (envelope.get("atoms") or []):
        atoms_by_artifact.setdefault(a.get("artifact_id", ""), []).append(a)

    out: list[str] = []
    out.append(
        "_For each source artifact, the raw extracted text preview is on top "
        "and the atoms parser-os pulled from it are below. Compare the two to "
        "see what was captured, what was missed, and what context is lost in "
        "the atom-level breakdown._\n\n"
    )

    for doc in docs:
        aid = doc.get("artifact_id", "")
        atoms = atoms_by_artifact.get(aid, [])
        out.append(f"---\n\n## `{doc.get('filename')}`\n")
        out.append(
            f"**artifact_id:** `{aid}`  ·  **type:** `{doc.get('artifact_type')}`  ·  "
            f"**parser:** `{doc.get('parser_name')}/{doc.get('parser_version')}`  ·  "
            f"**size:** {doc.get('size_bytes', 0):,} bytes  ·  "
            f"**sha256:** `{(doc.get('sha256') or '')[:16]}…`\n"
        )
        out.append(f"**atoms extracted:** {len(atoms)}  ·  ")
        cited = sum(1 for a in atoms if a.get("id") in brain_cited_atoms)
        in_brief = sum(1 for a in atoms if a.get("id") in in_brief_atoms)
        out.append(
            f"**cited by a brain:** {cited} ({_pct(cited, len(atoms))})  ·  "
            f"**in final brief:** {in_brief} ({_pct(in_brief, len(atoms))})\n"
        )

        # Raw preview from structured projection (parser-os already extracted text).
        structured = doc.get("structured") or {}
        preview = _structured_preview(structured)
        if preview:
            out.append(f"\n### Raw extracted text preview\n\n```\n{preview}\n```\n")
        elif source_dir and (source_dir / doc.get("filename", "")).is_file():
            out.append(
                f"\n_Raw file preserved verbatim at_ "
                f"`raw/{doc.get('filename')}` _(binary; open externally)._\n"
            )
        else:
            out.append("\n_No text preview available._\n")

        # Extracted atoms from this artifact, top 30 by importance (in_brief > brain > all).
        if atoms:
            out.append(f"\n### Atoms extracted from this artifact\n")
            ranked = sorted(
                atoms,
                key=lambda a: (
                    0 if a.get("id") in in_brief_atoms else (
                        1 if a.get("id") in brain_cited_atoms else 2
                    ),
                    -float(a.get("confidence") or 0),
                ),
            )
            shown = 30
            out.append("\n| atom_id | type | conf | locator | text | brain | brief |")
            out.append("|---|---|---:|---|---|:-:|:-:|")
            for a in ranked[:shown]:
                loc = a.get("locator") or {}
                loc_str = " ".join(f"{k}={v}" for k, v in loc.items() if v not in (None, ""))
                text = _truncate(a.get("text"), 180).replace("|", "\\|")
                aid_a = a.get("id", "")
                bf = "✓" if aid_a in brain_cited_atoms else ""
                bf2 = "✓" if aid_a in in_brief_atoms else ""
                out.append(
                    f"| `{aid_a}` | {a.get('atom_type', '')} | {a.get('confidence', '')} "
                    f"| `{loc_str}` | {text} | {bf} | {bf2} |"
                )
            if len(atoms) > shown:
                out.append(
                    f"\n_… {len(atoms) - shown} more atoms from this artifact "
                    f"(see `extraction/atoms.md` for the full list)._\n"
                )
        out.append("")

    return "\n".join(out) + "\n"


def _structured_preview(structured: dict, max_chars: int = 3500) -> str:
    """Best-effort text preview from a parser-os structured projection."""
    if not isinstance(structured, dict):
        return ""
    chunks: list[str] = []
    pages = structured.get("pages")
    if isinstance(pages, list):
        for page in pages[:6]:
            if not isinstance(page, dict):
                continue
            pno = page.get("page_number") or page.get("page")
            blocks = page.get("text_blocks") or page.get("blocks") or []
            for b in blocks[:8]:
                if isinstance(b, dict):
                    txt = b.get("text") or b.get("content") or ""
                else:
                    txt = str(b)
                if txt:
                    chunks.append(f"[p{pno}] {txt}")
    sheets = structured.get("sheets")
    if isinstance(sheets, list):
        for sh in sheets[:6]:
            if not isinstance(sh, dict):
                continue
            name = sh.get("name") or sh.get("sheet_name") or "?"
            rows = sh.get("rows") or sh.get("data") or []
            chunks.append(f"[sheet: {name}] ({len(rows)} rows)")
            for row in rows[:6]:
                if isinstance(row, dict):
                    chunks.append("  " + " | ".join(str(v)[:60] for v in row.values()))
                elif isinstance(row, list):
                    chunks.append("  " + " | ".join(str(v)[:60] for v in row))
    for k in ("text", "body", "content", "raw_text", "extracted_text"):
        if isinstance(structured.get(k), str):
            chunks.append(structured[k])
    out = "\n".join(chunks)
    return out[:max_chars] + ("…" if len(out) > max_chars else "")


def _llm_review_prompt(case_id: str, summary: dict[str, Any]) -> str:
    return f"""# LLM review prompt — case `{case_id}`

You are an expert PM reviewer for OrbitBrief, a system that turns
professional-services intake (RFPs, transcripts, spreadsheets) into a
reviewable scope brief. I'm giving you ONE engagement case so you can
analyze how the system performed end-to-end.

## What I want from you

Read the files in this folder in roughly this order:

1. `README.md` — orientation
2. `lineage/raw_vs_extracted.md` — for each source artifact, the raw
   extracted text preview is shown next to the atoms parser-os pulled
   out of it. Skim this first to get a feel for what was captured.
3. `extraction/packets.md` — packets are rolled-up findings; check
   what families parser-os emitted.
4. `synthesis/pack_prior.md` — which OrbitBrief domain pack the
   engagement was routed to.
5. `synthesis/brain_outputs/<pack_id>.md` — what the brain wrote for
   each active pack.
6. `brief.md` — the final composed brief a PM would review.

## Then write a structured review covering

### A. Coverage gaps
What did the brain miss that the raw artifacts clearly contained?
Pick 3–5 specific atoms from `lineage/raw_vs_extracted.md` that
should have made it to the brief but didn't.

### B. False positives
What did the brain include that the raw artifacts don't actually
support? Cite the brain item id from `synthesis/brain_outputs/`.

### C. Pack routing
Was `{summary.get('pack_prior_top') or '?'}` the right pack? What's
your reasoning? If multiple packs should have run, which ones?

### D. Brain output quality
For each brain that ran, score 1-10 on:
* Accuracy (claims match the source)
* Specificity (uses real SKUs/quantities/standards vs generic boilerplate)
* Completeness (covers all the sections that have evidence)
* PM-readiness (would a senior PM publish this with light edits?)

### E. Top 3 prompt fixes
What would you tell the brain prompt designer to add/remove/change
to fix the biggest issues you found?

### F. Top 3 parser-os fixes
Same question for the parser-os extraction step.

## Reference: this case's stats

* {summary.get('source_artifact_count', 0)} source files
* {summary.get('atom_count', 0):,} atoms extracted
* {summary.get('packet_count', 0):,} packets certified
* Active packs: {", ".join(f"`{p}`" for p in summary.get('active_packs') or [])}
* Brains run: {", ".join(f"`{b}`" for b in summary.get('brains_run') or []) or "_none (substrate-only sweep)_"}
* Brain fallbacks: {", ".join(f"`{b}`" for b in summary.get('brain_fallbacks') or []) or "_none_"}
* Composed brief items: {summary.get('composed_items', 0)}
* Items queued for review: {summary.get('queued_for_review', 0)}

Be specific, blunt, and operator-focused. The point of this review is
to find systematic issues, not to be polite.
"""


# ────────────────────────────── per-case generation ────────────────────


def build_case_bundle(
    case_id: str,
    case_results_dir: Path,
    case_source_dir: Path | None,
    out_root: Path,
) -> dict[str, Any]:
    """Generate the per-case handoff folder. Returns a quick summary dict."""
    target = out_root / case_id
    if target.exists():
        shutil.rmtree(target)
    (target / "raw").mkdir(parents=True)
    (target / "extraction").mkdir()
    (target / "synthesis" / "retrieval_bundles").mkdir(parents=True)
    (target / "synthesis" / "brain_outputs").mkdir()
    (target / "lineage").mkdir()

    envelope = _safe_load(case_results_dir / "00_envelope.json") or {}
    pack_prior = _safe_load(case_results_dir / "10_pack_prior_state.json") or {}
    site_reality = _safe_load(case_results_dir / "11_site_reality_state.json") or {}
    insp = _safe_load(case_results_dir / "90_inspection_report.json") or {}
    funnel = insp.get("funnel") or {}
    composed_summary = insp.get("composed_brief_summary") or {}
    pipeline_log = _safe_load(case_results_dir / "pipeline_log.json") or []
    manifest = _safe_load(case_results_dir / "manifest.json") or {}

    # Downstream-survival sets for atoms.
    brain_cited_atoms: set[str] = set()
    in_brief_atoms: set[str] = set()
    brain_cited_packets: set[str] = set()
    in_brief_packets: set[str] = set()
    for atom in (insp.get("atom_lineage") or []):
        downstream = atom.get("downstream") or {}
        if downstream.get("cited_by_brain"):
            brain_cited_atoms.add(atom.get("id"))
        if downstream.get("in_composed_brief"):
            in_brief_atoms.add(atom.get("id"))
    for p in (insp.get("packets") or []):
        downstream = p.get("downstream") or {}
        if downstream.get("cited_by_brain"):
            brain_cited_packets.add(p.get("id"))
        if downstream.get("in_composed_brief"):
            in_brief_packets.add(p.get("id"))

    # Copy raw source files (cap individual file size for the bundle).
    if case_source_dir is not None and case_source_dir.is_dir():
        for src_file in case_source_dir.iterdir():
            if not src_file.is_file():
                continue
            try:
                shutil.copy2(src_file, target / "raw" / src_file.name)
            except OSError:
                # Last-resort: skip if file can't be copied.
                pass

    # Per-case summary used in README + LLM prompt.
    runtime_ms = sum(int(r.get("duration_ms") or 0) for r in pipeline_log)
    fallbacks = sorted(
        r.get("stage", "").split("::", 1)[1]
        for r in pipeline_log
        if r.get("status") == "fallback" and r.get("stage", "").startswith("40_brain::")
    )
    summary = {
        "source_artifact_count": funnel.get("source_artifacts", 0),
        "atom_count": funnel.get("atoms_extracted", 0),
        "entity_count": funnel.get("entities_normalized", 0),
        "edge_count": funnel.get("edges_built", 0),
        "packet_count": funnel.get("packets_certified", 0),
        "active_packs": list(funnel.get("active_packs") or []),
        "brains_run": list((funnel.get("brain_items_per_pack") or {}).keys()),
        "brain_fallbacks": fallbacks,
        "pack_prior_top": pack_prior.get("top_pack_id"),
        "composed_items": funnel.get("composed_brief_items", 0),
        "queued_for_review": manifest.get("queued_for_review", 0),
        "total_runtime_seconds": runtime_ms / 1000.0,
    }

    # Write content.
    (target / "README.md").write_text(_per_case_readme(case_id, target, summary), encoding="utf-8")
    (target / "extraction" / "atoms.md").write_text(
        f"# Atoms — {case_id}\n\n" + _atoms_table(envelope, brain_cited_atoms, in_brief_atoms),
        encoding="utf-8",
    )
    (target / "extraction" / "packets.md").write_text(
        f"# Packets — {case_id}\n\n" + _packets_table(envelope, brain_cited_packets),
        encoding="utf-8",
    )
    (target / "extraction" / "entities_and_edges.md").write_text(
        f"# Entities + edges — {case_id}\n\n" + _entities_edges_md(envelope),
        encoding="utf-8",
    )
    (target / "synthesis" / "pack_prior.md").write_text(
        f"# Pack prior — {case_id}\n\n" + _pack_prior_md(pack_prior),
        encoding="utf-8",
    )
    (target / "synthesis" / "site_reality.md").write_text(
        f"# Site reality — {case_id}\n\n" + _site_reality_md(site_reality),
        encoding="utf-8",
    )

    # Retrieval bundles per pack.
    bundle_dir = case_results_dir / "20_retrieval_bundles"
    if bundle_dir.is_dir():
        for f in sorted(bundle_dir.glob("*.json")):
            bundle = _safe_load(f) or {}
            (target / "synthesis" / "retrieval_bundles" / f"{f.stem}.md").write_text(
                _retrieval_bundle_md(bundle, f.stem), encoding="utf-8"
            )
            shutil.copy2(f, target / "synthesis" / "retrieval_bundles" / f.name)

    # Brain outputs per pack.
    brain_dir = case_results_dir / "40_brain_outputs"
    if brain_dir.is_dir():
        for f in sorted(brain_dir.glob("*.json")):
            state = _safe_load(f) or {}
            (target / "synthesis" / "brain_outputs" / f"{f.stem}.md").write_text(
                _brain_output_md(state, f.stem), encoding="utf-8"
            )
            shutil.copy2(f, target / "synthesis" / "brain_outputs" / f.name)

    # Final brief markdown.
    md_brief = case_results_dir / "81_composed_brief.md"
    if md_brief.is_file():
        shutil.copy2(md_brief, target / "brief.md")

    # Lineage trio.
    (target / "lineage" / "raw_vs_extracted.md").write_text(
        f"# Raw vs extracted — {case_id}\n\n"
        + _raw_vs_extracted_md(
            envelope,
            target / "raw",
            case_source_dir,
            brain_cited_atoms,
            in_brief_atoms,
        ),
        encoding="utf-8",
    )
    insp_html = case_results_dir / "91_inspection_report.html"
    if insp_html.is_file():
        shutil.copy2(insp_html, target / "lineage" / "inspection_report.html")
    insp_json = case_results_dir / "90_inspection_report.json"
    if insp_json.is_file():
        shutil.copy2(insp_json, target / "inspection_report.json")
    pipeline_log_path = case_results_dir / "pipeline_log.json"
    if pipeline_log_path.is_file():
        shutil.copy2(pipeline_log_path, target / "pipeline_log.json")
    manifest_path = case_results_dir / "manifest.json"
    if manifest_path.is_file():
        shutil.copy2(manifest_path, target / "manifest.json")

    # The LLM-ready review prompt.
    (target / "LLM_REVIEW_PROMPT.md").write_text(
        _llm_review_prompt(case_id, summary), encoding="utf-8"
    )

    return summary


# ────────────────────────────── corpus-level files ─────────────────────


def _corpus_readme(case_count: int, run_at: str) -> str:
    return f"""# OrbitBrief corpus handoff bundle

Generated: {run_at}
Cases: {case_count}

This bundle pairs the **raw source artifacts** of every engagement
case with what OrbitBrief did to them — extracted atoms, certified
packets, normalized entities + edges, pack-routing decision, brain
outputs, and the final reviewable brief — packaged so any LLM
(ChatGPT, Claude, Gemini) or human reviewer can read it cold and
reason about the system's quality.

## How to use this bundle

### Quickest LLM review
Open `MASTER_LLM_REVIEW_PROMPT.md` and paste it into a frontier-model
chat (GPT-5 / Claude Opus / Gemini Ultra). Then attach one case
folder. The LLM will produce a structured review covering coverage
gaps, false positives, pack routing, brain quality, and prompt fixes.

### Per-case deep dive
1. Open `cases/<CASE_ID>/README.md` for orientation.
2. Open `cases/<CASE_ID>/lineage/raw_vs_extracted.md` for the killer
   side-by-side view: raw artifact preview ↔ extracted atoms with
   downstream-survival flags.
3. Open `cases/<CASE_ID>/brief.md` for the PM-readable composed brief.
4. Open `cases/<CASE_ID>/lineage/inspection_report.html` in a browser
   for the full single-page lineage view (works offline).

### Cross-case dashboard
Open `corpus_dashboard.html` for the cross-case scoreboard:
KPIs, pack-routing distribution, brain health, stage-timing aggregates,
top "interesting" findings, per-case scoreboard with drill-downs.

## What's in each case folder

```
cases/<CASE_ID>/
├── README.md                              orientation + per-case stats
├── LLM_REVIEW_PROMPT.md                   pre-baked prompt for LLM analysis
├── raw/                                   original source artifacts (verbatim)
├── extraction/
│   ├── atoms.md                           every atom in markdown table form
│   ├── packets.md                         packets grouped by family
│   └── entities_and_edges.md              the GNN structure
├── synthesis/
│   ├── pack_prior.md                      domain routing decision
│   ├── site_reality.md                    physical-site clusters
│   ├── retrieval_bundles/<pack>.{{md,json}}  what each brain saw
│   └── brain_outputs/<pack>.{{md,json}}     what each brain wrote
├── brief.md                               final PM-readable brief
├── lineage/
│   ├── raw_vs_extracted.md                source ↔ atoms side-by-side
│   └── inspection_report.html             full single-page lineage view
├── inspection_report.json                 lineage data (programmatic)
├── pipeline_log.json                      per-stage StageRecord
└── manifest.json                          run summary
```

## Source

Bundle generator: `tools/build_handoff_bundle.py` in the
`Purtera-IT/Orbitbrief-Core` repo. Re-run any time the corpus or
pipeline changes:

```bash
python tools/build_handoff_bundle.py \\
    --corpus /tmp/orbitbrief_corpus_results \\
    --source /Users/purtera/dev/purtera/testing/managed_services_sow_artifact_pack \\
    --out ~/Desktop/orbitbrief_corpus_handoff_<date>
```
"""


def _corpus_overview_md(corpus_report: dict[str, Any]) -> str:
    cases = corpus_report.get("cases") or []
    agg = corpus_report.get("aggregates") or {}
    out: list[str] = []
    out.append(f"# Corpus overview\n")
    out.append(f"\n**{agg.get('total_cases', 0)} case(s)** · ")
    out.append(f"{agg.get('total_atoms_processed', 0):,} total atoms · ")
    out.append(f"{agg.get('total_composed_items', 0)} brief items · ")
    out.append(f"{agg.get('total_queued_for_review', 0)} items queued for review · ")
    out.append(f"{agg.get('total_runtime_seconds', 0)}s total runtime\n")

    # Pack distribution.
    out.append("\n## Pack-routing distribution\n")
    out.append("\n| pack | active_in_cases | top_pick_in_cases |")
    out.append("|---|---:|---:|")
    pack_app = agg.get("pack_appearance") or {}
    pack_top = agg.get("pack_top_count") or {}
    for pack in sorted(set(pack_app) | set(pack_top), key=lambda p: -pack_app.get(p, 0)):
        out.append(f"| `{pack}` | {pack_app.get(pack, 0)} | {pack_top.get(pack, 0)} |")

    # Per-case scoreboard.
    out.append("\n## Per-case scoreboard\n")
    out.append("\n| case | files | atoms | packets | top pack | brains | items | status |")
    out.append("|---|---:|---:|---:|---|---|---:|---|")
    for c in cases:
        bf = c.get("brain_fallbacks") or []
        status = "FALLBACK" if bf else ("OK" if c.get("brains_run") else "substrate-only")
        out.append(
            f"| [`{c.get('case_id')}`](cases/{c.get('case_id')}/README.md) "
            f"| {c.get('source_artifact_count')} "
            f"| {c.get('atom_count')} "
            f"| {c.get('packet_count')} "
            f"| `{c.get('pack_prior_top') or '-'}` "
            f"| `{', '.join(c.get('brains_run') or []) or '-'}` "
            f"| {c.get('composed_items')} "
            f"| **{status}** |"
        )
    return "\n".join(out) + "\n"


def _master_llm_prompt(case_count: int) -> str:
    return f"""# Master LLM review prompt — OrbitBrief corpus

You are an expert PM-side QA reviewer for OrbitBrief, a system that
turns professional-services intake into a reviewable scope brief.

I'm giving you a corpus of {case_count} engagement cases. Each one is
a self-contained folder under `cases/<CASE_ID>/` with the original
raw artifacts paired with everything OrbitBrief did to them.

## What I want

Read the files in this order:

1. `corpus_overview.md` — quick stats + per-case scoreboard.
2. Then for the **3 cases you find most interesting** (biggest, most
   complex routing, fallback hotspots, etc.):
   * `cases/<CASE_ID>/README.md`
   * `cases/<CASE_ID>/lineage/raw_vs_extracted.md`
   * `cases/<CASE_ID>/brief.md`
   * `cases/<CASE_ID>/synthesis/brain_outputs/<pack>.md`

## Then produce a structured corpus-level review

### A. System strengths
What is OrbitBrief consistently good at across the corpus?
Cite specific cases.

### B. Systematic failure modes
What patterns of failure do you see across multiple cases?
For each pattern, cite 2-3 cases that exhibit it.

### C. Pack-routing quality
Look at the pack distribution in `corpus_overview.md`. Did the right
packs route to the right cases? Where is `pack_prior` mis-routing?

### D. Brain quality assessment
For each brain that appears in multiple cases, score 1-10 on:
* Accuracy
* Specificity (real SKUs/quantities/standards vs boilerplate)
* PM-readiness

### E. Top 5 prompt-engineering fixes
Specific, actionable changes to the brain prompts that would have the
biggest impact across the corpus.

### F. Top 5 parser-os extraction fixes
Same question for the parser-os extraction layer.

### G. The "next 3 things to test"
Given everything you've seen, what 3 concrete experiments should the
team run next to push the system from MVP-grade to production-grade?

Be specific, blunt, and operator-focused. The point of this review is
to find systematic issues, not to be polite.

## File-name reference

Every case folder has the same structure:

```
cases/<CASE_ID>/
├── README.md                              orientation + per-case stats
├── LLM_REVIEW_PROMPT.md                   per-case version of this prompt
├── raw/                                   original source artifacts
├── extraction/{{atoms,packets,entities_and_edges}}.md
├── synthesis/{{pack_prior,site_reality}}.md
├── synthesis/retrieval_bundles/<pack>.md
├── synthesis/brain_outputs/<pack>.md
├── brief.md
├── lineage/{{raw_vs_extracted,inspection_report}}.{{md,html}}
├── inspection_report.json
├── pipeline_log.json
└── manifest.json
```
"""


# ────────────────────────────── main ───────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="build_handoff_bundle.py")
    p.add_argument(
        "--corpus",
        required=True,
        help="Corpus results directory (output of compile_corpus.py)",
    )
    p.add_argument(
        "--source",
        required=True,
        help="Original case source directory (each subdir = one case's raw artifacts)",
    )
    p.add_argument("--out", required=True, help="Output bundle directory (will be created)")
    p.add_argument("--zip", action="store_true", default=True, help="Also create a .zip alongside")
    p.add_argument(
        "--cases",
        help="Comma-separated case ids to include (default: all that have manifests)",
    )
    args = p.parse_args(argv)

    corpus_root = Path(args.corpus)
    source_root = Path(args.source)
    out_root = Path(args.out)

    if not corpus_root.is_dir():
        print(f"corpus root not found: {corpus_root}", file=sys.stderr)
        return 1
    if not source_root.is_dir():
        print(f"source root not found: {source_root}", file=sys.stderr)
        return 1

    if out_root.exists():
        shutil.rmtree(out_root)
    (out_root / "cases").mkdir(parents=True)

    # Per-case build.
    wanted: set[str] | None = None
    if args.cases:
        wanted = {c.strip() for c in args.cases.split(",") if c.strip()}

    case_summaries: dict[str, dict[str, Any]] = {}
    for case_dir in sorted(corpus_root.iterdir()):
        if not case_dir.is_dir():
            continue
        if not (case_dir / "manifest.json").is_file():
            continue
        case_id = case_dir.name
        if wanted and case_id not in wanted:
            continue
        source_dir = source_root / case_id
        print(f"  building case: {case_id}", file=sys.stderr)
        summary = build_case_bundle(
            case_id, case_dir, source_dir if source_dir.is_dir() else None, out_root / "cases"
        )
        case_summaries[case_id] = summary

    if not case_summaries:
        print("no cases were built; check --corpus and --cases", file=sys.stderr)
        return 1

    # Top-level files.
    run_at = _ts()
    (out_root / "README.md").write_text(
        _corpus_readme(len(case_summaries), run_at), encoding="utf-8"
    )
    corpus_report = _safe_load(corpus_root / "corpus_report.json") or {}
    if corpus_report:
        (out_root / "corpus_overview.md").write_text(
            _corpus_overview_md(corpus_report), encoding="utf-8"
        )
        shutil.copy2(corpus_root / "corpus_report.json", out_root / "corpus_report.json")
    if (corpus_root / "corpus_dashboard.html").is_file():
        shutil.copy2(
            corpus_root / "corpus_dashboard.html", out_root / "corpus_dashboard.html"
        )
    (out_root / "MASTER_LLM_REVIEW_PROMPT.md").write_text(
        _master_llm_prompt(len(case_summaries)), encoding="utf-8"
    )
    # Copy the analyst review prompt (versioned in docs/) into the
    # bundle root so reviewers find it next to MASTER_LLM_REVIEW_PROMPT.md.
    analyst_prompt = _REPO_ROOT / "docs" / "ANALYST_REVIEW_PROMPT.md"
    if analyst_prompt.is_file():
        shutil.copy2(analyst_prompt, out_root / "ANALYST_REVIEW_PROMPT.md")

    print(f"\nbundle written: {out_root}", file=sys.stderr)
    print(f"  cases: {len(case_summaries)}", file=sys.stderr)
    print(f"  total size: {_dir_size_human(out_root)}", file=sys.stderr)

    # Zip.
    if args.zip:
        zip_path = out_root.with_suffix(".zip")
        if zip_path.exists():
            zip_path.unlink()
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for f in sorted(out_root.rglob("*")):
                if f.is_file():
                    zf.write(f, f.relative_to(out_root.parent))
        print(f"  zip: {zip_path} ({_human(zip_path.stat().st_size)})", file=sys.stderr)
    return 0


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if isinstance(n, float) else f"{n} {unit}"
        n = n / 1024
    return f"{n:.1f} TB"


def _dir_size_human(d: Path) -> str:
    total = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
    return _human(total)


if __name__ == "__main__":
    raise SystemExit(main())
