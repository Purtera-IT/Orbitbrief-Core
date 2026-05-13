"""``python -m orbitbrief_core.orchestrator`` — the end-to-end CLI.

Usage::

    python -m orbitbrief_core.orchestrator compile <envelope.json> \\
        --out <artifacts/> [--ollama] [--chat-model qwen3:14b] \\
        [--escalated-model qwen3:32b] [--ollama-base-url http://localhost:11434]

Without ``--ollama`` the substrate stages run, planner + brains
SKIP, and you still get the pack_prior + site_reality artifacts.
With ``--ollama`` the full Phase-0..6 pipeline runs.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from orbitbrief_core.inference.client import OpenAIChatClient
from orbitbrief_core.orchestrator.pipeline import (
    BriefPipeline,
    PipelineConfig,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orbitbrief_core.orchestrator")
    sub = parser.add_subparsers(dest="cmd", required=True)

    compile_p = sub.add_parser(
        "compile", help="Run the full Phase 0–6 pipeline on one envelope."
    )
    compile_p.add_argument("envelope", help="Path to an orbitbrief.input.v2 JSON file")
    compile_p.add_argument(
        "--out",
        required=True,
        help="Output artifacts directory (created if it doesn't exist)",
    )
    compile_p.add_argument(
        "--ollama",
        action="store_true",
        help="Wire the OpenAI-compatible chat client at OLLAMA_BASE_URL.",
    )
    compile_p.add_argument("--ollama-base-url", default="http://localhost:11434")
    compile_p.add_argument("--chat-model", default="qwen3:14b")
    # Default escalated tier matches default tier on the local Mac path
    # — qwen3:32b on Apple-Silicon Ollama generates ~30-40 tok/s which
    # runs out of the 600 s transport timeout on big BriefState JSON.
    # Override with --escalated-model qwen3:32b on a real GPU host.
    compile_p.add_argument("--escalated-model", default="qwen3:14b")
    compile_p.add_argument(
        "--no-persist-queue",
        action="store_true",
        help="Skip JSONL review-queue persistence (in-memory only).",
    )
    compile_p.add_argument(
        "--quiet",
        action="store_true",
        help="Don't print the manifest summary to stdout.",
    )

    args = parser.parse_args(argv)

    if args.cmd == "compile":
        return _cmd_compile(args)
    parser.print_help()
    return 2


def _cmd_compile(args) -> int:
    envelope_path = Path(args.envelope)
    if not envelope_path.is_file():
        print(f"envelope not found: {envelope_path}", file=sys.stderr)
        return 1

    chat = (
        # 600s timeout covers Qwen3-14B emitting up to 12k tokens of
        # BriefState JSON on a 600+ atom engagement. Ollama on Mac
        # caps generation at ~150 tok/s on the 14B model.
        OpenAIChatClient(base_url=args.ollama_base_url, timeout_s=600.0)
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

    if not args.quiet:
        manifest = json.loads(result.artifacts.manifest_path.read_text(encoding="utf-8"))
        json.dump(manifest, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
