"""Fixtures for Phase-5 brain tests.

The brains never touch the envelope or runtime — they read a typed
:class:`BriefState` and a typed :class:`RetrievalBundle`. The
fixtures here build both directly so brain tests stay fast and
don't pull the full evidence_runtime stack into scope.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable

import pytest

from orbitbrief_core.brains._retrieval_bundle import (
    PacketSnippet,
    RetrievalBundle,
)
from orbitbrief_core.inference.client import (
    ChatMessage,
    ChatResult,
    ChatUsage,
)
from orbitbrief_core.world_model.planner.schema import BriefState


@dataclass
class ScriptedChatClient:
    """Returns scripted text replies in order; records every call."""

    replies: list[str] = field(default_factory=list)
    call_log: list[dict[str, Any]] = field(default_factory=list)
    fixed_usage: ChatUsage = field(
        default_factory=lambda: ChatUsage(
            prompt_tokens=900,
            completion_tokens=400,
            total_tokens=1300,
            latency_ms=180,
        )
    )

    def _next(self) -> str:
        if not self.replies:
            return ""
        return self.replies.pop(0)

    def complete(self, messages, *, model, temperature=0.0, max_tokens=None, response_format=None):
        return self.complete_with_usage(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        ).text

    def complete_with_usage(
        self,
        messages,
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


# ────────────────────────────── helpers ────────────────────────────────


def _packet(
    pid: str,
    family: str,
    *,
    anchor_key: str = "",
    governing: Iterable[str] = (),
    supporting: Iterable[str] = (),
    contradicting: Iterable[str] = (),
    atom_text: dict[str, str] | None = None,
    confidence: float = 0.85,
) -> PacketSnippet:
    governing = tuple(governing)
    supporting = tuple(supporting)
    contradicting = tuple(contradicting)
    return PacketSnippet(
        packet_id=pid,
        family=family,
        anchor_type="generic",
        anchor_key=anchor_key,
        status="active",
        confidence=confidence,
        governing_atom_ids=governing,
        supporting_atom_ids=supporting,
        contradicting_atom_ids=contradicting,
        atom_text=atom_text or {},
    )


def _bundle(*packets: PacketSnippet, project_id: str = "p1", compile_id: str = "c1") -> RetrievalBundle:
    by_family: dict[str, list[PacketSnippet]] = {}
    for p in packets:
        by_family.setdefault(p.family, []).append(p)
    return RetrievalBundle(
        project_id=project_id,
        compile_id=compile_id,
        packets_by_family={f: tuple(ps) for f, ps in by_family.items()},
    )


def _brief(
    *,
    project_id: str = "p1",
    compile_id: str = "c1",
    pack_id: str = "msp",
) -> BriefState:
    """Minimal valid BriefState the brain accepts as input."""
    return BriefState(
        project_id=project_id,
        compile_id=compile_id,
        generated_at="2026-01-01T00:00:00Z",
        pack_activations=(
            {
                "pack_id": pack_id,
                "status": "active",
                "confidence": 0.9,
                "rationale": "msp keywords dense",
            },  # type: ignore[arg-type]
        ),
        sites=(),
        claims=(),
        contradictions=(),
        review_flags=(),
        orchestration=(),
        model_used="qwen3:14b",
        tier="default",
        escalation_log={},
        token_cost={},
    )


# ────────────────────────────── fixtures ───────────────────────────────


@pytest.fixture
def msp_brief() -> BriefState:
    return _brief()


@pytest.fixture
def msp_bundle() -> RetrievalBundle:
    """A small, realistic MSP-flavored bundle covering the main families."""
    return _bundle(
        _packet(
            "pkt_scope_1",
            "scope_inclusion",
            anchor_key="endpoint_monitoring",
            governing=("a_scope_1",),
            atom_text={"a_scope_1": "24x7 endpoint monitoring across 220 devices."},
        ),
        _packet(
            "pkt_scope_2",
            "scope_inclusion",
            anchor_key="patching",
            governing=("a_scope_2",),
            atom_text={"a_scope_2": "Monthly OS and third-party patching with reboot windows."},
        ),
        _packet(
            "pkt_excl_1",
            "scope_exclusion",
            anchor_key="hw_replacement",
            governing=("a_excl_1",),
            atom_text={
                "a_excl_1": "Hardware replacement and warranty management explicitly out of scope."
            },
        ),
        _packet(
            "pkt_cust_1",
            "customer_override",
            anchor_key="approver",
            governing=("a_cust_1",),
            atom_text={
                "a_cust_1": "Customer must designate change-approval contact within 5 business days of kickoff."
            },
        ),
        _packet(
            "pkt_meet_1",
            "meeting_decision",
            anchor_key="quarterly_review",
            governing=("a_meet_1",),
            atom_text={"a_meet_1": "Quarterly business review on the 3rd Thursday of each quarter."},
        ),
        _packet(
            "pkt_action_1",
            "action_item",
            anchor_key="cmdb_freeze",
            governing=("a_action_1",),
            atom_text={
                "a_action_1": "Customer to provide CMDB snapshot and freeze changes 1 week before cutover."
            },
        ),
        _packet(
            "pkt_site_1",
            "site_access",
            anchor_key="hq_dispatch",
            governing=("a_site_1",),
            atom_text={"a_site_1": "Onsite dispatch needs prior badge approval; 48-hour lead time."},
        ),
        _packet(
            "pkt_missing_1",
            "missing_info",
            anchor_key="third_party_apps",
            governing=("a_missing_1",),
            atom_text={"a_missing_1": "List of third-party apps to patch is not enumerated."},
        ),
        _packet(
            "pkt_compl_1",
            "compliance_clause",
            anchor_key="hipaa",
            governing=("a_compl_1",),
            atom_text={"a_compl_1": "All endpoint logs must satisfy HIPAA retention (6 years)."},
        ),
        _packet(
            "pkt_qty_1",
            "quantity_claim",
            anchor_key="device_count",
            governing=("a_qty_1",),
            atom_text={"a_qty_1": "Approximately 220 in-scope endpoints across HQ and 3 satellites."},
        ),
        _packet(
            "pkt_qconf_1",
            "quantity_conflict",
            anchor_key="device_count_conflict",
            governing=("a_qconf_1a", "a_qconf_1b"),
            contradicting=("a_qconf_1a", "a_qconf_1b"),
            atom_text={
                "a_qconf_1a": "RFP page 5: 220 endpoints.",
                "a_qconf_1b": "Asset spreadsheet: 248 endpoints.",
            },
        ),
        _packet(
            "pkt_vendor_1",
            "vendor_mismatch",
            anchor_key="rmm_tool",
            governing=("a_vendor_1",),
            atom_text={
                "a_vendor_1": "RFP requires Datto RMM; vendor proposal lists ConnectWise Automate."
            },
        ),
    )


@pytest.fixture
def valid_brain_payload(msp_brief, msp_bundle):
    """A round-trippable JSON payload for the brain."""

    def _build() -> str:
        return json.dumps(
            {
                "project_id": msp_brief.project_id,
                "compile_id": msp_brief.compile_id,
                "generated_at": "2026-01-01T00:00:00Z",
                "scope_items": [
                    {
                        "id": "scope_001",
                        "statement": "24x7 endpoint monitoring across approximately 220 devices.",
                        "supporting_packet_ids": ["pkt_scope_1", "pkt_qty_1"],
                        "supporting_atom_ids": ["a_scope_1", "a_qty_1"],
                        "confidence": 0.9,
                        "category": "monitoring",
                    },
                    {
                        "id": "scope_002",
                        "statement": "Monthly OS and third-party patching with documented reboot windows.",
                        "supporting_packet_ids": ["pkt_scope_2"],
                        "supporting_atom_ids": ["a_scope_2"],
                        "confidence": 0.85,
                        "category": "patching",
                    },
                ],
                "exclusions": [
                    {
                        "id": "excl_001",
                        "statement": "Hardware replacement and warranty handling.",
                        "supporting_packet_ids": ["pkt_excl_1"],
                        "supporting_atom_ids": ["a_excl_1"],
                        "confidence": 0.95,
                        "rationale": "Scope explicitly excludes hardware replacement.",
                    }
                ],
                "customer_responsibilities": [
                    {
                        "id": "cust_001",
                        "statement": "Designate a change-approval contact within 5 business days.",
                        "supporting_packet_ids": ["pkt_cust_1"],
                        "supporting_atom_ids": ["a_cust_1"],
                        "confidence": 0.9,
                        "deadline_relative": "T+5 business days from kickoff",
                    },
                    {
                        "id": "cust_002",
                        "statement": "Freeze CMDB changes 1 week before cutover.",
                        "supporting_packet_ids": ["pkt_action_1"],
                        "supporting_atom_ids": ["a_action_1"],
                        "confidence": 0.85,
                        "deadline_relative": "T-7 days before cutover",
                    },
                ],
                "milestones": [
                    {
                        "id": "ms_001",
                        "statement": "Quarterly business review on 3rd Thursday of each quarter.",
                        "supporting_packet_ids": ["pkt_meet_1"],
                        "supporting_atom_ids": ["a_meet_1"],
                        "confidence": 0.9,
                        "status": "scheduled",
                        "target_relative": "Quarterly, 3rd Thursday",
                    }
                ],
                "assumptions": [
                    {
                        "id": "as_001",
                        "statement": "All endpoint logs satisfy HIPAA retention (6 years).",
                        "supporting_packet_ids": ["pkt_compl_1"],
                        "supporting_atom_ids": ["a_compl_1"],
                        "confidence": 0.8,
                        "risk_if_false": "Compliance gap — logs purged before 6 years invalidates audit.",
                    }
                ],
                "dispatch_readiness_flags": [
                    {
                        "id": "rf_001",
                        "statement": "Onsite dispatch requires badge approval with 48-hour lead time.",
                        "supporting_packet_ids": ["pkt_site_1"],
                        "supporting_atom_ids": ["a_site_1"],
                        "confidence": 0.9,
                        "severity": "yellow",
                        "blocker_owner": "customer_security_lead",
                    },
                    {
                        "id": "rf_002",
                        "statement": "RMM tool conflict: RFP requires Datto, proposal cites ConnectWise.",
                        "supporting_packet_ids": ["pkt_vendor_1"],
                        "supporting_atom_ids": ["a_vendor_1"],
                        "confidence": 0.9,
                        "severity": "red",
                        "blocker_owner": "vendor_pm",
                    },
                ],
                "open_questions": [
                    {
                        "id": "oq_001",
                        "statement": "Device count discrepancy: RFP says 220, asset list says 248.",
                        "supporting_packet_ids": ["pkt_qconf_1"],
                        "supporting_atom_ids": ["a_qconf_1a", "a_qconf_1b"],
                        "confidence": 0.95,
                        "addressee": "customer",
                    },
                    {
                        "id": "oq_002",
                        "statement": "Third-party app patch list not enumerated.",
                        "supporting_packet_ids": ["pkt_missing_1"],
                        "supporting_atom_ids": ["a_missing_1"],
                        "confidence": 0.9,
                        "addressee": "customer",
                    },
                ],
            }
        )

    return _build
