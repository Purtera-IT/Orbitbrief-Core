"""Cross-case corpus aggregator — one dashboard view over many engagements.

Reads a *corpus root* (a directory of per-case artifact subdirectories,
each produced by :class:`BriefPipeline`) and aggregates:

* Per-case scoreboard rows: case id, file count, atom/packet counts,
  active packs, brain success rate, runtime, item counts, fallback
  flags. Each row links to the per-case ``91_inspection_report.html``.
* Pack-routing distribution across the corpus: which packs activated
  in how many cases (heatmap material).
* Family distribution: which packet families parser-os emitted
  across the corpus (calibration material for parser-os).
* Brain success-rate aggregates: per-brain OK / fallback / skip counts.
* Stage timing aggregates: median / p95 per stage across cases
  (so operators can spot "the planner is slow on big cases").
* Top "interesting" findings: highest contradiction density,
  highest atom count, multi-domain cases, fallback hotspots.

This module is read-only: it only consumes per-case artifacts that
:class:`BriefPipeline` already wrote. No LLM, no substrate. The
dashboard rendering lives in :mod:`orchestrator.corpus_html`.
"""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _safe_load(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


@dataclass
class CaseScore:
    """Per-case row in the corpus scoreboard."""

    case_id: str
    artifacts_dir: Path
    project_id: str | None = None
    compile_id: str | None = None
    generated_at: str | None = None
    source_artifact_count: int = 0
    atom_count: int = 0
    entity_count: int = 0
    edge_count: int = 0
    packet_count: int = 0
    contradiction_count: int = 0
    pack_prior_top: str | None = None
    pack_prior_margin: float | None = None
    active_packs: tuple[str, ...] = ()
    brains_run: tuple[str, ...] = ()
    brain_fallbacks: tuple[str, ...] = ()
    brain_items: dict[str, int] = field(default_factory=dict)
    composed_items: int = 0
    queued_for_review: int = 0
    auto_accept: int = 0
    blocker_count: int = 0
    atoms_to_brief_pct: float = 0.0
    packets_to_brief_pct: float = 0.0
    stage_status_counts: dict[str, int] = field(default_factory=dict)
    stage_timings_ms: dict[str, int] = field(default_factory=dict)
    total_runtime_ms: int = 0
    has_inspection_report: bool = False
    has_composed_brief: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "artifacts_dir": str(self.artifacts_dir),
            "project_id": self.project_id,
            "compile_id": self.compile_id,
            "generated_at": self.generated_at,
            "source_artifact_count": self.source_artifact_count,
            "atom_count": self.atom_count,
            "entity_count": self.entity_count,
            "edge_count": self.edge_count,
            "packet_count": self.packet_count,
            "contradiction_count": self.contradiction_count,
            "pack_prior_top": self.pack_prior_top,
            "pack_prior_margin": self.pack_prior_margin,
            "active_packs": list(self.active_packs),
            "brains_run": list(self.brains_run),
            "brain_fallbacks": list(self.brain_fallbacks),
            "brain_items": dict(self.brain_items),
            "composed_items": self.composed_items,
            "queued_for_review": self.queued_for_review,
            "auto_accept": self.auto_accept,
            "blocker_count": self.blocker_count,
            "atoms_to_brief_pct": self.atoms_to_brief_pct,
            "packets_to_brief_pct": self.packets_to_brief_pct,
            "stage_status_counts": dict(self.stage_status_counts),
            "stage_timings_ms": dict(self.stage_timings_ms),
            "total_runtime_ms": self.total_runtime_ms,
            "has_inspection_report": self.has_inspection_report,
            "has_composed_brief": self.has_composed_brief,
        }


