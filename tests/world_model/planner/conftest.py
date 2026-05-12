"""Fixtures for Phase-4 planner tests.

The planner takes substrate inputs (PackPriorState +
SiteRealityState + EvidenceRuntime) and a chat client. We stub
the chat client with a recorder so tests can drive its replies
deterministically. Only :file:`test_real_ollama_planner.py` uses
the live Ollama endpoint.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable

import pytest

from orbitbrief_core.evidence_runtime.runtime import EvidenceRuntime
from orbitbrief_core.inference.client import ChatMessage, ChatResult, ChatUsage
from orbitbrief_core.world_model.pack_prior import PackPrior
from orbitbrief_core.world_model.site_reality import SiteRealityEngine


@dataclass
class ScriptedChatClient:
    """Returns scripted text replies in order; records every call.

    Each ``reply`` is a string the client returns verbatim. After
    the script is exhausted the client returns ``""`` (empty), which
    will exercise the planner's fallback path.
    """

    replies: list[str] = field(default_factory=list)
    call_log: list[dict[str, Any]] = field(default_factory=list)
    fixed_usage: ChatUsage = field(
        default_factory=lambda: ChatUsage(
            prompt_tokens=400, completion_tokens=200, total_tokens=600, latency_ms=120
        )
    )

    def _next(self) -> str:
        if not self.replies:
            return ""
        return self.replies.pop(0)

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
        self.call_log.append(
            {
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": response_format,
                "n_messages": len(messages),
                "last_user": messages[-1].content[:200] if messages else "",
            }
        )
        return ChatResult(
            text=self._next(),
            model=model,
            usage=self.fixed_usage,
            raw={"choices": [{"message": {"content": ""}}]},
        )


def _valid_brief_payload(
    *,
    project_id: str,
    compile_id: str,
    pack_ids: Iterable[str],
    cluster_ids: Iterable[str],
    atom_ids: Iterable[str],
) -> dict[str, Any]:
    """Hand-built BriefState payload that round-trips through validation."""
    pack_list = list(pack_ids)
    cluster_list = list(cluster_ids)
    atom_list = list(atom_ids)
    return {
        "project_id": project_id,
        "compile_id": compile_id,
        "generated_at": "2026-01-01T00:00:00Z",
        "pack_activations": [
            {
                "pack_id": pid,
                "status": "active" if i == 0 else "watch",
                "confidence": 0.9 - (i * 0.1),
                "rationale": f"keyword evidence for {pid}",
            }
            for i, pid in enumerate(pack_list[:3])
        ],
        "sites": [
            {
                "cluster_id": cid,
                "canonical_name": f"site_{i}",
                "role": "primary" if i == 0 else "secondary",
                "confidence": 0.9,
                "depends_on_cluster_ids": [],
            }
            for i, cid in enumerate(cluster_list[:2])
        ],
        "claims": [
            {
                "id": f"claim_{i:03d}",
                "statement": f"claim about atom {aid}",
                "supporting_atom_ids": [aid],
                "supporting_packet_ids": [],
                "confidence": 0.8,
                "pack_id": pack_list[0] if pack_list else None,
            }
            for i, aid in enumerate(atom_list[:3])
        ],
        "contradictions": [],
        "review_flags": [],
        "orchestration": [
            {
                "action": "run_brain",
                "target": pack_list[0] if pack_list else "default_brain",
                "payload": {},
            }
        ],
        "model_used": "qwen3:14b",
        "tier": "default",
        "escalation_log": {},
        "token_cost": {},
    }


@pytest.fixture
def valid_brief_payload(wireless_envelope, runtime_from_envelope):
    """A factory: returns ``(envelope, payload_json_string)`` for a real envelope."""
    rt = runtime_from_envelope(wireless_envelope)
    env = rt.to_envelope_dict()
    atom_ids = [a["id"] for a in env["atoms"]]
    payload = _valid_brief_payload(
        project_id=env["project_id"],
        compile_id=env["compile_id"],
        pack_ids=("wireless", "low_voltage_cabling"),
        cluster_ids=(),
        atom_ids=atom_ids,
    )
    rt.close()
    return wireless_envelope, json.dumps(payload)


@pytest.fixture
def substrate_factory(runtime_from_envelope):
    """Factory: envelope dict → (runtime, pack_prior, site_reality)."""
    pp = PackPrior.with_default_registry(chat_client=None)
    sr = SiteRealityEngine(chat_client=None)

    def _build(env: dict[str, Any]) -> tuple[EvidenceRuntime, Any, Any]:
        rt = runtime_from_envelope(env)
        return rt, pp.compute(rt), sr.compute(rt)

    return _build
