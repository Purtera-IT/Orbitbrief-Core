"""A brief built on hash vectors must SAY it was.

The embedder (a single Mac serving qwen3-embedding:8b behind Cloudflare) was
returning 530/502 while every brief today reported success. The fallback to
DeterministicHashEmbedder is correct -- a flapping proxy must not kill a compile
-- but it was logged at WARNING and recorded nowhere, so degraded briefs were
indistinguishable from healthy ones. Hash vectors encode nothing: paraphrased
duplicates stop collapsing and fact-quality scoring degrades with them.
"""
from __future__ import annotations

import pytest

from orbitbrief_core.pm_handoff.semantic_dedupe import (
    embedder_health,
    record_embedder_failure,
    reset_embedder_health,
)


@pytest.fixture(autouse=True)
def _clean():
    reset_embedder_health()
    yield
    reset_embedder_health()


def test_healthy_by_default():
    h = embedder_health()
    assert h["degraded"] is False


def test_failure_is_recorded_and_loud():
    record_embedder_failure("HTTP 502 Bad Gateway", url="https://embed.example/api/embed")
    h = embedder_health()
    assert h["degraded"] is True
    assert "502" in h["error"]
    assert h["backend"] == "https://embed.example/api/embed"
    # the consequence must be stated, not just the error
    assert "dedupe" in h["impact"]


def test_repeat_failures_count_but_keep_first_error():
    record_embedder_failure("HTTP 530", url="https://embed.example/api/embed")
    record_embedder_failure("HTTP 502", url="https://embed.example/api/embed")
    h = embedder_health()
    assert h["failures"] == 2
    assert "530" in h["error"]


def test_reset_clears_between_compiles():
    record_embedder_failure("HTTP 502")
    reset_embedder_health()
    assert embedder_health()["degraded"] is False


def test_healthy_azure_run_names_azure_not_the_mac(monkeypatch):
    """A healthy run reported the Mac's URL as its backend — wrong and misleading."""
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://aoai.example.com")
    monkeypatch.setenv("AZURE_OPENAI_EMBED_DEPLOYMENT", "text-embedding-3-small")
    monkeypatch.setenv("OLLAMA_EMBED_URL", "https://mac.example/api/embed")
    h = embedder_health()
    assert h["degraded"] is False
    assert "aoai.example.com" in h["backend"]
    assert "mac.example" not in h["backend"]
