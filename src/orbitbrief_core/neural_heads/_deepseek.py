"""Minimal DeepSeek client for the teacher/judge heads.

Production reads the key from the env var ``DEEPSEEK_API_KEY`` ONLY — never from a
local file. If the key is absent, :func:`deepseek_json` returns ``None`` so every
head degrades to a graceful no-op (the brief is unaffected). Stdlib-only (urllib)
so the worker needs no new package.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request

_URL = "https://api.deepseek.com/v1/chat/completions"


def deepseek_available() -> bool:
    return bool(os.environ.get("DEEPSEEK_API_KEY", "").strip())


def _repair(text: str) -> dict | None:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(re.sub(r",\s*([}\]])", r"\1", m.group(0)))
    except Exception:
        return None


def deepseek_json(system: str, user: str, *, max_tokens: int = 2000,
                  temperature: float = 0.1, timeout_s: float = 90.0) -> dict | None:
    """Call DeepSeek with JSON-object response format. Returns the parsed dict, or
    ``None`` on any failure (no key / transport / bad JSON). Never raises."""
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        return None
    body = json.dumps({
        "model": "deepseek-chat", "temperature": temperature, "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(_URL, data=body, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as r:
                content = json.loads(r.read())["choices"][0]["message"]["content"]
            parsed = _repair(content)
            if parsed is not None:
                return parsed
            return None
        except Exception:
            if attempt == 2:
                return None
            time.sleep(2 * (attempt + 1))
    return None
