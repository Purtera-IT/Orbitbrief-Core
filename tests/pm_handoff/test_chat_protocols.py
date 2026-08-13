"""Two chat protocols exist in this codebase; each caller must get the right one.

`_raw_chat` returns the inference protocol — complete(messages, model=).
`_briefing_chat` returns the pm_briefing protocol — complete(system=, user=).

Handing question_llm the briefing wrapper produced
`_BriefingChat.complete() got an unexpected keyword argument 'model'` on every
call, so the exposure generator returned zero questions live while every unit
test passed — the tests used stubs that accepted anything. These assert the real
adapters against the real call shapes.
"""
from __future__ import annotations

import inspect

import pytest


def _sig(fn):
    return inspect.signature(fn)


def test_briefing_chat_speaks_system_user(monkeypatch):
    monkeypatch.setenv("ORBITBRIEF_CHAT_MODEL", "test-model")
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://example.invalid")
    from orbitbrief_core.pm_handoff.builder import _briefing_chat

    client, model = _briefing_chat()
    assert client is not None and model == "test-model"
    params = _sig(client.complete).parameters
    assert "system" in params and "user" in params
    assert "model" not in params  # pm_briefing never passes model


def test_raw_chat_speaks_messages_model(monkeypatch):
    monkeypatch.setenv("ORBITBRIEF_CHAT_MODEL", "test-model")
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://example.invalid")
    from orbitbrief_core.pm_handoff.builder import _raw_chat

    client, model = _raw_chat()
    assert client is not None and model == "test-model"
    params = _sig(client.complete).parameters
    assert "model" in params
    assert "system" not in params  # inference protocol takes a message list


@pytest.mark.parametrize("var", ["ORBITBRIEF_CHAT_MODEL", "OLLAMA_BASE_URL"])
def test_both_are_off_when_unconfigured(monkeypatch, var):
    monkeypatch.setenv("ORBITBRIEF_CHAT_MODEL", "test-model")
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://example.invalid")
    monkeypatch.delenv(var, raising=False)
    from orbitbrief_core.pm_handoff.builder import _briefing_chat, _raw_chat

    assert _raw_chat() == (None, "")
    assert _briefing_chat() == (None, "")
