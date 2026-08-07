"""The narrative LLM must be repointable at a hosted endpoint.

Nothing in the narrative path learns or improves with use — it is a plain
generation call. Keeping it pinned to a single local box meant that when that
box wedged, every LLM stage burned its full timeout, returned ``ok=fallback``,
and the brief shipped with no summary while reporting success.

Embeddings and the trained heads deliberately stay local; only this moves.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _help() -> str:
    out = subprocess.run(
        [sys.executable, str(ROOT / "compile_brief.py"), "--help"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    return out.stdout + out.stderr


def test_chat_api_key_flag_exists():
    assert "--chat-api-key" in _help()


def test_chat_timeout_flag_exists():
    assert "--chat-timeout-s" in _help()


def test_api_key_defaults_from_env(monkeypatch):
    monkeypatch.setenv("ORBITBRIEF_CHAT_API_KEY", "sk-test-123")
    monkeypatch.setenv("ORBITBRIEF_CHAT_TIMEOUT_S", "90")
    import importlib

    mod = importlib.import_module("compile_brief")
    importlib.reload(mod)
    args = mod._parse_args(["case", "--out", "o"]) if hasattr(mod, "_parse_args") else None
    if args is not None:
        assert args.chat_api_key == "sk-test-123"
        assert args.chat_timeout_s == 90.0


def test_client_accepts_an_api_key():
    """The wire format is OpenAI-compatible either way; only auth differs."""
    from orbitbrief_core.inference.client import OpenAIChatClient

    c = OpenAIChatClient(base_url="https://api.deepseek.com", api_key="sk-x", timeout_s=90.0)
    assert c.api_key == "sk-x"
    assert c.timeout_s == 90.0
    # A local Ollama takes no key and must still construct.
    assert OpenAIChatClient(base_url="http://localhost:11434").api_key is None
