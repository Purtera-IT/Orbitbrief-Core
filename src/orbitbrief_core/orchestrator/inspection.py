"""Per-engagement inspection report — full lineage from raw → reviewable brief.

Reads the per-stage artifacts written by :class:`BriefPipeline` and
produces:

* ``90_inspection_report.json`` — a structured snapshot covering:
    - per source artifact: filename, type, sha256, size, atom_ids it
      produced, content preview (the actual extracted text/CSV/MD body
      so reviewers can see what parser-os saw).
    - per atom: id, type, authority, confidence, locator (page/row/cell),
      verified status, **downstream lineage** (which packets cite it,
      which brain items cite it, did it land in the composed brief).
    - per entity: canonical_key + name + which atoms merged into it
      across artifacts (the parser-os entity-normalization signal).
    - per edge: from_atom → to_atom + edge_type + confidence (the GNN
      structure parser-os builds during graph_build).
    - per packet: family + anchor + atom citations + downstream survival
      (made it into the bundle? cited by brain? in composed brief?).
    - **funnel metrics**: counts at each stage so the attrition is visible
      at a glance (atoms ingested → packets formed → bundled → brain-cited
      → in brief).
    - pack_prior verdict + site_reality clusters + brain results summary.
* ``91_inspection_report.html`` — a single-page rendered view of the
  same data with raw artifact previews next to extracted atoms, grouped
  by source file. Designed to be scrolled top-to-bottom by a PM.

This module is the user's "what did the system actually do?" surface.
Everything is reading the existing per-stage JSONs the pipeline wrote
— no new LLM calls, no new substrate touches.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from orbitbrief_core.orchestrator.artifacts import BriefArtifacts


# Cap previews so the HTML stays bounded on giant artifacts.
_PREVIEW_CHARS_PER_ARTIFACT = 4000
_PREVIEW_ROWS_PER_SHEET = 8
_MAX_ATOMS_LISTED_PER_ARTIFACT = 60


def _safe_load_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# ────────────────────────────── builders ───────────────────────────────


def build_inspection_report(artifacts: BriefArtifacts) -> dict[str, Any]:
    """Read every per-stage artifact and produce one comprehensive report dict."""
    envelope = _safe_load_json(artifacts.envelope_path) or {}
    pack_prior = _safe_load_json(artifacts.pack_prior_path) or {}
    site_reality = _safe_load_json(artifacts.site_reality_path) or {}
    refined_brief = _safe_load_json(artifacts.brief_state_refined_path) or _safe_load_json(
        artifacts.brief_state_raw_path
    ) or {}
    composed = _safe_load_json(artifacts.composed_brief_path) or {}
    pipeline_log = _safe_load_json(artifacts.pipeline_log_path) or []
    manifest = _safe_load_json(artifacts.manifest_path) or {}

    # Per-pack brain outputs + reports.
    brain_outputs: dict[str, dict] = {}
    validations: dict[str, dict] = {}
    calibrations: dict[str, dict] = {}
    bundles: dict[str, dict] = {}
    brain_dir = artifacts.root / "40_brain_outputs"
    if brain_dir.is_dir():
        for f in sorted(brain_dir.glob("*.json")):
            brain_outputs[f.stem] = _safe_load_json(f) or {}
    val_dir = artifacts.root / "50_validations"
    if val_dir.is_dir():
        for f in sorted(val_dir.glob("*.json")):
            validations[f.stem] = _safe_load_json(f) or {}
    cal_dir = artifacts.root / "60_calibrations"
    if cal_dir.is_dir():
        for f in sorted(cal_dir.glob("*.json")):
            calibrations[f.stem] = _safe_load_json(f) or {}
    bundle_dir = artifacts.root / "20_retrieval_bundles"
    if bundle_dir.is_dir():
        for f in sorted(bundle_dir.glob("*.json")):
            bundles[f.stem] = _safe_load_json(f) or {}

    # Review queue + decisions.
    queue_items = _read_jsonl(
        artifacts.review_queue_dir / "review_queue.items.jsonl"
    )
    decisions = _read_jsonl(
        artifacts.review_queue_dir / "review_queue.decisions.jsonl"
    )

    # Lineage indexes (atom_id → downstream usage).
    packet_atoms: dict[str, set[str]] = defaultdict(set)
    atom_packets: dict[str, set[str]] = defaultdict(set)
    for p in envelope.get("packets") or []:
        pid = p.get("id")
        if not pid:
            continue
        for aid in (p.get("governing_atom_ids") or []) + (
            p.get("supporting_atom_ids") or []
        ) + (p.get("contradicting_atom_ids") or []):
            packet_atoms[pid].add(aid)
            atom_packets[aid].add(pid)

    # Bundled packets per pack.
    bundled_packet_ids_by_pack: dict[str, set[str]] = {}
    for pack, b in bundles.items():
        ids: set[str] = set()
        for fam, ps in (b.get("packets_by_family") or {}).items():
            for p in ps or []:
                if p.get("packet_id"):
                    ids.add(p["packet_id"])
        bundled_packet_ids_by_pack[pack] = ids
    all_bundled_packet_ids: set[str] = set().union(
        *bundled_packet_ids_by_pack.values()
    ) if bundled_packet_ids_by_pack else set()

    # Brain-cited packets/atoms.
    brain_cited_packets: dict[str, set[str]] = defaultdict(set)
    brain_cited_atoms: dict[str, set[str]] = defaultdict(set)
    brain_items_per_pack: dict[str, list[dict[str, Any]]] = {}
    for pack, state in brain_outputs.items():
        items: list[dict[str, Any]] = []
        # Briefing brains have 9 sections; managed_services has 7. Just
        # walk every list-of-dicts that looks like grounded items.
        for sec_name, sec_val in (state or {}).items():
            if not isinstance(sec_val, list):
                continue
            for it in sec_val:
                if not isinstance(it, dict):
                    continue
                if "supporting_packet_ids" not in it:
                    continue
                items.append(
                    {
                        "section": sec_name,
                        "id": it.get("id"),
                        "statement": it.get("statement", "")[:240],
                        "confidence": it.get("confidence"),
                        "supporting_packet_ids": list(it.get("supporting_packet_ids") or []),
                        "supporting_atom_ids": list(it.get("supporting_atom_ids") or []),
                    }
                )
                for pid in it.get("supporting_packet_ids") or []:
                    brain_cited_packets[pack].add(pid)
                for aid in it.get("supporting_atom_ids") or []:
                    brain_cited_atoms[pack].add(aid)
        brain_items_per_pack[pack] = items

    all_brain_cited_packets: set[str] = set().union(
        *brain_cited_packets.values()
    ) if brain_cited_packets else set()
    all_brain_cited_atoms: set[str] = set().union(
        *brain_cited_atoms.values()
    ) if brain_cited_atoms else set()

    # Composed-brief packet ids (which made it through to the doc).
    composed_packet_ids: set[str] = set()
    for grp in (composed.get("domains") or []):
        for sec in (grp.get("sections") or []):
            for it in (sec.get("items") or []):
                for pid in it.get("supporting_packet_ids") or []:
                    composed_packet_ids.add(pid)

    # Per-source-artifact view.
    artifacts_view = []
    for doc in envelope.get("documents") or []:
        atom_ids = list(doc.get("atom_ids") or [])
        artifacts_view.append(
            _artifact_view(
                doc=doc,
                atom_ids=atom_ids,
                envelope=envelope,
                atom_packets=atom_packets,
                bundled_packet_ids=all_bundled_packet_ids,
                brain_cited_atoms=all_brain_cited_atoms,
                composed_packet_ids=composed_packet_ids,
            )
        )

    # Per-atom downstream lineage (compact list).
    atom_lineage = []
    for atom in envelope.get("atoms") or []:
        aid = atom.get("id")
        if not aid:
            continue
        used_by_packets = sorted(atom_packets.get(aid, ()))
        bundled = any(pid in all_bundled_packet_ids for pid in used_by_packets)
        brain_cited = aid in all_brain_cited_atoms
        in_brief = any(pid in composed_packet_ids for pid in used_by_packets)
        atom_lineage.append(
            {
                "id": aid,
                "atom_type": atom.get("atom_type"),
                "authority_class": atom.get("authority_class"),
                "confidence": atom.get("confidence"),
                "verified": atom.get("verified"),
                "artifact_id": atom.get("artifact_id"),
                "text": (atom.get("text") or "")[:300],
                "locator": atom.get("locator") or {},
                "downstream": {
                    "packet_ids": used_by_packets,
                    "bundled": bundled,
                    "cited_by_brain": brain_cited,
                    "in_composed_brief": in_brief,
                },
            }
        )

    # Per-entity (cross-artifact reach).
    entity_view = []
    for ent in envelope.get("entities") or []:
        entity_view.append(
            {
                "id": ent.get("id"),
                "canonical_key": ent.get("canonical_key"),
                "canonical_name": ent.get("canonical_name"),
                "entity_type": ent.get("entity_type"),
                "aliases": list(ent.get("aliases") or []),
                "artifact_ids": list(ent.get("artifact_ids") or []),
                "source_atom_ids": list(ent.get("source_atom_ids") or []),
                "review_status": ent.get("review_status"),
                "confidence": ent.get("confidence"),
            }
        )

    # Per-edge (the GNN-shaped structure).
    edges_view = [
        {
            "id": e.get("id"),
            "edge_type": e.get("edge_type"),
            "from_atom_id": e.get("from_atom_id"),
            "to_atom_id": e.get("to_atom_id"),
            "confidence": e.get("confidence"),
            "cross_artifact": e.get("cross_artifact"),
            "reason": e.get("reason"),
        }
        for e in (envelope.get("edges") or [])
    ]

    # Per-packet downstream survival.
    packets_view = []
    for p in envelope.get("packets") or []:
        pid = p.get("id")
        packets_view.append(
            {
                "id": pid,
                "family": p.get("family"),
                "anchor_type": p.get("anchor_type"),
                "anchor_key": p.get("anchor_key"),
                "status": p.get("status"),
                "confidence": p.get("confidence"),
                "governing_atom_ids": list(p.get("governing_atom_ids") or []),
                "supporting_atom_ids": list(p.get("supporting_atom_ids") or []),
                "contradicting_atom_ids": list(p.get("contradicting_atom_ids") or []),
                "downstream": {
                    "bundled": pid in all_bundled_packet_ids,
                    "bundled_to_packs": sorted(
                        pack
                        for pack, ids in bundled_packet_ids_by_pack.items()
                        if pid in ids
                    ),
                    "cited_by_brain": pid in all_brain_cited_packets,
                    "cited_by_packs": sorted(
                        pack
                        for pack, ids in brain_cited_packets.items()
                        if pid in ids
                    ),
                    "in_composed_brief": pid in composed_packet_ids,
                },
            }
        )

    # Funnel — counts at every attrition point.
    n_atoms = len(envelope.get("atoms") or [])
    n_packets = len(envelope.get("packets") or [])
    n_entities = len(envelope.get("entities") or [])
    n_edges = len(envelope.get("edges") or [])
    n_bundled_packets = len(all_bundled_packet_ids)
    n_brain_cited_packets = len(all_brain_cited_packets)
    n_brain_cited_atoms = len(all_brain_cited_atoms)
    n_brain_items = sum(len(v) for v in brain_items_per_pack.values())
    n_composed_items = sum(
        len(s.get("items") or [])
        for g in (composed.get("domains") or [])
        for s in (g.get("sections") or [])
    )

    funnel = {
        "source_artifacts": len(envelope.get("documents") or []),
        "atoms_extracted": n_atoms,
        "entities_normalized": n_entities,
        "edges_built": n_edges,
        "packets_certified": n_packets,
        "active_packs": list((pack_prior or {}).get("scores") and []),  # placeholder
        "bundled_packets_total": n_bundled_packets,
        "bundled_packets_per_pack": {
            k: len(v) for k, v in bundled_packet_ids_by_pack.items()
        },
        "brain_items_per_pack": {k: len(v) for k, v in brain_items_per_pack.items()},
        "brain_cited_packets": n_brain_cited_packets,
        "brain_cited_atoms": n_brain_cited_atoms,
        "composed_brief_items": n_composed_items,
        "atoms_to_brief_pct": (
            round(100 * n_brain_cited_atoms / n_atoms, 1) if n_atoms else 0.0
        ),
        "packets_to_brief_pct": (
            round(100 * n_brain_cited_packets / n_packets, 1) if n_packets else 0.0
        ),
    }
    # Patch active_packs from pack_prior properly.
    funnel["active_packs"] = [
        s.get("pack_id")
        for s in (pack_prior.get("scores") or [])
        if (s.get("confidence") or 0) > 0.05
    ]
    funnel["pack_prior_top"] = pack_prior.get("top_pack_id")
    funnel["pack_prior_margin"] = pack_prior.get("margin")

    # Pack-prior + site-reality summaries.
    pack_prior_summary = {
        "top_pack_id": pack_prior.get("top_pack_id"),
        "top_confidence": pack_prior.get("top_confidence"),
        "runner_up_pack_id": pack_prior.get("runner_up_pack_id"),
        "runner_up_confidence": pack_prior.get("runner_up_confidence"),
        "margin": pack_prior.get("margin"),
        "escalated": pack_prior.get("escalated"),
        "tokens_considered": pack_prior.get("tokens_considered"),
        "selected_pack_ids": pack_prior.get("selected_pack_ids") or [],
        "top_scores": [
            {
                "pack_id": s.get("pack_id"),
                "raw_score": s.get("raw_score"),
                "confidence": round(float(s.get("confidence") or 0.0), 4),
                "matched_keywords": list(s.get("matched_keywords") or [])[:8],
            }
            for s in (pack_prior.get("scores") or [])[:8]
        ],
    }

    site_reality_summary = {
        "cluster_count": site_reality.get("cluster_count"),
        "merged_keys": site_reality.get("merged_keys"),
        "clusters": [
            {
                "cluster_id": c.get("cluster_id"),
                "canonical_name": c.get("canonical_name"),
                "site_keys": list(c.get("site_keys") or []),
                "member_atom_ids": list(c.get("member_atom_ids") or [])[:20],
                "artifact_ids": list(c.get("artifact_ids") or []),
                "name_resolved_by_llm": c.get("name_resolved_by_llm"),
            }
            for c in (site_reality.get("clusters") or [])
        ],
    }

    refined_brief_summary = {
        "model_used": refined_brief.get("model_used"),
        "tier": refined_brief.get("tier"),
        "claim_count": len(refined_brief.get("claims") or []),
        "site_count": len(refined_brief.get("sites") or []),
        "contradictions": len(refined_brief.get("contradictions") or []),
        "review_flags": len(refined_brief.get("review_flags") or []),
        "orchestration": [
            o.get("action") for o in (refined_brief.get("orchestration") or [])
        ],
        "escalation_log": refined_brief.get("escalation_log"),
        "token_cost": refined_brief.get("token_cost"),
    }

    verification_summary = _compute_verification_summary(
        envelope.get("atoms") or (), artifacts_view
    )

    return {
        "project_id": envelope.get("project_id"),
        "compile_id": envelope.get("compile_id"),
        "manifest": manifest,
        "funnel": funnel,
        "pack_prior": pack_prior_summary,
        "site_reality": site_reality_summary,
        "refined_brief": refined_brief_summary,
        "verification": verification_summary,
        "artifacts": artifacts_view,
        "atom_lineage": atom_lineage,
        "entities": entity_view,
        "edges": edges_view,
        "packets": packets_view,
        "bundles": {
            pack: {
                "packet_count": len(ids),
                "packet_ids": sorted(ids),
            }
            for pack, ids in bundled_packet_ids_by_pack.items()
        },
        "brain_items": brain_items_per_pack,
        "validations": {
            pack: {
                "rule_counts": _rule_counts(v),
                "blocker_count": _blocker_count(v),
                "passed_count": _passed_count(v),
                "failed_count": _failed_count(v),
            }
            for pack, v in validations.items()
        },
        "calibrations": {
            pack: _calibration_summary(c)
            for pack, c in calibrations.items()
        },
        "review_queue": {
            "open_count": len([q for q in queue_items if q.get("status") == "open"]),
            "decided_count": len([q for q in queue_items if q.get("status") == "decided"]),
            "decisions_logged": len(decisions),
        },
        "composed_brief_summary": _composed_summary(composed),
        "pipeline_log": pipeline_log,
    }


# ────────────────────────────── per-artifact view ──────────────────────


def _compute_verification_summary(
    atoms: Any, artifacts_view: list[dict[str, Any]]
) -> dict[str, Any]:
    """Aggregate parser-os atom verification status across the corpus.

    Parser-os tags every atom with a ``verified`` field
    (``unverified|failed|verified|partial|unsupported``) that records
    whether the parser could replay the source bytes back to the
    extracted text. ``failed`` atoms are the canary for parser drift —
    the source PDF / XLSX changed in a way the parser couldn't follow.

    The dashboard uses this rollup to surface:

    * Corpus-wide verified/failed/partial/unverified counts.
    * The failure rate as a percentage.
    * The top N artifacts ranked by raw failed-atom count, so a
      reviewer can click straight into the noisy file.
    """
    counts: dict[str, int] = {}
    failed_by_artifact: dict[str, int] = {}
    artifact_meta: dict[str, dict[str, Any]] = {}
    for art in artifacts_view:
        aid = art.get("artifact_id")
        if aid:
            artifact_meta[aid] = {
                "filename": art.get("filename"),
                "artifact_type": art.get("artifact_type"),
                "atom_count": art.get("atom_count", 0),
            }
    total_with_status = 0
    for atom in atoms or ():
        status = (atom.get("verified") or "unverified") or "unverified"
        counts[status] = counts.get(status, 0) + 1
        total_with_status += 1
        if status == "failed":
            art_id = atom.get("artifact_id") or ""
            if art_id:
                failed_by_artifact[art_id] = failed_by_artifact.get(art_id, 0) + 1

    failed = counts.get("failed", 0)
    partial = counts.get("partial", 0)
    verified = counts.get("verified", 0)
    unverified = counts.get("unverified", 0)
    unsupported = counts.get("unsupported", 0)

    def _pct(n: int) -> float:
        return round(100.0 * n / total_with_status, 1) if total_with_status else 0.0

    top_failed = sorted(
        (
            {
                "artifact_id": aid,
                "filename": (artifact_meta.get(aid) or {}).get("filename"),
                "artifact_type": (artifact_meta.get(aid) or {}).get("artifact_type"),
                "failed_atoms": n,
                "atom_count": (artifact_meta.get(aid) or {}).get("atom_count", 0),
            }
            for aid, n in failed_by_artifact.items()
        ),
        key=lambda r: -r["failed_atoms"],
    )[:10]

    return {
        "atom_total": total_with_status,
        "counts": counts,
        "verified_count": verified,
        "failed_count": failed,
        "partial_count": partial,
        "unverified_count": unverified,
        "unsupported_count": unsupported,
        "verified_pct": _pct(verified),
        "failed_pct": _pct(failed),
        "partial_pct": _pct(partial),
        # Health = % of atoms that the parser could fully replay.
        # < 95 % is the "look closely" threshold; < 80 % is the
        # "parser regression suspected" threshold.
        "health_pct": _pct(verified),
        "top_failed_artifacts": top_failed,
    }


def _artifact_view(
    *,
    doc: dict[str, Any],
    atom_ids: list[str],
    envelope: dict[str, Any],
    atom_packets: dict[str, set[str]],
    bundled_packet_ids: set[str],
    brain_cited_atoms: set[str],
    composed_packet_ids: set[str],
) -> dict[str, Any]:
    atoms_by_id = {a["id"]: a for a in (envelope.get("atoms") or ()) if a.get("id")}
    atom_records: list[dict[str, Any]] = []
    used_in_brief = 0
    cited_by_brain = 0
    bundled_atoms = 0
    for aid in atom_ids[:_MAX_ATOMS_LISTED_PER_ARTIFACT]:
        atom = atoms_by_id.get(aid)
        if atom is None:
            continue
        used_by_packets = sorted(atom_packets.get(aid, ()))
        in_bundle = any(p in bundled_packet_ids for p in used_by_packets)
        in_brain = aid in brain_cited_atoms
        in_brief = any(p in composed_packet_ids for p in used_by_packets)
        if in_brief:
            used_in_brief += 1
        if in_brain:
            cited_by_brain += 1
        if in_bundle:
            bundled_atoms += 1
        atom_records.append(
            {
                "id": aid,
                "atom_type": atom.get("atom_type"),
                "authority_class": atom.get("authority_class"),
                "confidence": atom.get("confidence"),
                "verified": atom.get("verified"),
                "text": (atom.get("text") or "")[:280],
                "locator": atom.get("locator") or {},
                "in_bundle": in_bundle,
                "cited_by_brain": in_brain,
                "in_composed_brief": in_brief,
            }
        )

    preview = _content_preview(doc)
    return {
        "artifact_id": doc.get("artifact_id"),
        "filename": doc.get("filename"),
        "artifact_type": doc.get("artifact_type"),
        "sha256": doc.get("sha256"),
        "size_bytes": doc.get("size_bytes"),
        "parser_name": doc.get("parser_name"),
        "parser_version": doc.get("parser_version"),
        "atom_count": len(atom_ids),
        "atoms_listed": len(atom_records),
        "atoms_truncated": max(0, len(atom_ids) - len(atom_records)),
        "atoms_in_bundle": bundled_atoms,
        "atoms_cited_by_brain": cited_by_brain,
        "atoms_in_composed_brief": used_in_brief,
        "preview": preview,
        "atoms": atom_records,
    }


def _content_preview(doc: dict[str, Any]) -> dict[str, Any]:
    """Best-effort preview of what parser-os extracted from this artifact."""
    structured = doc.get("structured") or {}
    artifact_type = (doc.get("artifact_type") or "").lower()
    out: dict[str, Any] = {"kind": "raw_text", "body": ""}

    # Easy: the structured projection already has text-like content.
    candidates = []
    for k in ("text", "body", "content", "raw_text", "extracted_text"):
        if k in structured and isinstance(structured[k], str):
            candidates.append(structured[k])
    # PDF / structured.v1 shapes often have pages with text blocks.
    pages = structured.get("pages")
    if isinstance(pages, list):
        page_chunks: list[str] = []
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
                    page_chunks.append(f"[p{pno}] {txt}")
        if page_chunks:
            candidates.append("\n".join(page_chunks))

    # XLSX / structured projections often list sheets + rows.
    sheets = structured.get("sheets")
    if isinstance(sheets, list):
        sheet_chunks: list[str] = []
        for sh in sheets[:8]:
            if not isinstance(sh, dict):
                continue
            name = sh.get("name") or sh.get("sheet_name") or "?"
            rows = sh.get("rows") or sh.get("data") or []
            sheet_chunks.append(f"  [sheet: {name}] ({len(rows)} rows)")
            for row in rows[:_PREVIEW_ROWS_PER_SHEET]:
                if isinstance(row, dict):
                    sheet_chunks.append(
                        "    " + " | ".join(str(v)[:60] for v in row.values())
                    )
                elif isinstance(row, list):
                    sheet_chunks.append(
                        "    " + " | ".join(str(v)[:60] for v in row)
                    )
        if sheet_chunks:
            out["kind"] = "spreadsheet"
            out["body"] = "\n".join(sheet_chunks)[:_PREVIEW_CHARS_PER_ARTIFACT]
            return out

    # Markdown / TXT — use the first available text candidate.
    if candidates:
        body = max(candidates, key=len)[:_PREVIEW_CHARS_PER_ARTIFACT]
        out["kind"] = "text" if artifact_type in {"txt", "transcript", "email"} else "extracted_text"
        out["body"] = body
        return out

    # Last resort: dump structured as compact JSON snippet.
    if structured:
        out["kind"] = "structured_json"
        out["body"] = json.dumps(structured, indent=2, ensure_ascii=False)[:_PREVIEW_CHARS_PER_ARTIFACT]
    return out


# ────────────────────────────── small helpers ──────────────────────────


def _rule_counts(validation: dict[str, Any]) -> dict[str, int]:
    out: Counter = Counter()
    for iv in validation.get("items") or []:
        for f in iv.get("failures") or []:
            out[f.get("rule_id", "unknown")] += 1
    for f in validation.get("project_failures") or []:
        out[f.get("rule_id", "unknown")] += 1
    return dict(sorted(out.items()))


def _blocker_count(validation: dict[str, Any]) -> int:
    n = 0
    for iv in validation.get("items") or []:
        if any(
            f.get("severity") == "blocker"
            for f in iv.get("failures") or []
        ):
            n += 1
    return n


def _passed_count(validation: dict[str, Any]) -> int:
    n = 0
    for iv in validation.get("items") or []:
        non_info = [
            f for f in iv.get("failures") or [] if f.get("severity") != "info"
        ]
        if not non_info:
            n += 1
    return n


def _failed_count(validation: dict[str, Any]) -> int:
    return len(validation.get("items") or []) - _passed_count(validation)


def _calibration_summary(report: dict[str, Any]) -> dict[str, Any]:
    items = report.get("items") or []
    by_verdict: dict[str, int] = Counter()
    confs: list[float] = []
    for it in items:
        by_verdict[it.get("verdict", "unknown")] += 1
        c = it.get("calibrated_confidence")
        if isinstance(c, (int, float)):
            confs.append(float(c))
    return {
        "by_verdict_counts": dict(sorted(by_verdict.items())),
        "mean_calibrated_confidence": (
            round(sum(confs) / len(confs), 4) if confs else None
        ),
        "min_calibrated_confidence": round(min(confs), 4) if confs else None,
        "max_calibrated_confidence": round(max(confs), 4) if confs else None,
        "item_count": len(items),
    }


def _composed_summary(composed: dict[str, Any]) -> dict[str, Any]:
    return {
        "auto_accept_count": composed.get("auto_accept_count"),
        "review_count": composed.get("review_count"),
        "blocker_count": composed.get("blocker_count"),
        "domain_count": len(composed.get("domains") or []),
        "site_count": len(composed.get("sites") or []),
        "open_question_count": len(composed.get("open_questions") or []),
        "domains": [
            {
                "pack_id": g.get("pack_id"),
                "brain": g.get("brain"),
                "fallback_used": g.get("fallback_used"),
                "section_counts": {
                    s.get("section_id"): len(s.get("items") or [])
                    for s in (g.get("sections") or [])
                },
            }
            for g in (composed.get("domains") or [])
        ],
    }
