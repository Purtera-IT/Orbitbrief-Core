"""``python -m orbitbrief_core.world_model`` — quick world-model preview.

Loads an envelope through the seam, runs both engines, and prints
:class:`PackPriorState` + :class:`SiteRealityState` as canonical
JSON. Intended for local inspection — production callers should
use the engine classes directly.

Usage:

    python -m orbitbrief_core.world_model path/to/envelope.json
    python -m orbitbrief_core.world_model path/to/envelope.json --engine pack_prior
    python -m orbitbrief_core.world_model path/to/envelope.json --ollama
"""
from __future__ import annotations

import argparse
import json
import sys

from orbitbrief_core.evidence_runtime.runtime import EvidenceRuntime
from orbitbrief_core.inference.client import OpenAIChatClient
from orbitbrief_core.world_model.pack_prior import PackPrior
from orbitbrief_core.world_model.site_reality import SiteRealityEngine


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="orbitbrief_core.world_model")
    p.add_argument("envelope", help="Path to an orbitbrief.input.v2 JSON file")
    p.add_argument(
        "--engine",
        choices=("both", "pack_prior", "site_reality"),
        default="both",
    )
    p.add_argument(
        "--ollama",
        action="store_true",
        help="Wire the OpenAI-compatible chat client at OLLAMA_BASE_URL "
        "(default http://localhost:11434) for LLM escalations.",
    )
    p.add_argument("--ollama-base-url", default="http://localhost:11434")
    p.add_argument("--chat-model", default="qwen3:14b")
    args = p.parse_args(argv)

    chat = (
        OpenAIChatClient(base_url=args.ollama_base_url) if args.ollama else None
    )

    runtime = EvidenceRuntime.from_envelope_path(args.envelope)
    try:
        out: dict = {}
        if args.engine in ("both", "pack_prior"):
            prior = PackPrior.with_default_registry(
                chat_client=chat, chat_model_id=args.chat_model
            )
            out["pack_prior"] = prior.compute(runtime).model_dump(mode="json")
        if args.engine in ("both", "site_reality"):
            engine = SiteRealityEngine(
                chat_client=chat, chat_model_id=args.chat_model
            )
            out["site_reality"] = engine.compute(runtime).model_dump(mode="json")
        json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    finally:
        runtime.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
