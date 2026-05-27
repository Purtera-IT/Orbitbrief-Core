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


def _post_chat_streaming(
    url: str, payload: dict, *, timeout_s: float, api_key: str | None
) -> tuple[str, dict]:
    """POST a /v1/chat/completions request with ``stream: true`` and
    accumulate the SSE chunks into a single response text.

    Why streaming?  When running through the Azure ollama-mac-studio-proxy
    (Tailscale userspace netstack), non-streamed responses on slow LLM
    generations (e.g. qwen3:14b emitting ~12k BriefState JSON tokens, ~2 min
    of internal generation) trigger Tailscale's idle-connection teardown
    because NO TCP packets flow between proxy and Mac while Ollama is
    generating internally.  Streaming sends each token as an SSE chunk →
    continuous TCP activity → no idle period → Tailscale netstack keeps the
    connection alive.

    Returns (accumulated_text, last_chunk_dict).  The final chunk is the
    one carrying usage info on most backends; if a chunk has no usage we
    return an empty dict — the caller fills in defaults.

    Accumulation handles both OpenAI-style ``delta.content`` and Ollama's
    Qwen3 thinking-mode ``delta.reasoning``.  When content is non-empty we
    use it; otherwise fall back to reasoning so we never lose the model's
    answer.
    """
    body = json.dumps({**payload, "stream": True}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
        },
        method="POST",
    )

    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    last_chunk: dict = {}

    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="ignore").rstrip("\r\n")
                if not line.startswith("data:"):
                    continue
                payload_str = line[len("data:"):].strip()
                if not payload_str or payload_str == "[DONE]":
                    if payload_str == "[DONE]":
                        break
                    continue
                try:
                    chunk = json.loads(payload_str)
                except json.JSONDecodeError:
                    continue
                last_chunk = chunk
                try:
                    choices = chunk.get("choices") or []
                    if choices:
                        delta = choices[0].get("delta") or {}
                        c = delta.get("content")
                        if c:
                            content_parts.append(str(c))
                        r = delta.get("reasoning")
                        if r:
                            reasoning_parts.append(str(r))
                except (AttributeError, TypeError):
                    continue
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            detail = ""
        raise InferenceError(
            f"HTTP {exc.code} from {url}: {exc.reason}; body={detail!r}"
        ) from exc
    except (urllib.error.URLError, socket.timeout) as exc:
        raise InferenceError(f"transport error against {url}: {exc}") from exc

    content_text = "".join(content_parts).strip()
    reasoning_text = "".join(reasoning_parts).strip()
    final_text = content_text or reasoning_text
    if not final_text:
        raise InferenceError(
            f"streaming response produced no content from {url} "
            f"(last_chunk={last_chunk!r})"
        )
    return final_text, last_chunk


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


@dataclass(frozen=True)
class ChatUsage:
    """Token accounting for one chat call.

    Servers vary in what they report; missing fields are zero.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    # Wall time in milliseconds of the HTTP round-trip (transport +
    # generate). Useful for the cost telemetry rollup.
    latency_ms: int = 0

    def merged_with(self, other: "ChatUsage") -> "ChatUsage":
        return ChatUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            latency_ms=self.latency_ms + other.latency_ms,
        )

    def to_dict(self) -> dict:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
        }


@dataclass(frozen=True)
class ChatResult:
    """Text + usage + raw payload for one chat call."""

    text: str
    model: str
    usage: ChatUsage
    raw: dict  # the parsed JSON response (for debugging)


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

    def complete_with_usage(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> ChatResult:
        """Same as :meth:`complete` but returns text + token usage + raw response."""
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
        return self.complete_with_usage(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        ).text

    def complete_with_usage(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> ChatResult:
        if not messages:
            raise InferenceError("complete: messages list is empty")
        payload: dict = {
            "model": model,
            "temperature": float(temperature),
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            # v45.2: disable Qwen3 thinking mode.  With thinking on, the
            # model spends its token budget emitting chain-of-thought into
            # `reasoning` and never reaches the actual `content`.  Planner /
            # brains then receive empty content and silently fall back to
            # planner-state defaults → degraded brief quality.  Setting
            # think:false matches the parser-os _call_ollama payload (which
            # is why parser-os has never had this issue).  Ollama-specific
            # extension on /v1/chat/completions; real OpenAI ignores it.
            "think": False,
            # Belt-and-suspenders: also pass the canonical Qwen3 chat
            # template kwarg in case the Ollama version routes through
            # the template engine instead of the top-level flag.
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)
        if response_format is not None:
            payload["response_format"] = response_format
        import time

        start = time.perf_counter()
        # v45.2: use streaming so each token flows as an SSE chunk over
        # TCP.  Through Azure → Tailscale userspace netstack → Mac
        # Studio, NON-streaming requests on slow generations (~2 min for
        # 12k BriefState tokens) trigger Tailscale's idle-connection
        # teardown and the response gets cut mid-stream with
        # httpx.ReadError.  Streaming keeps the connection active end-to-end.
        text, last_chunk = _post_chat_streaming(
            self._url("/v1/chat/completions"),
            payload,
            timeout_s=self.timeout_s,
            api_key=self.api_key,
        )
        latency_ms = int((time.perf_counter() - start) * 1000)

        # Usage is typically in the very last chunk before [DONE].  If the
        # backend doesn't include it (some streaming impls don't), fall
        # back to defaults so the rest of the pipeline keeps going.
        usage_raw = (last_chunk.get("usage") if isinstance(last_chunk, dict) else None) or {}
        usage = ChatUsage(
            prompt_tokens=int(usage_raw.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage_raw.get("completion_tokens", 0) or 0),
            total_tokens=int(usage_raw.get("total_tokens", 0) or 0),
            latency_ms=latency_ms,
        )
        return ChatResult(text=text, model=model, usage=usage, raw=last_chunk)

    def _url(self, path: str) -> str:
        return self.base_url.rstrip("/") + path
