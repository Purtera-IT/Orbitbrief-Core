"""``python -m orbitbrief_core.brains`` — preview a brain on a brief + bundle.

Reads:

* ``--brief brief.json``  — a serialized :class:`BriefState`.
* ``--bundle bundle.json`` — a serialized :class:`RetrievalBundle`.

Writes the brain's :class:`ManagedServicesScopeState` JSON to
stdout. Intended for local inspection — production callers use
the brain class directly via the (forthcoming) orchestrator.

Usage:

    python -m orbitbrief_core.brains \\
        --brief brief.json --bundle bundle.json \\
        --brain managed_services --ollama
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from orbitbrief_core.brains._retrieval_bundle import RetrievalBundle
from orbitbrief_core.brains.managed_services import ManagedServicesBrain
from orbitbrief_core.inference.client import (
    NullInferenceClient,
    OpenAIChatClient,
)
from orbitbrief_core.world_model.planner.schema import BriefState


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="orbitbrief_core.brains")
    p.add_argument("--brief", required=True, help="Path to a serialized BriefState JSON")
    p.add_argument(
        "--bundle", required=True, help="Path to a serialized RetrievalBundle JSON"
    )
    p.add_argument(
        "--brain",
        choices=("managed_services",),
        default="managed_services",
        help="Which brain to invoke (more land in later phases).",
    )
    p.add_argument(
        "--ollama",
        action="store_true",
        help="Wire the OpenAI-compatible chat client at OLLAMA_BASE_URL.",
    )
    p.add_argument("--ollama-base-url", default="http://localhost:11434")
    p.add_argument("--chat-model", default="qwen3:14b")
    args = p.parse_args(argv)

    brief = _load_brief(args.brief)
    bundle = _load_bundle(args.bundle)

    if not args.ollama:
        # Without a chat client the brain has nowhere to send the
        # prompt; bail loudly rather than silently emitting fallback.
        print(
            "brain CLI: pass --ollama to run a real LLM (no offline mode "
            "wired today).",
            file=sys.stderr,
        )
        return 2

    chat = OpenAIChatClient(base_url=args.ollama_base_url, timeout_s=240.0)
    if args.brain == "managed_services":
        brain = ManagedServicesBrain(chat_client=chat, model=args.chat_model)
    else:  # pragma: no cover - argparse guards
        print(f"unknown brain {args.brain!r}", file=sys.stderr)
        return 2

    result = brain.compose(brief, bundle)
    out: dict[str, Any] = {
        "state": result.state.model_dump(mode="json"),
        "fallback_used": result.fallback_used,
        "validation_errors": list(result.validation_errors),
        "unresolved_packet_ids": list(result.unresolved_packet_ids),
        "unresolved_atom_ids": list(result.unresolved_atom_ids),
        "usage": result.usage.to_dict(),
    }
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


def _load_brief(path: str) -> BriefState:
    with open(path, encoding="utf-8") as fh:
        return BriefState.model_validate_json(fh.read())


def _load_bundle(path: str) -> RetrievalBundle:
    with open(path, encoding="utf-8") as fh:
        return RetrievalBundle.model_validate_json(fh.read())


# Sanity reference so unused-import linters don't trip.
_ = NullInferenceClient  # noqa: F401


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