def load_case_score(case_dir: Path) -> CaseScore | None:
    """Read one case's artifact directory into a :class:`CaseScore`.

    Returns ``None`` if the directory has no manifest (i.e. the
    pipeline never ran for that case).
    """
    case_dir = Path(case_dir)
    manifest = _safe_load(case_dir / "manifest.json")
    if manifest is None:
        return None

    insp = _safe_load(case_dir / "90_inspection_report.json") or {}
    funnel = insp.get("funnel") or {}
    pp = insp.get("pack_prior") or {}
    composed = insp.get("composed_brief_summary") or {}
    log = _safe_load(case_dir / "pipeline_log.json") or []

    case_id = case_dir.name
    if case_id.endswith("_artifacts"):
        case_id = case_id[: -len("_artifacts")]

    stage_status_counts: Counter[str] = Counter()
    stage_timings_ms: dict[str, int] = {}
    total_runtime_ms = 0
    for r in log:
        status = r.get("status") or "unknown"
        stage_status_counts[status] += 1
        ms = int(r.get("duration_ms") or 0)
        stage_timings_ms[r.get("stage", "?")] = ms
        total_runtime_ms += ms

    brain_items_per_pack = dict(funnel.get("brain_items_per_pack") or {})
    brains_run = tuple(sorted(brain_items_per_pack.keys()))

    fallbacks: list[str] = []
    for r in log:
        if r.get("status") == "fallback" and r.get("stage", "").startswith("40_brain::"):
            fallbacks.append(r["stage"].split("::", 1)[1])

    return CaseScore(
        case_id=case_id,
        artifacts_dir=case_dir,
        project_id=manifest.get("envelope_path", "").split("/")[-1].replace(".json", "")
        or insp.get("project_id"),
        compile_id=insp.get("compile_id"),
        generated_at=manifest.get("generated_at"),
        source_artifact_count=int(funnel.get("source_artifacts") or 0),
        atom_count=int(funnel.get("atoms_extracted") or 0),
        entity_count=int(funnel.get("entities_normalized") or 0),
        edge_count=int(funnel.get("edges_built") or 0),
        packet_count=int(funnel.get("packets_certified") or 0),
        contradiction_count=int((insp.get("refined_brief") or {}).get("contradictions") or 0),
        pack_prior_top=pp.get("top_pack_id"),
        pack_prior_margin=pp.get("margin"),
        active_packs=tuple(funnel.get("active_packs") or []),
        brains_run=brains_run,
        brain_fallbacks=tuple(sorted(fallbacks)),
        brain_items=brain_items_per_pack,
        composed_items=int(funnel.get("composed_brief_items") or 0),
        queued_for_review=int(manifest.get("queued_for_review") or 0),
        auto_accept=int(composed.get("auto_accept_count") or 0),
        blocker_count=int(composed.get("blocker_count") or 0),
        atoms_to_brief_pct=float(funnel.get("atoms_to_brief_pct") or 0.0),
        packets_to_brief_pct=float(funnel.get("packets_to_brief_pct") or 0.0),
        stage_status_counts=dict(stage_status_counts),
        stage_timings_ms=stage_timings_ms,
        total_runtime_ms=total_runtime_ms,
        has_inspection_report=(case_dir / "91_inspection_report.html").is_file(),
        has_composed_brief=(case_dir / "81_composed_brief.md").is_file(),
    )


