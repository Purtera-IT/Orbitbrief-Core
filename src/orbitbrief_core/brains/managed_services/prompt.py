"""Prompt builder for :class:`ManagedServicesBrain`.

The brain receives:

* The planner's :class:`BriefState` — for orientation (sites,
  pack activations, contradictions, overall directives).
* A :class:`RetrievalBundle` — packets the orchestrator deemed
  relevant to managed-services scope.

We pre-organize the bundle by packet family and inline templated
hints so the model knows which sections each family typically
maps to:

============================== ================================
parser-os PacketFamily         managed-services target section
============================== ================================
``scope_inclusion``            ``scope_items``
``scope_exclusion``            ``exclusions``
``customer_override``          ``customer_responsibilities``
``meeting_decision``           ``milestones`` / ``assumptions``
``action_item``                ``customer_responsibilities`` /
                               ``open_questions``
``site_access``                ``dispatch_readiness_flags``
``missing_info``               ``open_questions``
``compliance_clause``          ``assumptions``
``quantity_claim``             ``scope_items`` (with quantity)
``quantity_conflict``          ``open_questions`` (severity high)
``vendor_mismatch``            ``open_questions`` /
                               ``dispatch_readiness_flags``
============================== ================================

Two hard rules in the system prompt:

1. Output JSON only, conforming to the schema described in the
   user message.
2. Every emitted item MUST cite a ``packet_id`` from the bundle
   in ``supporting_packet_ids``. Atom ids cited in
   ``supporting_atom_ids`` MUST appear in that packet's
   ``governing_atom_ids`` or ``supporting_atom_ids``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from orbitbrief_core.brains._retrieval_bundle import (
    PacketSnippet,
    RetrievalBundle,
)
from orbitbrief_core.inference.client import ChatMessage
from orbitbrief_core.world_model.planner.schema import BriefState


# How many packets per family to ship in the prompt. Most
# families produce a handful of packets per engagement; we cap to
# avoid prompt bloat.
_PACKETS_PER_FAMILY_CAP = 12
# Atom-text snippets are pre-trimmed by the orchestrator; we cap
# again here as a defense.
_MAX_SNIPPET_CHARS = 240


# Family → list of target sections (used in the prompt's hint table).
FAMILY_SECTION_HINTS: dict[str, tuple[str, ...]] = {
    "scope_inclusion": ("scope_items",),
    "scope_exclusion": ("exclusions",),
    "customer_override": ("customer_responsibilities",),
    "meeting_decision": ("milestones", "assumptions"),
    "action_item": ("customer_responsibilities", "open_questions"),
    "site_access": ("dispatch_readiness_flags",),
    "missing_info": ("open_questions",),
    "compliance_clause": ("assumptions",),
    "quantity_claim": ("scope_items",),
    "quantity_conflict": ("open_questions",),
    "vendor_mismatch": ("open_questions", "dispatch_readiness_flags"),
}


@dataclass(frozen=True)
class BrainPromptInputs:
    """Everything the prompt builder needs."""

    brief: BriefState
    bundle: RetrievalBundle
    generated_at: str


@dataclass(frozen=True)
class BrainPrompt:
    """The (system, user) message pair plus a debug snapshot."""

    system: str
    user: str
    snapshot: dict[str, Any]

    def messages(self) -> list[ChatMessage]:
        return [
            ChatMessage("system", self.system),
            ChatMessage("user", self.user),
        ]


def build_prompt(inputs: BrainPromptInputs) -> BrainPrompt:
    """Assemble (system, user) for the managed-services brain."""
    snapshot = _build_snapshot(inputs)
    user = _USER_TEMPLATE.format(
        project_id=inputs.brief.project_id,
        compile_id=inputs.brief.compile_id,
        generated_at=inputs.generated_at,
        snapshot_json=json.dumps(snapshot, indent=2, ensure_ascii=False),
    ).strip()
    return BrainPrompt(system=_SYSTEM.strip(), user=user, snapshot=snapshot)


def _build_snapshot(inputs: BrainPromptInputs) -> dict[str, Any]:
    brief = inputs.brief
    bundle = inputs.bundle

    brief_summary = {
        "project_id": brief.project_id,
        "compile_id": brief.compile_id,
        "model_used": brief.model_used,
        "tier": brief.tier,
        "active_pack_ids": [
            pa.pack_id for pa in brief.pack_activations if pa.status.value == "active"
        ],
        "pack_activations": [
            {
                "pack_id": pa.pack_id,
                "status": pa.status.value,
                "confidence": round(pa.confidence, 3),
            }
            for pa in brief.pack_activations[:8]
        ],
        "sites": [
            {
                "cluster_id": s.cluster_id,
                "canonical_name": s.canonical_name,
                "role": s.role.value,
            }
            for s in brief.sites[:8]
        ],
        "contradictions": [
            {
                "edge_id": c.edge_id,
                "severity": c.severity.value,
                "summary": c.summary,
            }
            for c in brief.contradictions[:8]
        ],
        "review_flags": [
            {
                "severity": f.severity.value,
                "category": f.category.value,
                "message": f.message,
            }
            for f in brief.review_flags[:8]
        ],
    }

    packets_by_family: dict[str, list[dict[str, Any]]] = {}
    for family in sorted(bundle.packets_by_family):
        kept = []
        for p in bundle.packets_by_family[family][:_PACKETS_PER_FAMILY_CAP]:
            kept.append(_packet_view(p))
        packets_by_family[family] = kept

    family_hints = {
        family: list(FAMILY_SECTION_HINTS.get(family, ()))
        for family in packets_by_family
    }

    return {
        "brief": brief_summary,
        "family_to_section_hints": family_hints,
        "packets_by_family": packets_by_family,
    }


def _packet_view(p: PacketSnippet) -> dict[str, Any]:
    """Compact dict view of a packet for prompt inclusion."""
    return {
        "packet_id": p.packet_id,
        "family": p.family,
        "anchor_type": p.anchor_type,
        "anchor_key": p.anchor_key,
        "status": p.status,
        "confidence": round(p.confidence, 3),
        "governing_atom_ids": list(p.governing_atom_ids),
        "supporting_atom_ids": list(p.supporting_atom_ids),
        "contradicting_atom_ids": list(p.contradicting_atom_ids),
        "atom_text": {
            aid: (text or "")[:_MAX_SNIPPET_CHARS]
            for aid, text in (p.atom_text or {}).items()
        },
    }


_SYSTEM = """/no_think
You are the OrbitBrief Managed Services brain. You produce a single
JSON ManagedServicesScopeState that a project manager will review.
You DO NOT write prose, Markdown, code fences, or commentary.

