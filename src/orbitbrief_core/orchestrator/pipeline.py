"""End-to-end pipeline: ``envelope.json`` → reviewable brief.

Stage map (matches the artifact-directory prefixes):

* **00 ingest** — load and re-emit the canonical envelope.
* **01 evidence_runtime** — ingest into DuckDB-backed runtime.
* **10 pack_prior** — Phase-3 keyword scorer.
* **11 site_reality** — Phase-3 graph clusterer.
* **20 retrieval_bundles** — one bundle per active pack.
* **30 planner** — Phase-4 BriefState (LLM, optional escalation).
* **31 refiner** — Phase-4 graph-consistency cleanup.
* **40 brains** — one brain per active pack (Phase 5).
* **50 validator** — per brain output (Phase 6).
* **60 calibrator** — per brain output (Phase 6).
* **70 review_queue** — needs_review + reject items enqueued.
* **71 training_log** — handed to the orchestrator caller; the
  pipeline does NOT auto-create reviewer decisions.

Every stage logs a :class:`StageRecord`. Final ``pipeline_log.json``
captures the whole audit trail, including timings, fallback usage,
and per-pack outputs.

Without a chat client (no ``--ollama`` / no client passed at
construction) the planner + brain stages SKIP rather than blow up.
That's the path the smoke tests exercise: the pipeline still runs
to completion and writes the substrate artifacts; later runs can
re-attach a real client and resume.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from orbitbrief_core.brains._retrieval_bundle import RetrievalBundle
from orbitbrief_core.calibrator import Calibrator, CalibratorReport
from orbitbrief_core.calibrator.verdict import Verdict
from orbitbrief_core.composer import (
    ComposedBrief,
    Composer,
    ComposerInputs,
    render_markdown,
)
from orbitbrief_core.orchestrator.inspection import build_inspection_report
from orbitbrief_core.orchestrator.inspection_html import render_inspection_html
from orbitbrief_core.evidence_runtime.runtime import EvidenceRuntime
from orbitbrief_core.inference.client import ChatClient
from orbitbrief_core.orchestrator.artifacts import (
    BriefArtifacts,
    StageRecord,
    StageStatus,
)
from orbitbrief_core.orchestrator.brain_registry import (
    BRIEFING_PACK_IDS,
    BrainRegistry,
    default_brain_registry,
)
from orbitbrief_core.orchestrator.bundle_assembler import BundleAssembler
from orbitbrief_core.review_runtime import (
    InMemoryTrainingLog,
    JsonlReviewQueue,
    JsonlTrainingLog,
)
from orbitbrief_core.validator import (
    BrainOutputValidator,
    RuntimeEvidenceLookup,
    ValidationReport,
)
from orbitbrief_core.world_model.pack_prior import PackPrior, PackPriorState
from orbitbrief_core.world_model.registry import (
    DomainPackRegistry,
    load_default_registry,
)
from orbitbrief_core.world_model.planner import (
    BriefState,
    Planner,
    PlannerResult,
)
from orbitbrief_core.world_model.refiner import refine_brief
from orbitbrief_core.world_model.site_reality import (
    SiteRealityEngine,
    SiteRealityState,
)


@dataclass
class PipelineConfig:
    """Knobs the orchestrator caller can tweak per run."""

    # How many top brains to run per engagement, picked by **raw**
    # pack-prior score rather than softmax confidence. The softmax
    # saturates when one pack dominates by 25× (e.g. cabling >> msp on
    # a cabling-heavy engagement that still has MSP onboarding); raw
    # rank surfaces the secondary brains that confidence rounds to 0.
    active_brain_top_n: int = 3
    # Backstop confidence floor — drops dust packs even within the
    # top-N. Defaults loose so msp/wireless/etc. still run when their
    # raw score is non-trivial relative to the dominant pack.
    active_pack_floor: float = 0.0
    # If True, persist the review queue + training log to JSONL on disk.
    persist_review_queue: bool = True
    # If True, enqueue NEEDS_REVIEW + REJECT items into the review queue.
    enqueue_review_items: bool = True
    # Run brain stages concurrently using a ThreadPoolExecutor. With
    # default OLLAMA_NUM_PARALLEL=1, requests serialize at the model
    # layer and parallel offers ~no speedup AND risks thermal throttling
    # bleed-over between calls on Mac. Default 1 (sequential, safe).
    # Bump to 2+ when running against vLLM or Ollama with
    # OLLAMA_NUM_PARALLEL >= N (a real GPU host).
    parallel_brains: int = 1


@dataclass
class PipelineResult:
    """Orchestrator return: per-stage outputs + the artifacts handle."""

    artifacts: BriefArtifacts
    pack_prior: PackPriorState | None = None
    site_reality: SiteRealityState | None = None
    bundles: dict[str, RetrievalBundle] = field(default_factory=dict)
    planner_result: PlannerResult | None = None
    refined_brief: BriefState | None = None
    brain_states: dict[str, Any] = field(default_factory=dict)
    brain_fallbacks: dict[str, bool] = field(default_factory=dict)
    validations: dict[str, ValidationReport] = field(default_factory=dict)
    calibrations: dict[str, CalibratorReport] = field(default_factory=dict)
    composed_brief: ComposedBrief | None = None
    queued_count: int = 0
    stage_records: list[StageRecord] = field(default_factory=list)
    skipped_brains_no_chat: bool = False


@dataclass
class BriefPipeline:
    """Runs Phases 0–6 against one envelope, writing artifacts as it goes."""

    chat_client: ChatClient | None = None
    brain_registry: BrainRegistry = field(default_factory=default_brain_registry)
    domain_registry: DomainPackRegistry = field(default_factory=load_default_registry)
    planner_default_model: str = "qwen3:14b"
    planner_escalated_model: str = "qwen3:32b"
    pack_prior_chat_model: str = "qwen3:14b"
    site_reality_chat_model: str = "qwen3:14b"
    config: PipelineConfig = field(default_factory=PipelineConfig)

    def compile(
        self, envelope_path: Path | str, *, out_dir: Path | str
    ) -> PipelineResult:
        """End-to-end: ``envelope.json`` → ``out_dir/`` of artifacts."""
        envelope_path = Path(envelope_path)
        artifacts = BriefArtifacts(Path(out_dir))
        records: list[StageRecord] = []

        # 00 + 01: load envelope, build evidence runtime.
        runtime, env_record = self._stage_load_runtime(envelope_path, artifacts)
        records.append(env_record)

        try:
            return self._compile_with_runtime(runtime, artifacts, records, envelope_path)
        except Exception:
            # v45.2: on ANY unhandled exception inside _compile_with_runtime,
            # still persist whatever stage records we have so we can
            # diagnose without re-running.  Without this the crash kills
            # pipeline_log.json entirely and we lose every stage's detail.
            import traceback as _tb
            records.append(StageRecord(
                stage="99_unhandled_pipeline_exception",
                status=StageStatus.FAILED,
                started_at=_iso_now(),
                finished_at=_iso_now(),
                duration_ms=0,
                artifact_path=None,
                detail={"traceback": _tb.format_exc()[:4000]},
            ))
            try:
                artifacts.write_pipeline_log(records)
            except Exception:
                pass
            raise
        finally:
            runtime.close()

    def _compile_with_runtime(
        self,
        runtime: EvidenceRuntime,
        artifacts: BriefArtifacts,
        records: list[StageRecord],
        envelope_path: Path,
    ) -> PipelineResult:
        result = PipelineResult(artifacts=artifacts)

        # 10 pack_prior.
        pp_state, rec = self._run_stage(
            "10_pack_prior",
            lambda: PackPrior.with_default_registry(
                chat_client=self.chat_client,
                chat_model_id=self.pack_prior_chat_model,
            ).compute(runtime),
            artifact=artifacts.pack_prior_path,
        )
        result.pack_prior = pp_state
        records.append(rec)

        # 11 site_reality.
        sr_state, rec = self._run_stage(
            "11_site_reality",
            lambda: SiteRealityEngine(
                chat_client=self.chat_client,
                chat_model_id=self.site_reality_chat_model,
            ).compute(runtime),
            artifact=artifacts.site_reality_path,
        )
        result.site_reality = sr_state
        records.append(rec)

        # 20 retrieval bundles per active pack — keyword-density
        # filtered so each brain only sees packets relevant to its
        # domain (huge prompt-size win on multi-pack engagements).
        active_packs = self._pick_active_packs(pp_state)
        pack_keywords = self._build_pack_keywords(active_packs)
        bundles: dict[str, RetrievalBundle] = {}
        assembler = BundleAssembler(runtime=runtime, pack_keywords=pack_keywords)
        for pack_id in active_packs:
            bundle, rec = self._run_stage(
                f"20_retrieval_bundles::{pack_id}",
                lambda pid=pack_id: assembler.assemble(pack_id=pid),
                artifact=artifacts.retrieval_bundle_path(pack_id),
                extra_detail=lambda b: {
                    "packet_count": sum(
                        len(v) for v in b.packets_by_family.values()
                    ),
                    "families": sorted(b.packets_by_family.keys()),
                },
            )
            bundles[pack_id] = bundle
            records.append(rec)
        result.bundles = bundles

        # 30 planner + 31 refiner — only with a chat client.
        if self.chat_client is None:
            result.skipped_brains_no_chat = True
            records.append(
                _skipped_record(
                    "30_planner",
                    detail={"reason": "no chat_client; planner requires LLM"},
                )
            )
            records.append(_skipped_record("31_refiner"))
            for pack_id in active_packs:
                records.append(
                    _skipped_record(
                        f"40_brain::{pack_id}",
                        detail={"reason": "no chat_client"},
                    )
                )
                records.append(_skipped_record(f"50_validator::{pack_id}"))
                records.append(_skipped_record(f"60_calibrator::{pack_id}"))
            records.append(_skipped_record("70_review_queue"))
            records.append(_skipped_record("80_composer"))
            # Inspection still runs in substrate-only mode — that's
            # the most valuable view of what parser-os saw, even
            # without LLM downstream.
            self._run_inspection_stage(artifacts, records)
            artifacts.write_pipeline_log(records)
            artifacts.write_manifest(self._manifest(envelope_path, result, records))
            result.stage_records = records
            return result

        planner = Planner(
            chat_client=self.chat_client,
            default_model=self.planner_default_model,
            escalated_model=self.planner_escalated_model,
        )
        planner_result, rec = self._run_stage(
            "30_planner",
            lambda: planner.compose(
                runtime, pack_prior=pp_state, site_reality=sr_state
            ),
            artifact=artifacts.brief_state_raw_path,
            payload_extractor=lambda r: r.state,
            extra_detail=lambda r: {
                "tier": r.escalation.tier.value,
                "fallback_used": r.fallback_used,
                "validation_errors": list(r.validation_errors),
                "token_cost": r.usage.to_dict(),
                # v45.2 debug: snippet of raw LLM response so we can
                # diagnose JSON parse failures without re-running.
                "raw_response_snippet": (r.raw_response or "")[:2000],
                "raw_response_length": len(r.raw_response or ""),
            },
            fallback_status=lambda r: (
                StageStatus.FALLBACK if r.fallback_used else StageStatus.OK
            ),
        )
        result.planner_result = planner_result
        records.append(rec)

        refined, rec = self._run_stage(
            "31_refiner",
            lambda: refine_brief(
                planner_result.state,
                runtime=runtime,
                pack_prior=pp_state,
                site_reality=sr_state,
            ),
            artifact=artifacts.brief_state_refined_path,
            payload_extractor=lambda r: r.state,
            extra_detail=lambda r: r.to_dict(),
        )
        # v45.2 defensive: _run_stage returns (None, record) on exception.
        # When the refiner LLM call fails, fall back to planner_state.  AND
        # when the PLANNER itself fails (planner_result is None), fall
        # through with refined_brief=None — downstream brain stages already
        # handle that path.  This keeps the pipeline running so we get a
        # complete pipeline_log.json with per-stage error details instead
        # of crashing mid-flight and losing the diagnostic info.
        if refined is not None:
            result.refined_brief = refined.state
        elif planner_result is not None:
            result.refined_brief = planner_result.state
        else:
            result.refined_brief = None
        records.append(rec)

        # 40 brains per active pack with a registered factory.
        validator = BrainOutputValidator(
            lookup=RuntimeEvidenceLookup(runtime=runtime)
        )
        calibrator = Calibrator()
        queue = (
            JsonlReviewQueue(artifacts.review_queue_dir)
            if self.config.persist_review_queue
            else None
        )
        training_log = (
            JsonlTrainingLog(artifacts.review_queue_dir)
            if self.config.persist_review_queue
            else InMemoryTrainingLog()
        )
        # The training log isn't populated here (no decisions yet);
        # it's wired so subsequent reviewer decisions land in the
        # right file. Touch it so the file exists.
        _ = training_log

        # Brain stages can run concurrently — each (factory, refined_brief,
        # bundle) tuple is independent. We dispatch the LLM-bound 40_brain
        # stages in parallel up to ``parallel_brains``; the validator
        # and calibrator follow per-pack once their brain finishes.
        runnable_packs = [p for p in active_packs if self.brain_registry.get(p) is not None]
        skipped_packs = [p for p in active_packs if self.brain_registry.get(p) is None]
        for pack_id in skipped_packs:
            records.append(
                _skipped_record(
                    f"40_brain::{pack_id}",
                    detail={"reason": "no registered brain for pack_id"},
                )
            )
            records.append(_skipped_record(f"50_validator::{pack_id}"))
            records.append(_skipped_record(f"60_calibrator::{pack_id}"))

        def _run_brain(pack_id: str):
            brain = self.brain_registry.get(pack_id)(self.chat_client)  # type: ignore[arg-type,misc]
            return self._run_stage(
                f"40_brain::{pack_id}",
                # v45.2: use result.refined_brief instead of refined.state so brains
                # operate on the fallback planner_state when the refiner failed.
                # See line 290 for the matching defensive None-check.
                lambda b=brain, br=result.refined_brief, bd=bundles[pack_id]: b.compose(br, bd),
                artifact=artifacts.brain_output_path(pack_id),
                payload_extractor=lambda r: r.state,
                extra_detail=lambda r: {
                    "fallback_used": r.fallback_used,
                    "unresolved_packet_ids": list(r.unresolved_packet_ids),
                    "unresolved_atom_ids": list(r.unresolved_atom_ids),
                    "token_cost": r.usage.to_dict(),
                    # v45.2 debug: capture validation errors and a snippet
                    # of the raw LLM response so we can diagnose why a
                    # brain fell back instead of guessing.
                    "validation_errors": list(r.validation_errors or ()),
                    "raw_response_snippet": (r.raw_response or "")[:1000],
                    "raw_response_length": len(r.raw_response or ""),
                },
                fallback_status=lambda r: (
                    StageStatus.FALLBACK if r.fallback_used else StageStatus.OK
                ),
            )

        # Dispatch brains. ``max_workers=1`` forces sequential (compat path).
        brain_outputs: dict[str, tuple[Any, StageRecord]] = {}
        if self.config.parallel_brains > 1 and len(runnable_packs) > 1:
            with ThreadPoolExecutor(
                max_workers=min(self.config.parallel_brains, len(runnable_packs))
            ) as pool:
                futures = {pool.submit(_run_brain, pid): pid for pid in runnable_packs}
                for fut, pid in futures.items():
                    brain_outputs[pid] = fut.result()
        else:
            for pid in runnable_packs:
                brain_outputs[pid] = _run_brain(pid)

        # Validator + calibrator + queue per pack run sequentially —
        # they're cheap (≤ 20 ms each on real envelopes).
        for pack_id in runnable_packs:
            brain_result, brain_rec = brain_outputs[pack_id]
            result.brain_states[pack_id] = brain_result.state
            result.brain_fallbacks[pack_id] = bool(brain_result.fallback_used)
            records.append(brain_rec)

            is_briefing = pack_id in BRIEFING_PACK_IDS
            validate_fn = (
                validator.validate_briefing
                if is_briefing
                else validator.validate_managed_services
            )
            calibrate_fn = (
                calibrator.calibrate_briefing
                if is_briefing
                else calibrator.calibrate_managed_services
            )

            validation_report, rec = self._run_stage(
                f"50_validator::{pack_id}",
                lambda s=brain_result.state, br=refined.state, bd=bundles[pack_id], fn=validate_fn: (
                    fn(s, brief=br, bundle=bd)
                ),
                artifact=artifacts.validation_path(pack_id),
                extra_detail=lambda r: {
                    "rule_counts": r.rule_counts(),
                    "n_passed": len(r.passed_items),
                    "n_failed": len(r.failed_items),
                    "n_blocker": len(r.blocker_items),
                },
            )
            result.validations[pack_id] = validation_report
            records.append(rec)

            calibration_report, rec = self._run_stage(
                f"60_calibrator::{pack_id}",
                lambda s=brain_result.state, v=validation_report, br=refined.state, bd=bundles[pack_id], fn=calibrate_fn: (
                    fn(s, validation=v, brief=br, bundle=bd)
                ),
                artifact=artifacts.calibration_path(pack_id),
                extra_detail=lambda r: {
                    "by_verdict_counts": {
                        k: len(v) for k, v in r.by_verdict().items()
                    },
                },
            )
            result.calibrations[pack_id] = calibration_report
            records.append(rec)

            if (
                queue is not None
                and self.config.enqueue_review_items
                and calibration_report is not None
            ):
                queued = 0
                for item in calibration_report.items:
                    if item.verdict is Verdict.AUTO_ACCEPT:
                        continue
                    queue.enqueue(item)
                    queued += 1
                result.queued_count += queued
                records.append(
                    StageRecord(
                        stage=f"70_review_queue::{pack_id}",
                        status=StageStatus.OK,
                        started_at=_iso_now(),
                        finished_at=_iso_now(),
                        duration_ms=0,
                        artifact_path=str(artifacts.review_queue_dir),
                        detail={"queued": queued},
                    )
                )

        # 80 + 81 composer: aggregate all brain outputs into one document.
        if result.refined_brief is not None and result.brain_states:
            composer_inputs = ComposerInputs(
                brief=result.refined_brief,
                brain_states=result.brain_states,
                calibrations=result.calibrations,
                validations=result.validations,
                fallback_used=result.brain_fallbacks,
            )
            composed, rec = self._run_stage(
                "80_composer",
                lambda: Composer().compose(composer_inputs),
                artifact=artifacts.composed_brief_path,
                extra_detail=lambda c: {
                    "domains": [g.pack_id for g in c.domains],
                    "auto_accept": c.auto_accept_count,
                    "needs_review": c.review_count,
                    "rejected": c.blocker_count,
                },
            )
            if composed is not None:
                result.composed_brief = composed
                self._write_text(
                    artifacts.composed_brief_markdown_path,
                    render_markdown(composed),
                )
            records.append(rec)
        else:
            records.append(
                _skipped_record(
                    "80_composer",
                    detail={"reason": "no brain states to compose"},
                )
            )

        # Write the pipeline log + manifest first so the inspection
        # stage can read them as part of the report.
        artifacts.write_pipeline_log(records)
        artifacts.write_manifest(self._manifest(envelope_path, result, records))

        # 90 + 91 inspection report — comprehensive lineage view across
        # every stage. Always runs (even on no-chat-client / fallback
        # paths) because the value of "what did the substrate see?"
        # doesn't depend on a successful brain run.
        self._run_inspection_stage(artifacts, records)

        # Re-write the pipeline log + manifest so they include the
        # inspection-stage record.
        artifacts.write_pipeline_log(records)
        artifacts.write_manifest(self._manifest(envelope_path, result, records))
        result.stage_records = records
        return result

    def _run_inspection_stage(
        self, artifacts: BriefArtifacts, records: list[StageRecord]
    ) -> None:
        """Build + write the inspection report. Same shape regardless
        of whether the LLM stages ran — substrate-only runs still get
        the full pack_prior / site_reality / atom-lineage view."""
        report, rec = self._run_stage(
            "90_inspection",
            lambda: build_inspection_report(artifacts),
            artifact=artifacts.inspection_json_path,
            extra_detail=lambda r: {
                "atoms": (r.get("funnel") or {}).get("atoms_extracted", 0),
                "packets": (r.get("funnel") or {}).get("packets_certified", 0),
                "active_packs": (r.get("funnel") or {}).get("active_packs", []),
            },
        )
        if report is not None:
            # PM final layer is the FIRST section of the inspection
            # page; build it best-effort so PMs see their view above
            # the engineering view, with one-click links to the
            # standalone PM_EXECUTIVE_SUMMARY / SA_REVIEW_PACKET /
            # PM_HANDOFF artifacts. Failure here never blocks the
            # render; we just fall back to engineering-only HTML.
            pm_handoff_payload: dict[str, Any] | None = None
            try:
                from orbitbrief_core.pm_handoff import build_pm_handoff
                pm_handoff_payload = build_pm_handoff(artifacts.root).to_dict()
            except Exception:
                pm_handoff_payload = None
            try:
                self._write_text(
                    artifacts.inspection_html_path,
                    render_inspection_html(report, pm_handoff=pm_handoff_payload),
                )
            except Exception as exc:  # pragma: no cover - defensive
                rec = StageRecord(
                    stage=rec.stage,
                    status=StageStatus.FALLBACK,
                    started_at=rec.started_at,
                    finished_at=_iso_now(),
                    duration_ms=rec.duration_ms,
                    artifact_path=rec.artifact_path,
                    detail={**(rec.detail or {}), "html_render_error": str(exc)},
                )
        records.append(rec)

    # ───── stage helpers ─────

    def _stage_load_runtime(
        self, envelope_path: Path, artifacts: BriefArtifacts
    ) -> tuple[EvidenceRuntime, StageRecord]:
        start = perf_counter()
        started = _iso_now()
        # Load the envelope dict and write the canonical copy.
        text = envelope_path.read_text(encoding="utf-8")
        envelope_dict = json.loads(text)
        artifacts.write_json(artifacts.envelope_path, envelope_dict)
        runtime = EvidenceRuntime.from_envelope(envelope_dict)
        finished = _iso_now()
        rec = StageRecord(
            stage="00_ingest_envelope",
            status=StageStatus.OK,
            started_at=started,
            finished_at=finished,
            duration_ms=int((perf_counter() - start) * 1000),
            artifact_path=str(artifacts.envelope_path),
            detail={
                "envelope_path": str(envelope_path),
                "atom_count": len(envelope_dict.get("atoms") or []),
                "packet_count": len(envelope_dict.get("packets") or []),
                "entity_count": len(envelope_dict.get("entities") or []),
            },
        )
        return runtime, rec

    def _run_stage(
        self,
        stage: str,
        thunk,
        *,
        artifact: Path,
        payload_extractor=None,
        extra_detail=None,
        fallback_status=None,
    ) -> tuple[Any, StageRecord]:
        """Run ``thunk()``, write its artifact, and return (result, record)."""
        start = perf_counter()
        started = _iso_now()
        try:
            value = thunk()
        except Exception as exc:
            duration = int((perf_counter() - start) * 1000)
            record = StageRecord(
                stage=stage,
                status=StageStatus.FAILED,
                started_at=started,
                finished_at=_iso_now(),
                duration_ms=duration,
                artifact_path=None,
                detail={"error": f"{type(exc).__name__}: {exc}"},
            )
            return None, record

        payload = payload_extractor(value) if payload_extractor is not None else value
        self._write(artifact, payload)

        status = StageStatus.OK
        if fallback_status is not None:
            try:
                status = fallback_status(value) or StageStatus.OK
            except Exception:
                status = StageStatus.OK
        detail = extra_detail(value) if extra_detail is not None else {}
        record = StageRecord(
            stage=stage,
            status=status,
            started_at=started,
            finished_at=_iso_now(),
            duration_ms=int((perf_counter() - start) * 1000),
            artifact_path=str(artifact),
            detail=detail or {},
        )
        return value, record

    def _write(self, artifact: Path, payload: Any) -> None:
        """Write ``payload`` to ``artifact`` as JSON (uses BriefArtifacts.write_json)."""
        artifact.parent.mkdir(parents=True, exist_ok=True)
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump(mode="json")
        artifact.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _write_text(self, artifact: Path, payload: str) -> None:
        """Write ``payload`` (already a string, e.g. Markdown) to ``artifact``."""
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(payload, encoding="utf-8")

    def _build_pack_keywords(self, pack_ids: list[str]) -> dict[str, set[str]]:
        """Per-pack keyword set used by the bundle assembler's filter.

        Drawn from the world-model domain registry — workbook-extracted
        ``keywords`` plus the hand-curated ``boosted_keywords``. The
        assembler keeps a packet only when at least one of these tokens
        appears in its atom text or anchor key.
        """
        out: dict[str, set[str]] = {}
        for pack_id in pack_ids:
            pack = self.domain_registry.get(pack_id)
            if pack is None:
                continue
            kws: set[str] = set()
            for w in pack.keywords:
                kws.add(w.lower())
            for w in pack.boosted_keywords:
                kws.add(w.lower())
            if kws:
                out[pack_id] = kws
        return out

    def _pick_active_packs(self, pack_prior: PackPriorState) -> list[str]:
        """Pick brains to run.

        Preferred source: ``pack_prior.selected_pack_ids`` — the router
        already applied the proper "top + meaningful secondaries"
        selection rules (absolute / fractional / boosted-hits) instead
        of softmax saturation, so this is the source of truth.

        Fallback: legacy top-N raw-score ranking, for back-compat with
        any state that predates ``selected_pack_ids``.
        """
        cap = max(1, self.config.active_brain_top_n)

        if pack_prior.selected_pack_ids:
            active: list[str] = []
            seen: set[str] = set()
            for pid in pack_prior.selected_pack_ids:
                if pid in seen:
                    continue
                active.append(pid)
                seen.add(pid)
                if len(active) >= cap:
                    break
            if pack_prior.top_pack_id and pack_prior.top_pack_id not in seen and len(active) < cap:
                active.append(pack_prior.top_pack_id)
            return active

        # ── legacy path: top-N by raw_score ───────────────────────
        floor = self.config.active_pack_floor
        ranked = sorted(
            pack_prior.scores,
            key=lambda s: (-s.raw_score, -s.confidence, s.pack_id),
        )
        active = []
        seen = set()
        if pack_prior.top_pack_id and pack_prior.top_pack_id not in seen:
            active.append(pack_prior.top_pack_id)
            seen.add(pack_prior.top_pack_id)
        for s in ranked:
            if s.pack_id in seen:
                continue
            if s.raw_score <= 0 and s.confidence < floor:
                continue
            active.append(s.pack_id)
            seen.add(s.pack_id)
            if len(active) >= cap:
                break
        return active

    def _manifest(
        self,
        envelope_path: Path,
        result: PipelineResult,
        records: list[StageRecord],
    ) -> dict[str, Any]:
        return {
            "envelope_path": str(envelope_path),
            "generated_at": _iso_now(),
            "active_packs": list(result.bundles.keys()),
            "brains_run": list(result.brain_states.keys()),
            "queued_for_review": result.queued_count,
            "skipped_brains_no_chat": result.skipped_brains_no_chat,
            "stage_count": len(records),
            "stage_status_counts": _count_statuses(records),
        }


# ────────────────────────────── helpers ────────────────────────────────


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _skipped_record(stage: str, *, detail: dict[str, Any] | None = None) -> StageRecord:
    return StageRecord(
        stage=stage,
        status=StageStatus.SKIPPED,
        started_at=_iso_now(),
        finished_at=_iso_now(),
        duration_ms=0,
        artifact_path=None,
        detail=detail or {},
    )


def _count_statuses(records: list[StageRecord]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in records:
        out[r.status.value] = out.get(r.status.value, 0) + 1
    return out
