"""HTTP client for OpenAI-compatible inference endpoints (vLLM today).

Two implementations:

* :class:`VllmInferenceClient` — real HTTP via stdlib ``urllib`` (no
  extra dependency just for embed/rerank). Targets vLLM's
  ``/v1/embeddings`` and ``/v1/rerank``.
* :class:`NullInferenceClient` — raises on every call. Wires up the
  protocol so retrieval components fail loud when an inference
  client wasn't supplied (rather than silently returning empty
  vectors).

Both implement the :class:`InferenceClient` protocol so retrieval
backends can swap them. Tests pass a deterministic-stub
implementation defined in ``tests/retrieval/conftest.py``.

Why stdlib ``urllib`` instead of ``httpx`` / ``requests``?
The Phase-2 surface is two endpoints. Adding a transport library
just for that bloats the dep tree of a layer that's supposed to be
small and crisp. We can swap to ``httpx`` if we ever need async or
HTTP/2.
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol


class InferenceError(RuntimeError):
    """Raised on any inference-client failure (transport, status, decode)."""


class InferenceClient(Protocol):
    """Minimum surface every inference backend must offer.

    All shapes are plain Python — no Pydantic at the boundary so
    retrieval can pin its own types.
    """

    def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        """Return one fixed-dim float vector per input text, in order."""
        ...

    def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        model: str,
        top_n: int | None = None,
    ) -> list[tuple[int, float]]:
        """Return ``[(original_index, score), ...]`` sorted by score desc."""
        ...


# ────────────────────────────── stdlib HTTP helper ────────────────────


def _post_json(url: str, payload: dict, *, timeout_s: float, api_key: str | None) -> dict:
    """POST JSON, return parsed JSON. Raises :class:`InferenceError` on any failure."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        # Capture response body for debugging — vLLM puts its
        # error reason there, not in the exception message.
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            detail = ""
        raise InferenceError(
            f"HTTP {exc.code} from {url}: {exc.reason}; body={detail!r}"
        ) from exc
    except (urllib.error.URLError, socket.timeout) as exc:
        raise InferenceError(f"transport error against {url}: {exc}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InferenceError(
            f"non-JSON response from {url}: {raw[:200]!r}"
        ) from exc


# ────────────────────────────── implementations ───────────────────────


@dataclass
class VllmInferenceClient:
    """OpenAI-compatible HTTP client.

    ``base_url`` is the vLLM root, e.g. ``http://localhost:8000``;
    we append ``/v1/embeddings`` and ``/v1/rerank``. Set ``api_key``
    if you've fronted vLLM with an auth proxy; vLLM itself doesn't
    require one.
    """

    base_url: str
    api_key: str | None = None
    timeout_s: float = 60.0

    def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        if not texts:
            return []
        payload = {"model": model, "input": texts}
        data = _post_json(
            self._url("/v1/embeddings"),
            payload,
            timeout_s=self.timeout_s,
            api_key=self.api_key,
        )
        try:
            ordered = sorted(data["data"], key=lambda d: int(d["index"]))
            return [list(map(float, d["embedding"])) for d in ordered]
        except (KeyError, TypeError, ValueError) as exc:
            raise InferenceError(
                f"unexpected embeddings response shape: {data!r}"
            ) from exc

    def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        model: str,
        top_n: int | None = None,
    ) -> list[tuple[int, float]]:
        if not documents:
            return []
        payload: dict = {"model": model, "query": query, "documents": documents}
        if top_n is not None:
            payload["top_n"] = top_n
        data = _post_json(
            self._url("/v1/rerank"),
            payload,
            timeout_s=self.timeout_s,
            api_key=self.api_key,
        )
        try:
            results = data["results"]
            return [
                (int(r["index"]), float(r["relevance_score"]))
                for r in results
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise InferenceError(
                f"unexpected rerank response shape: {data!r}"
            ) from exc

    def _url(self, path: str) -> str:
        return self.base_url.rstrip("/") + path


class NullInferenceClient:
    """Sentinel that fails loud — used when a layer was constructed without a real client.

    We prefer this over silently returning empty vectors because
    silent retrieval emptiness is hard to root-cause.
    """

    def embed(self, texts: list[str], *, model: str) -> list[list[float]]:  # noqa: ARG002
        raise InferenceError(
            "NullInferenceClient.embed() called — wire a real "
            "InferenceClient (VllmInferenceClient or test stub) before retrieval"
        )

    def rerank(  # noqa: ARG002
        self,
        query: str,
        documents: list[str],
        *,
        model: str,
        top_n: int | None = None,
    ) -> list[tuple[int, float]]:
        raise InferenceError(
            "NullInferenceClient.rerank() called — wire a real "
            "InferenceClient (VllmInferenceClient or test stub) before retrieval"
        )


# ────────────────────────────── chat ──────────────────────────────────


@dataclass(frozen=True)
class ChatMessage:
    """One turn in a chat conversation. Mirrors OpenAI message shape."""

    role: str  # "system" | "user" | "assistant"
    content: str


class ChatClient(Protocol):
    """Minimum chat surface: a non-streaming completion."""

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> str:
        """Return the assistant's full text reply (non-streaming)."""
        ...


@dataclass
class OpenAIChatClient:
    """OpenAI-compatible ``/v1/chat/completions`` client.

    Targets vLLM, Ollama, LM Studio, OpenRouter, and proper OpenAI
    interchangeably. ``base_url`` is the server root; we append
    ``/v1/chat/completions``. ``temperature=0.0`` is the default
    because Phase-3 escalations want deterministic output.
    """

    base_url: str
    api_key: str | None = None
    timeout_s: float = 120.0

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> str:
        if not messages:
            raise InferenceError("complete: messages list is empty")
        payload: dict = {
            "model": model,
            "temperature": float(temperature),
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)
        if response_format is not None:
            payload["response_format"] = response_format
        data = _post_json(
            self._url("/v1/chat/completions"),
            payload,
            timeout_s=self.timeout_s,
            api_key=self.api_key,
        )
        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise InferenceError(
                f"unexpected chat response shape: {data!r}"
            ) from exc

    def _url(self, path: str) -> str:
        return self.base_url.rstrip("/") + path