Hard rules:
1. Output a single JSON object that conforms to the schema described
   in the user message. No leading or trailing whitespace.
2. Every emitted item (scope_items, exclusions, customer_responsibilities,
   milestones, assumptions, dispatch_readiness_flags, open_questions)
   MUST include `supporting_packet_ids` with at least one packet_id from
   the supplied retrieval bundle.
3. `supporting_atom_ids` (when present) MUST appear in the cited
   packet's governing_atom_ids or supporting_atom_ids.
4. Use the family_to_section_hints to choose target sections; do not
   invent items unsupported by the bundle.
5. dispatch_readiness_flags severity:
   - `red`   = blocker; cannot dispatch (missing badging, blocked site
                  access, contradicted scope at the dispatchable site).
   - `yellow` = caveat the PM must know (unresolved access window,
                  vendor mismatch on a single site, ambiguous scope).
   - `green`  = explicit positive readiness signal (badged, scheduled).
6. Length caps (validator-enforced):
   - statement ≤ 500 chars
   - rationale / risk_if_false / message ≤ 400 chars
   - category / target_relative / addressee ≤ 80–120 chars
7. Leave provenance fields (`model_used`, `token_cost`,
   `fallback_used`, `unresolved_*`) unset; the runner stamps them.

Reasoning: temperature=0. Cite conservatively — confidence 0.95 only
when a single packet is unambiguous; 0.5 for one-source inference;
0.3 for bridging inference between two weak packets.
"""


_USER_TEMPLATE = """
Project: {project_id}
Compile: {compile_id}
Generated at: {generated_at}

Below is the BriefState summary plus the retrieval bundle, organized
by parser-os PacketFamily. Synthesize a ManagedServicesScopeState
JSON object using ONLY this evidence.

Required top-level keys:
  project_id, compile_id, generated_at,
  scope_items, exclusions, customer_responsibilities, milestones,
  assumptions, dispatch_readiness_flags, open_questions

Substrate snapshot:
{snapshot_json}

Reply with the JSON object only.
"""