@dataclass
class CorpusReport:
    """Aggregated view across all case rows."""

    corpus_root: Path
    cases: list[CaseScore] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus_root": str(self.corpus_root),
            "case_count": len(self.cases),
            "cases": [c.to_dict() for c in self.cases],
            "aggregates": self.aggregates(),
        }

    # ───── aggregates ─────

    def aggregates(self) -> dict[str, Any]:
        if not self.cases:
            return {}
        cs = self.cases
        atom_totals = [c.atom_count for c in cs]
        runtime_totals = [c.total_runtime_ms for c in cs]

        # Pack distribution.
        pack_appearance: Counter[str] = Counter()
        pack_top: Counter[str] = Counter()
        for c in cs:
            for p in c.active_packs:
                pack_appearance[p] += 1
            if c.pack_prior_top:
                pack_top[c.pack_prior_top] += 1

        # Brain success.
        brain_runs: Counter[str] = Counter()
        brain_fallbacks: Counter[str] = Counter()
        for c in cs:
            for b in c.brains_run:
                brain_runs[b] += 1
            for b in c.brain_fallbacks:
                brain_fallbacks[b] += 1
        brain_health: dict[str, dict[str, Any]] = {}
        for b, total in brain_runs.items():
            fb = brain_fallbacks.get(b, 0)
            brain_health[b] = {
                "total_runs": total,
                "fallback_runs": fb,
                "ok_runs": total - fb,
                "ok_rate_pct": round(100.0 * (total - fb) / total, 1) if total else 0.0,
            }

        # Stage timing aggregates.
        stage_timing_lists: dict[str, list[int]] = defaultdict(list)
        for c in cs:
            for stage, ms in c.stage_timings_ms.items():
                # Normalize stage names like "40_brain::msp" → "40_brain"
                base = stage.split("::", 1)[0]
                stage_timing_lists[base].append(ms)
        stage_timing_summary = {
            stage: {
                "n": len(values),
                "median_ms": int(statistics.median(values)) if values else 0,
                "p95_ms": int(_p95(values)) if values else 0,
                "max_ms": max(values) if values else 0,
            }
            for stage, values in sorted(stage_timing_lists.items())
        }

        # Top "interesting" findings.
        sorted_by_atoms = sorted(cs, key=lambda c: -c.atom_count)
        sorted_by_contradictions = sorted(cs, key=lambda c: -c.contradiction_count)
        multi_domain = [c for c in cs if len(c.brains_run) > 1]
        all_fallbacks = [c for c in cs if c.brain_fallbacks]

        return {
            "total_cases": len(cs),
            "total_atoms_processed": sum(atom_totals),
            "total_runtime_seconds": round(sum(runtime_totals) / 1000, 1),
            "mean_atoms_per_case": int(statistics.mean(atom_totals)) if atom_totals else 0,
            "median_atoms_per_case": int(statistics.median(atom_totals)) if atom_totals else 0,
            "max_atoms_per_case": max(atom_totals) if atom_totals else 0,
            "total_composed_items": sum(c.composed_items for c in cs),
            "total_queued_for_review": sum(c.queued_for_review for c in cs),
            "pack_appearance": dict(pack_appearance.most_common()),
            "pack_top_count": dict(pack_top.most_common()),
            "brain_health": brain_health,
            "stage_timing_summary": stage_timing_summary,
            "top_by_atom_count": [
                {"case_id": c.case_id, "atom_count": c.atom_count} for c in sorted_by_atoms[:5]
            ],
            "top_by_contradictions": [
                {"case_id": c.case_id, "contradiction_count": c.contradiction_count}
                for c in sorted_by_contradictions[:5]
                if c.contradiction_count > 0
            ],
            "multi_domain_cases": [
                {"case_id": c.case_id, "brains_run": list(c.brains_run)}
                for c in multi_domain
            ],
            "fallback_cases": [
                {"case_id": c.case_id, "fallback_brains": list(c.brain_fallbacks)}
                for c in all_fallbacks
            ],
        }


def _p95(values: list[int]) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    idx = int(0.95 * (len(sorted_v) - 1))
    return float(sorted_v[idx])


def build_corpus_report(corpus_root: Path) -> CorpusReport:
    """Walk ``corpus_root`` for per-case artifact dirs and build a :class:`CorpusReport`."""
    corpus_root = Path(corpus_root)
    if not corpus_root.is_dir():
        raise FileNotFoundError(f"corpus root not found: {corpus_root}")
    cases: list[CaseScore] = []
    # Each immediate subdirectory of corpus_root that has a manifest.json
    # is treated as one case. Sorted for deterministic dashboard order.
    for sub in sorted(corpus_root.iterdir()):
        if not sub.is_dir():
            continue
        score = load_case_score(sub)
        if score is not None:
            cases.append(score)
    return CorpusReport(corpus_root=corpus_root, cases=cases)
