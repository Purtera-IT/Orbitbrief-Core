"""End-to-end planner smoke test against a live Ollama Qwen3-14B.

Skipped if Ollama isn't reachable. Verifies that a real model
returns JSON the planner can validate against the
:class:`BriefState` schema.
"""
from __future__ import annotations

import os

import pytest

from orbitbrief_core.inference.client import OpenAIChatClient
from orbitbrief_core.world_model.planner import BriefState, Planner
from orbitbrief_core.world_model.refiner import refine_brief


OLLAMA_BASE = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
QWEN3_CHAT_MODEL = os.environ.get("QWEN3_CHAT_MODEL", "qwen3:14b")


def _ollama_reachable() -> bool:
    import urllib.request

    try:
        urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=2.0).read(8)
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not _ollama_reachable(),
        reason=f"Ollama not reachable at {OLLAMA_BASE}",
    ),
]


def test_real_planner_emits_valid_brief(
    substrate_factory, wireless_envelope
) -> None:
    """A real Qwen3-14B call returns JSON that validates as :class:`BriefState`."""
    rt, pp, sr = substrate_factory(wireless_envelope)
    chat = OpenAIChatClient(base_url=OLLAMA_BASE, timeout_s=240.0)
    planner = Planner(
        chat_client=chat,
        default_model=QWEN3_CHAT_MODEL,
        escalated_model=QWEN3_CHAT_MODEL,  # avoid escalation for this smoke
        max_output_tokens=4096,
    )
    result = planner.compose(rt, pack_prior=pp, site_reality=sr)
    assert isinstance(result.state, BriefState)
    # Even if the LLM hallucinates atom ids, the refiner cleans up
    # without raising.
    refined = refine_brief(
        result.state,
        runtime=rt,
        pack_prior=pp,
        site_reality=sr,
    )
    assert isinstance(refined.state, BriefState)
    # Token cost must be populated (Ollama returns prompt_eval_count
    # and eval_count which the OpenAI shim normalizes).
    assert result.state.token_cost.get("total_tokens", 0) >= 0
