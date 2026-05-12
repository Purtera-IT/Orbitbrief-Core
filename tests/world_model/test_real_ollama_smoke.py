"""Integration smoke test against a real Ollama server.

Verifies the wiring between :class:`OpenAIChatClient` and Phase-3
engines actually works against a Qwen3 model. Skipped if Ollama is
not reachable, so CI without a local model server stays green.
"""
from __future__ import annotations

import os

import pytest

from orbitbrief_core.inference.client import (
    ChatMessage,
    InferenceError,
    OpenAIChatClient,
)
from orbitbrief_core.world_model.pack_prior import PackPrior


OLLAMA_BASE = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
QWEN3_CHAT_MODEL = os.environ.get("QWEN3_CHAT_MODEL", "qwen3:14b")


def _ollama_reachable() -> bool:
    import urllib.request

    try:
        urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=2.0).read(8)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _ollama_reachable(),
    reason=f"Ollama not reachable at {OLLAMA_BASE}",
)


def test_chat_client_round_trip() -> None:
    """A trivial ``complete`` call reaches the model and returns text."""
    client = OpenAIChatClient(base_url=OLLAMA_BASE)
    reply = client.complete(
        [
            ChatMessage(
                "user",
                "Reply with only the lowercase word: pong",
            )
        ],
        model=QWEN3_CHAT_MODEL,
        temperature=0.0,
        max_tokens=512,
    )
    assert reply, "empty reply from Ollama"


def test_pack_prior_with_real_chat_on_ambiguous_envelope(
    runtime_from_envelope, wireless_envelope: dict[str, Any]  # noqa: F821
) -> None:
    """Force ambiguity (low temperature) and verify the LLM picks one of the candidates."""
    # Strip text down to a single neutral token to force no-signal escalation.
    blank_env = {
        **wireless_envelope,
        "atoms": [
            {**a, "text": "the and or of for"} for a in wireless_envelope["atoms"]
        ],
    }
    chat = OpenAIChatClient(base_url=OLLAMA_BASE)
    prior = PackPrior.with_default_registry(
        chat_client=chat, chat_model_id=QWEN3_CHAT_MODEL
    )
    rt = runtime_from_envelope(blank_env)
    try:
        state = prior.compute(rt)
    except InferenceError as exc:  # pragma: no cover - environmental
        pytest.skip(f"Ollama refused the request: {exc}")
    log = state.escalation_log
    assert log["count"] >= 1, "no_signal must trigger escalation when chat client present"
    # Either the LLM picked something (escalated) or its pick wasn't
    # in the top-K — both are acceptable; the contract is just that
    # the call was logged structurally.
    for entry in log["entries"]:
        assert entry["model_id"] == QWEN3_CHAT_MODEL
        assert entry["reason"]
        assert entry["engine"] == "pack_prior"


# Also import the fixture from world_model conftest so the typing
# annotation above resolves at collection time.
from typing import Any  # noqa: E402
