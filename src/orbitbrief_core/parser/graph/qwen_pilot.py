from __future__ import annotations

import importlib
import os
from typing import Any, Callable

from orbitbrief_core.parser.graph.neural_hooks import GraphNeuralHooks
from orbitbrief_core.parser.graph.scorers.packet_seed import PacketSeedScoringService
from orbitbrief_core.parser.graph.scorers.same_topic import SameTopicScoringService
from orbitbrief_core.parser.graph.scorers.support import SupportScoringService


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str | None, default: int, *, minimum: int = 1) -> int:
    try:
        parsed = int(str(value).strip())
    except Exception:
        return default
    return max(minimum, parsed)


def _load_backend(dotted_path: str | None) -> Callable[[Any], float | None] | None:
    path = str(dotted_path or "").strip()
    if not path:
        return None
    module_name, _, attr = path.partition(":")
    if not module_name or not attr:
        return None
    try:
        module = importlib.import_module(module_name)
        backend = getattr(module, attr)
    except Exception:
        return None
    return backend if callable(backend) else None


def build_qwen_graph_hooks_from_env() -> GraphNeuralHooks | None:
    if not _enabled(os.getenv("ORBITBRIEF_ENABLE_QWEN_SCORERS")):
        return None
    same_topic_backend = _load_backend(os.getenv("ORBITBRIEF_QWEN_SAME_TOPIC_BACKEND"))
    support_backend = _load_backend(os.getenv("ORBITBRIEF_QWEN_SUPPORT_BACKEND"))
    packet_seed_backend = _load_backend(os.getenv("ORBITBRIEF_QWEN_PACKET_SEED_BACKEND"))
    timeout_ms = _int(os.getenv("ORBITBRIEF_QWEN_SCORER_TIMEOUT_MS"), 350, minimum=50)
    max_context_chars = _int(os.getenv("ORBITBRIEF_QWEN_SCORER_MAX_CONTEXT_CHARS"), 640, minimum=64)
    return GraphNeuralHooks(
        same_topic_scorer=SameTopicScoringService(
            model_name="qwen:same_topic",
            backend=same_topic_backend,
            enabled=_enabled(os.getenv("ORBITBRIEF_QWEN_SAME_TOPIC_ENABLED", "1")),
            timeout_ms=timeout_ms,
            max_context_chars=max_context_chars,
        ),
        support_scorer=SupportScoringService(
            model_name="qwen:support",
            backend=support_backend,
            enabled=_enabled(os.getenv("ORBITBRIEF_QWEN_SUPPORT_ENABLED", "1")),
            timeout_ms=timeout_ms,
            max_context_chars=max_context_chars,
        ),
        packet_seed_scorer=PacketSeedScoringService(
            model_name="qwen:packet_seed",
            backend=packet_seed_backend,
            enabled=_enabled(os.getenv("ORBITBRIEF_QWEN_PACKET_SEED_ENABLED", "1")),
            timeout_ms=timeout_ms,
            max_context_chars=max_context_chars,
        ),
    )
