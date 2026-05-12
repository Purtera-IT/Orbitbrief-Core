"""Fixtures for validator tests.

The validator consumes a brain output (today: ManagedServicesScopeState)
plus a RetrievalBundle plus a BriefState plus an EvidenceLookup. The
fixtures here build a single coherent set with no LLM in the loop so
the test corpus is fast, deterministic, and easy to mutate.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from orbitbrief_core.brains._retrieval_bundle import (
    PacketSnippet,
    RetrievalBundle,
)
from orbitbrief_core.brains.managed_services.schema import (
    ManagedServicesScopeState,
)
from orbitbrief_core.validator.evidence_lookup import (
    DictEvidenceLookup,
)
from orbitbrief_core.world_model.planner.schema import BriefState


def _packet(
    pid: str,
    family: str,
    *,
    governing: tuple[str, ...] = (),
    supporting: tuple[str, ...] = (),
    contradicting: tuple[str, ...] = (),
    atom_text: dict[str, str] | None = None,
) -> PacketSnippet:
    return PacketSnippet(
        packet_id=pid,
        family=family,
        anchor_type="generic",
        anchor_key=family,
        status="active",
        confidence=0.9,
        governing_atom_ids=governing,
        supporting_atom_ids=supporting,
        contradicting_atom_ids=contradicting,
        atom_text=atom_text or {},
    )


@pytest.fixture
def small_bundle() -> RetrievalBundle:
    return RetrievalBundle(
        project_id="p1",
        compile_id="c1",
        packets_by_family={
            "scope_inclusion": (
                _packet("pkt_s1", "scope_inclusion", governing=("a1",), atom_text={"a1": "MSP scope item"}),
            ),
            "scope_exclusion": (
                _packet("pkt_x1", "scope_exclusion", governing=("a2",), atom_text={"a2": "Out of scope"}),
            ),
        },
    )


@pytest.fixture
def lookup_with_two_atoms() -> DictEvidenceLookup:
    return DictEvidenceLookup(
        atoms={
            "a1": {
                "id": "a1",
                "text": "MSP scope item",
                "verified": "verified",
                "locator": {"page": 5, "section": "Scope"},
            },
            "a2": {
                "id": "a2",
                "text": "Out of scope",
                "verified": "verified",
                "locator": {"page": 12, "section": "Exclusions"},
            },
        }
    )


@pytest.fixture
def small_brief() -> BriefState:
    return BriefState(
        project_id="p1",
        compile_id="c1",
        generated_at="2026-01-01T00:00:00Z",
        pack_activations=(
            {
                "pack_id": "msp",
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
        escalation_log={"metrics": {"pack_margin": 0.6}},
        token_cost={},
    )


def _build_state(payload: dict[str, Any]) -> ManagedServicesScopeState:
    """Build a state from a partial payload, defaulting unspecified sections to ``[]``."""
    base = {
        "project_id": "p1",
        "compile_id": "c1",
        "generated_at": "2026-01-01T00:00:00Z",
        "scope_items": [],
        "exclusions": [],
        "customer_responsibilities": [],
        "milestones": [],
        "assumptions": [],
        "dispatch_readiness_flags": [],
        "open_questions": [],
    }
    base.update(payload)
    return ManagedServicesScopeState.model_validate(base)


@pytest.fixture
def build_state():
    return _build_state
