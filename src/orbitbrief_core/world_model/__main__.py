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
from orbitbrief_core.world_model.planner import Planner
from orbitbrief_core.world_model.refiner import refine_brief
from orbitbrief_core.world_model.site_reality import SiteRealityEngine


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="orbitbrief_core.world_model")
    p.add_argument("envelope", help="Path to an orbitbrief.input.v2 JSON file")
    p.add_argument(
        "--engine",
        choices=("both", "pack_prior", "site_reality", "planner"),
        default="both",
        help=(
            "'both' runs pack_prior + site_reality only. 'planner' "
            "additionally calls the LLM to emit a refined BriefState."
        ),
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
        prior = PackPrior.with_default_registry(
            chat_client=chat, chat_model_id=args.chat_model
        )
        engine = SiteRealityEngine(
            chat_client=chat, chat_model_id=args.chat_model
        )
        pp_state = prior.compute(runtime)
        sr_state = engine.compute(runtime)
        if args.engine in ("both", "pack_prior"):
            out["pack_prior"] = pp_state.model_dump(mode="json")
        if args.engine in ("both", "site_reality"):
            out["site_reality"] = sr_state.model_dump(mode="json")
        if args.engine == "planner":
            if chat is None:
                print(
                    "planner requires --ollama (chat client mandatory)",
                    file=sys.stderr,
                )
                return 2
            planner = Planner(chat_client=chat, default_model=args.chat_model)
            result = planner.compose(
                runtime, pack_prior=pp_state, site_reality=sr_state
            )
            refined = refine_brief(
                result.state,
                runtime=runtime,
                pack_prior=pp_state,
                site_reality=sr_state,
            )
            out["planner"] = {
                "brief_state": refined.state.model_dump(mode="json"),
                "escalation": result.escalation.to_dict(),
                "fallback_used": result.fallback_used,
                "validation_errors": list(result.validation_errors),
                "refinement": refined.to_dict(),
            }
        json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    finally:
        runtime.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
