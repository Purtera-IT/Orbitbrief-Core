#!/usr/bin/env python3
"""One-command setup helper for vision OCR.

Pulls a vision-capable Ollama model on the configured Ollama host so
the OCR chain in parser-os ``_ocr_chain.py`` can fall through to
``ollama_vision/<model>`` when Tesseract / pytesseract / easyocr
aren't installed locally.

Usage:
    python tools/setup_vision_ocr.py [--model llava] [--base-url URL]

Default base URL matches the Phase 1.5 Mac Studio Tailscale setup
(``http://100.114.102.122:11434``). Override with ``--base-url`` or the
``OLLAMA_BASE_URL`` environment variable.

The script:
  1. Verifies the Ollama host is reachable.
  2. Checks whether the target vision model is already pulled.
  3. Triggers a streaming pull if not present, with progress in stderr.
  4. Smoke-tests the model with a 1×1 white pixel so the user sees
     a known-good response shape before relying on it for a real
     image.

Vision-capable Ollama models we recommend (smallest → largest):
  * ``moondream``       — 1.6 GB, tiny but accurate enough for OCR
  * ``llava``           — 4.7 GB, the standard vision model
  * ``bakllava``        — 4.5 GB, llava variant tuned on documents
  * ``llama3.2-vision`` — 7.9 GB, Meta's vision model
  * ``qwen2.5vl``       — 5.0 GB, Qwen's vision flagship (best for docs)
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.request
from typing import Any


def _request_json(url: str, *, data: dict[str, Any] | None = None, method: str = "GET", timeout: int = 30) -> dict[str, Any]:
    payload = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"} if payload else {},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


def _check_host(base_url: str) -> dict[str, Any]:
    return _request_json(f"{base_url.rstrip('/')}/api/tags", timeout=5)


def _has_model(tags: dict[str, Any], name: str) -> bool:
    target = name.lower()
    for m in tags.get("models") or []:
        if (m.get("name") or "").lower().startswith(target):
            return True
    return False


def _pull_model(base_url: str, name: str) -> None:
    """Stream a model pull, printing progress lines to stderr."""
    url = f"{base_url.rstrip('/')}/api/pull"
    payload = {"model": name, "stream": True}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    sys.stderr.write(f"Pulling {name} from {base_url} (this can take a few minutes)…\n")
    with urllib.request.urlopen(req, timeout=600) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            status = obj.get("status", "")
            if status:
                sys.stderr.write(f"  {status}\n")
            if obj.get("error"):
                sys.stderr.write(f"  ERROR: {obj['error']}\n")
                raise RuntimeError(obj["error"])


def _smoke_test(base_url: str, model: str) -> str:
    """Send a 1×1 white pixel to confirm the model answers."""
    # A 1×1 white PNG, base64-encoded.
    one_pixel_png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAA"
        "DUlEQVR4nGP4//8/AwAI/AL+pf6QvgAAAABJRU5ErkJggg=="
    )
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": "Reply with the single word READY.",
                "images": [one_pixel_png_b64],
            },
        ],
        "stream": False,
        "options": {"temperature": 0.0},
    }
    body = _request_json(
        f"{base_url.rstrip('/')}/api/chat",
        data=payload,
        method="POST",
        timeout=60,
    )
    return ((body.get("message") or {}).get("content") or "").strip()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="setup_vision_ocr")
    p.add_argument(
        "--model",
        default=os.environ.get("PARSER_OS_OCR_OLLAMA_VISION_MODEL", "llava"),
        help="Ollama vision model to pull (default: llava)",
    )
    p.add_argument(
        "--base-url",
        default=os.environ.get(
            "PARSER_OS_OCR_OLLAMA_BASE_URL",
            os.environ.get("OLLAMA_BASE_URL", "http://100.114.102.122:11434"),
        ),
        help="Ollama host base URL",
    )
    args = p.parse_args(argv)

    sys.stderr.write(f"Checking Ollama host at {args.base_url}…\n")
    try:
        tags = _check_host(args.base_url)
    except Exception as exc:
        sys.stderr.write(f"  FAIL: {exc}\n")
        sys.stderr.write(
            "Ollama host is unreachable. Ensure the server is running and "
            "the base URL is correct (default targets the Mac Studio via "
            "Tailscale at http://100.114.102.122:11434).\n"
        )
        return 2
    sys.stderr.write(f"  Connected. {len(tags.get('models') or [])} models present.\n")

    if _has_model(tags, args.model):
        sys.stderr.write(f"  Model '{args.model}' already pulled.\n")
    else:
        try:
            _pull_model(args.base_url, args.model)
        except Exception as exc:
            sys.stderr.write(f"FAIL: pull failed — {exc}\n")
            return 3

    sys.stderr.write("Running smoke test…\n")
    try:
        reply = _smoke_test(args.base_url, args.model)
    except Exception as exc:
        sys.stderr.write(f"FAIL: smoke test failed — {exc}\n")
        return 4
    sys.stderr.write(f"  Model replied: {reply!r}\n")
    sys.stderr.write(
        f"\n✅ {args.model} is ready on {args.base_url}.\n"
        f"To use it for OCR in OrbitBrief / parser-os, set:\n"
        f"  PARSER_OS_OCR_OLLAMA_BASE_URL={args.base_url}\n"
        f"  PARSER_OS_OCR_OLLAMA_VISION_MODEL={args.model}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
