#!/usr/bin/env python3
"""``compile_brief.py [envelope.json | case_dir/] --out artifacts/`` — operator one-liner.

Two input modes:

* **Envelope JSON** — an ``orbitbrief.input.v2`` file already produced
  by parser-os. Skips parser-os, runs orbitbrief end-to-end on the
  envelope.

* **Case directory** — a directory of raw artifacts (PDF / DOCX /
  XLSX / CSV / MD / transcripts / emails). Auto-runs parser-os to
  build the envelope first, then orbitbrief end-to-end. Saves the
  envelope under ``<out>/00_envelope.json``.

Usage::

    # Envelope path (existing behavior)
    python compile_brief.py /tmp/envelope.json --out artifacts/ --ollama

    # Case directory (auto-compiles via parser-os first)
    python compile_brief.py testing/managed_services_sow_artifact_pack/COPPER_001_SPRING_LAKE_AUDITORIUM \\
        --out /tmp/COPPER_001_artifacts/ --ollama

    # Quiet parser-os (suppresses replay-error stderr noise on synthetic intake)
    python compile_brief.py <case_dir> --out artifacts/ --ollama --quiet-parser
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from contextlib import nullcontext, redirect_stderr
from io import StringIO
from pathlib import Path

# Make in-tree ``src/`` importable from a checkout.
_REPO_ROOT = Path(__file__).resolve().parent
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _maybe_compile_with_parser_os(
    case_dir: Path, project_id: str | None, *, quiet: bool
) -> Path:
    """Run parser-os on ``case_dir`` and write the envelope to a temp path."""
    parser_os_root_raw = os.environ.get("PARSER_OS_ROOT", "")
    parser_os_root = Path(parser_os_root_raw).expanduser() if parser_os_root_raw else None
    if not parser_os_root or not parser_os_root.is_dir():
        sys.exit(
            "compile_brief: parser-os not found. "
            "Set PARSER_OS_ROOT=/absolute/path/to/parser-os-repo "
            "or pass a prebuilt envelope.json."
        )
    if str(parser_os_root) not in sys.path:
        sys.path.insert(0, str(parser_os_root))

    from app.core.compiler import compile_project  # type: ignore
    from app.core.orbitbrief_envelope import build_orbitbrief_envelope  # type: ignore

    project_id = project_id or case_dir.name
    print(
        f"compile_brief: parser-os compiling {case_dir.name} (project_id={project_id})",
        file=sys.stderr,
    )
    # ``allow_unverified_receipts=True`` keeps source-replay failures (common
    # on synthetic / scan-noisy PDFs) from blocking the compile. Atoms still
    # carry the ``verified`` field downstream so the validator can flag any
    # that downstream consumers care about.
    captured = StringIO()
    ctx = redirect_stderr(captured) if quiet else nullcontext()
    with ctx:
        result = compile_project(
            project_dir=case_dir.resolve(),
            project_id=project_id,
            allow_errors=True,
            allow_unverified_receipts=True,
        )
        envelope = build_orbitbrief_envelope(
            project_dir=case_dir.resolve(), compile_result=result
        )

    tmp_envelope = Path(tempfile.mkdtemp(prefix="ob_envelope_")) / f"{project_id}.json"
    tmp_envelope.write_text(
        json.dumps(envelope, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"compile_brief: envelope written to {tmp_envelope} "
        f"(documents={len(envelope.get('documents') or [])} "
        f"atoms={len(envelope.get('atoms') or [])} "
        f"entities={len(envelope.get('entities') or [])} "
        f"edges={len(envelope.get('edges') or [])} "
        f"packets={len(envelope.get('packets') or [])})",
        file=sys.stderr,
    )
    if quiet and captured.getvalue():
        # Surface a one-line summary of suppressed messages so operators
        # know how much got hidden.
        n_errs = captured.getvalue().count("ERROR:")
        n_warns = captured.getvalue().count("WARN")
        if n_errs or n_warns:
            print(
                f"compile_brief: parser-os emitted {n_errs} ERROR + {n_warns} WARN "
                f"line(s) (suppressed by --quiet-parser; expected on synthetic intake)",
                file=sys.stderr,
            )
    return tmp_envelope


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="compile_brief.py",
        description="Compile a case directory or envelope.json into an OrbitBrief artifacts dir.",
    )
    p.add_argument(
        "input",
        help="Path to either an orbitbrief.input.v2 envelope JSON file OR a case directory of raw artifacts",
    )
    p.add_argument("--out", required=True, help="Output artifacts directory")
    p.add_argument("--project-id", help="Override the project_id (default: case dir name)")
    p.add_argument(
        "--ollama",
        action="store_true",
        help="Wire the OpenAI-compatible chat client at OLLAMA_BASE_URL.",
    )
    p.add_argument("--ollama-base-url", default="http://localhost:11434")
    p.add_argument("--chat-model", default="qwen3:14b")
    # Default escalated tier matches default tier on the local Mac path —
    # qwen3:32b on Apple-Silicon Ollama generates ~30 tok/s which exceeds
    # the 600 s transport timeout on big BriefState JSON. Override with
    # ``--escalated-model qwen3:32b`` on a real GPU host.
    p.add_argument("--escalated-model", default="qwen3:14b")
    p.add_argument(
        "--quiet-parser",
        action="store_true",
        help="Suppress parser-os replay-error stderr noise (safe on synthetic intake).",
    )
    p.add_argument(
        "--no-persist-queue",
        action="store_true",
        help="Skip JSONL review-queue persistence (in-memory only).",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Don't print the manifest summary to stdout at the end.",
    )
    args = p.parse_args(argv)

    src = Path(args.input)
    if not src.exists():
        print(f"compile_brief: not found: {src}", file=sys.stderr)
        return 1

    # Resolve to an envelope path (either the user gave us one, or we
    # build one from a case directory via parser-os).
    if src.is_dir():
        envelope_path = _maybe_compile_with_parser_os(
            src, args.project_id, quiet=args.quiet_parser
        )
    elif src.is_file():
        envelope_path = src
    else:
        print(f"compile_brief: input is neither file nor directory: {src}", file=sys.stderr)
        return 1

    # Now run the orchestrator pipeline on the envelope.
    from orbitbrief_core.inference.client import OpenAIChatClient
    from orbitbrief_core.orchestrator.pipeline import (
        BriefPipeline,
        PipelineConfig,
    )

    chat = (
        # 1200 s transport timeout keeps us safe even when the brain
        # runs through 12 k tokens of JSON on a slow tier (qwen3:32b ~ 30 tok/s).
        OpenAIChatClient(base_url=args.ollama_base_url, timeout_s=1200.0)
        if args.ollama
        else None
    )
    pipeline = BriefPipeline(
        chat_client=chat,
        planner_default_model=args.chat_model,
        planner_escalated_model=args.escalated_model,
        pack_prior_chat_model=args.chat_model,
        site_reality_chat_model=args.chat_model,
        config=PipelineConfig(
            persist_review_queue=not args.no_persist_queue,
        ),
    )
    result = pipeline.compile(envelope_path, out_dir=args.out)

    # Final PM/SA presentation layer — this is what the user actually
    # consumes. Render markdown + html + json into the same case
    # output directory so the substrate dir doubles as the PM
    # handoff. Failures here never block compile completion.
    try:
        from orbitbrief_core.pm_handoff import (
            build_pm_handoff,
            render_pm_executive_markdown,
            render_solution_architect_markdown,
            render_pm_handoff_markdown,
            render_sow_draft,
        )
        from orbitbrief_core.pm_handoff.rfp_draft import render_rfp_draft
        from orbitbrief_core.pm_handoff.render_html import (
            render_pm_executive_html,
            render_solution_architect_html,
            render_pm_handoff_html,
        )
        from pathlib import Path as _Path
        out_dir = _Path(args.out)
        handoff = build_pm_handoff(out_dir)
        (out_dir / "PM_EXECUTIVE_SUMMARY.md").write_text(
            render_pm_executive_markdown(handoff), encoding="utf-8"
        )
        (out_dir / "SA_REVIEW_PACKET.md").write_text(
            render_solution_architect_markdown(handoff), encoding="utf-8"
        )
        (out_dir / "PM_HANDOFF.md").write_text(
            render_pm_handoff_markdown(handoff), encoding="utf-8"
        )
        # B1: SOW draft — picks atoms straight from the inspection
        # report so we don't reload the envelope here.
        try:
            _report_path = out_dir / "90_inspection_report.json"
            if _report_path.exists():
                _report = json.loads(_report_path.read_text(encoding="utf-8"))
                (out_dir / "SOW_DRAFT.md").write_text(
                    render_sow_draft(handoff, _report), encoding="utf-8"
                )
        except Exception:
            pass
        # B8: vendor RFP draft — only written when the intake has
        # vendor_line_item atoms. ``render_rfp_draft`` returns ""
        # when there's nothing to RFP, so the file is skipped in
        # that case.
        rfp_md = ""
        try:
            rfp_md = render_rfp_draft(handoff)
            if rfp_md:
                (out_dir / "RFP_DRAFT.md").write_text(rfp_md, encoding="utf-8")
        except Exception:
            pass
        # Embed the rendered SOW + RFP markdown into PM_HANDOFF.json
        # so a UI consumer can pull all three deliverables (PM brief,
        # SOW draft, RFP draft) from a single JSON payload.
        sow_md = ""
        try:
            _report_path2 = out_dir / "90_inspection_report.json"
            if _report_path2.exists():
                _report2 = json.loads(_report_path2.read_text(encoding="utf-8"))
                sow_md = render_sow_draft(handoff, _report2)
        except Exception:
            pass
        handoff_dict = handoff.to_dict()
        handoff_dict["sow_draft_markdown"] = sow_md
        handoff_dict["rfp_draft_markdown"] = rfp_md
        (out_dir / "PM_HANDOFF.json").write_text(
            json.dumps(handoff_dict, indent=2), encoding="utf-8"
        )
        # Append the brief's snapshot to the corpus history ledger
        # so future runs can surface comparable past deals.
        try:
            from orbitbrief_core.pm_handoff.pm_intelligence import write_corpus_history
            import os as _os
            history_path = _os.environ.get(
                "ORBITBRIEF_CORPUS_HISTORY",
                str((out_dir / ".orbitbrief_history.jsonl").resolve()),
            )
            domains_active = [d.label for d in handoff.domains if d.active_for_sow]
            margin = handoff.margin_view or {}
            write_corpus_history(history_path, {
                "case_id": handoff.case_id,
                "closed_at": "",
                "deal_value_usd": int(margin.get("deal_total") or 0),
                "domains": domains_active,
                "sites_count": len(handoff.sites),
                "phase_count": len(handoff.schedule_phases),
                "final_margin_pct": float(margin.get("margin_pct") or 0),
                "outcome": "",
            })
        except Exception:
            pass
        (out_dir / "PM_EXECUTIVE_SUMMARY.html").write_text(
            render_pm_executive_html(handoff), encoding="utf-8"
        )
        (out_dir / "SA_REVIEW_PACKET.html").write_text(
            render_solution_architect_html(handoff), encoding="utf-8"
        )
        (out_dir / "PM_HANDOFF.html").write_text(
            render_pm_handoff_html(handoff), encoding="utf-8"
        )
        if not args.quiet:
            print(
                f"compile_brief: PM handoff written ({handoff.status.upper()}: "
                f"{len([g for g in handoff.gaps if g.severity == 'blocker'])} blocker / "
                f"{len([g for g in handoff.gaps if g.severity == 'warning'])} warning)",
                file=sys.stderr,
            )
    except Exception as exc:
        if not args.quiet:
            print(f"compile_brief: PM handoff render skipped: {exc}", file=sys.stderr)

    if not args.quiet:
        manifest = json.loads(result.artifacts.manifest_path.read_text(encoding="utf-8"))
        json.dump(manifest, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
