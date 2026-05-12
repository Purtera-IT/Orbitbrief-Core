"""Shared runner for every Phase-7.5 briefing brain.

Each domain brain (``brains.wireless``, ``brains.low_voltage_cabling``,
``brains.rack_and_stack``, ``brains.datacenter``, ``brains.imac``) is
a thin :class:`BriefingBrain` instance that loads its
:class:`DomainBriefingConfig` and delegates the heavy lifting here:

1. Build a config-driven (system, user) prompt that names the
   nine canonical sections, embeds the workbook's operating rules,
   inlines any normalization vocabularies the domain ships, and
   pre-arranges the bundle by packet-family hint.
2. Call the chat client with ``response_format={"type": "json_object"}``.
3. Validate against :class:`BriefingState`. Retry once on
   parse/validation failure with the error fed back. Hard-fall to
   a deterministic skeleton on a second failure.
4. Post-call validator strips items citing packets not in the
   bundle (``unresolved_packet_ids``) and atom_ids not in the
   cited packets (``unresolved_atom_ids``). Stripped ids are
   surfaced on the state for the trust layer.
5. Stamp ``model_used`` / ``token_cost`` / ``fallback_used``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from orbitbrief_core.brains._briefing import (
    CANONICAL_SECTIONS,
    BriefingItem,
    BriefingState,
)
from orbitbrief_core.brains._briefing_config import DomainBriefingConfig
from orbitbrief_core.brains._retrieval_bundle import (
    PacketSnippet,
    RetrievalBundle,
)
from orbitbrief_core.inference.client import (
    ChatClient,
    ChatMessage,
    ChatUsage,
    InferenceError,
)
from orbitbrief_core.world_model.planner.schema import BriefState


_DEFAULT_MODEL = "qwen3:14b"
# 9 grounded sections × ~10 items × ~120 tokens/item = ~10k upper bound.
# 8192 covers the typical engagement comfortably; the ``/no_think``
# directive in the system prompt eliminates the worst Qwen3 thinking
# overhead.
_MAX_OUTPUT_TOKENS = 8192


# Per-section parser-os PacketFamily hints. Same family can hint
# at multiple sections; the prompt routes the model with these hints.
SECTION_FAMILY_HINTS: dict[str, tuple[str, ...]] = {
    "scope_overview": ("scope_inclusion",),
    "detailed_scope_of_services": ("scope_inclusion", "quantity_claim"),
    "deliverables": ("scope_inclusion", "meeting_decision"),
    "assumptions": ("compliance_clause", "meeting_decision"),
    "customer_responsibilities": ("customer_override", "action_item"),
    "out_of_scope": ("scope_exclusion",),
    "risks_or_dependencies": ("vendor_mismatch", "site_access", "missing_info"),
    "completion_criteria": ("meeting_decision", "scope_inclusion"),
    "open_items": ("missing_info", "quantity_conflict", "vendor_mismatch"),
}

_PACKETS_PER_FAMILY_CAP = 12
_MAX_SNIPPET_CHARS = 240


@dataclass
class BriefingBrainResult:
    """Runner return: state + prompt + cost + raw + validation footprints."""

    state: BriefingState
    prompt_system: str
    prompt_user: str
    usage: ChatUsage
    raw_response: str = ""
    fallback_used: bool = False
    validation_errors: tuple[str, ...] = ()
    unresolved_packet_ids: tuple[str, ...] = ()
    unresolved_atom_ids: tuple[str, ...] = ()


@dataclass
class BriefingBrain:
    """One concrete briefing brain. Stateless aside from configuration."""

    domain_id: str
    config: DomainBriefingConfig
    chat_client: ChatClient
    model: str = _DEFAULT_MODEL
    max_output_tokens: int = _MAX_OUTPUT_TOKENS
    max_retries: int = 1

    def compose(
        self, brief: BriefState, bundle: RetrievalBundle
    ) -> BriefingBrainResult:
        if brief.project_id != bundle.project_id or brief.compile_id != bundle.compile_id:
            raise ValueError(
                f"brief/bundle mismatch: brief=({brief.project_id},{brief.compile_id}) "
                f"bundle=({bundle.project_id},{bundle.compile_id})"
            )

        generated_at = _now_iso()
        system, user = self._build_prompt(brief, bundle, generated_at)
        state, usage, raw, fallback, errors = self._run_with_retry(
            system=system,
            user=user,
            brief=brief,
            bundle=bundle,
            generated_at=generated_at,
        )
        cleaned, unresolved_packets, unresolved_atoms = _strip_unresolved(
            state, bundle
        )
        cleaned = cleaned.model_copy(
            update={
                "model_used": self.model,
                "token_cost": usage.to_dict(),
                "fallback_used": fallback,
                "unresolved_packet_ids": tuple(unresolved_packets),
                "unresolved_atom_ids": tuple(unresolved_atoms),
            }
        )
        return BriefingBrainResult(
            state=cleaned,
            prompt_system=system,
            prompt_user=user,
            usage=usage,
            raw_response=raw,
            fallback_used=fallback,
            validation_errors=errors,
            unresolved_packet_ids=tuple(unresolved_packets),
            unresolved_atom_ids=tuple(unresolved_atoms),
        )

    # ───── prompt construction ─────

    def _build_prompt(
        self,
        brief: BriefState,
        bundle: RetrievalBundle,
        generated_at: str,
    ) -> tuple[str, str]:
        cfg = self.config

        # System prompt: persona, hard rules, operating rules from the workbook.
        op_rules = "\n".join(cfg.operating_rules_lines) or "- (no domain operating rules; use defaults)"
        system = _SYSTEM_TEMPLATE.format(
            display_name=cfg.display_name,
            domain_id=cfg.domain_id,
            operating_rules=op_rules,
        ).strip()

        # User snapshot: brief summary, bundle by family, per-section guidance + family hints, normalization.
        snapshot = self._build_snapshot(brief, bundle, generated_at)
        user = _USER_TEMPLATE.format(
            project_id=brief.project_id,
            compile_id=brief.compile_id,
            generated_at=generated_at,
            domain_id=cfg.domain_id,
            display_name=cfg.display_name,
            snapshot_json=json.dumps(snapshot, indent=2, ensure_ascii=False),
        ).strip()
        return system, user

    def _build_snapshot(
        self,
        brief: BriefState,
        bundle: RetrievalBundle,
        generated_at: str,
    ) -> dict[str, Any]:
        cfg = self.config
        brief_summary = {
            "project_id": brief.project_id,
            "compile_id": brief.compile_id,
            "model_used": brief.model_used,
            "tier": brief.tier,
            "active_pack_ids": [
                pa.pack_id
                for pa in brief.pack_activations
                if pa.status.value == "active"
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
                for c in brief.contradictions[:6]
            ],
        }

        packets_by_family: dict[str, list[dict[str, Any]]] = {}
        for family in sorted(bundle.packets_by_family):
            kept = []
            for p in bundle.packets_by_family[family][:_PACKETS_PER_FAMILY_CAP]:
                kept.append(_packet_view(p))
            packets_by_family[family] = kept

        section_guidance: dict[str, dict[str, Any]] = {}
        for section in CANONICAL_SECTIONS:
            section_guidance[section] = {
                "guidance": list(cfg.guidance_for(section)),
                "family_hints": list(SECTION_FAMILY_HINTS.get(section, ())),
            }

        return {
            "brief": brief_summary,
            "domain": {
                "id": cfg.domain_id,
                "display_name": cfg.display_name,
                "subdomain_notes": list(cfg.subdomain_notes),
                "artifact_labels": list(cfg.artifact_labels),
            },
            "normalization": cfg.normalization_summary,
            "section_guidance": section_guidance,
            "packets_by_family": packets_by_family,
        }

    # ───── LLM call w/ retry ─────

    def _run_with_retry(
        self,
        *,
        system: str,
        user: str,
        brief: BriefState,
        bundle: RetrievalBundle,
        generated_at: str,
    ) -> tuple[BriefingState, ChatUsage, str, bool, tuple[str, ...]]:
        accumulated = ChatUsage()
        last_raw = ""
        last_errors: tuple[str, ...] = ()
        messages: list[ChatMessage] = [
            ChatMessage("system", system),
            ChatMessage("user", user),
        ]

        for attempt in range(self.max_retries + 1):
            try:
                result = self.chat_client.complete_with_usage(
                    messages,
                    model=self.model,
                    temperature=0.0,
                    max_tokens=self.max_output_tokens,
                    response_format={"type": "json_object"},
                )
            except InferenceError as exc:
                last_errors = (f"inference_error_attempt_{attempt}: {exc}",)
                break

            accumulated = accumulated.merged_with(result.usage)
            last_raw = result.text
            try:
                payload = _extract_json(result.text)
                payload.setdefault("project_id", brief.project_id)
                payload.setdefault("compile_id", brief.compile_id)
                payload.setdefault("generated_at", generated_at)
                payload.setdefault("domain_id", self.domain_id)
                state = BriefingState.model_validate(payload)
                return state, accumulated, last_raw, False, last_errors
            except (json.JSONDecodeError, ValidationError, KeyError) as exc:
                msg = _format_validation_failure(exc)
                last_errors = (msg,)
                if attempt < self.max_retries:
                    messages = messages + [
                        ChatMessage("assistant", result.text),
                        ChatMessage(
                            "user",
                            "Your previous response failed validation:\n"
                            f"{msg}\n"
                            "Reply ONLY with a corrected JSON object that "
                            "validates against the BriefingState schema.",
                        ),
                    ]
                    continue

        skeleton = _skeleton_state(
            brief=brief,
            generated_at=generated_at,
            domain_id=self.domain_id,
            errors=last_errors,
            bundle=bundle,
        )
        return skeleton, accumulated, last_raw, True, last_errors


# ────────────────────────────── helpers ────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _packet_view(p: PacketSnippet) -> dict[str, Any]:
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


def _extract_json(text: str) -> dict[str, Any]:
    """Same Qwen3-tolerant extractor used in planner + managed_services runner."""
    s = text
    if "</think>" in s:
        s = s.rsplit("</think>", 1)[1]
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
    start = s.find("{")
    if start < 0:
        raise json.JSONDecodeError("no JSON object found in LLM output", s, 0)
    depth = 0
    for i in range(start, len(s)):
        ch = s[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(s[start : i + 1])
    return json.loads(s[start:])


def _format_validation_failure(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
            for e in exc.errors()[:6]
        )
    return f"{type(exc).__name__}: {exc}"


def _strip_unresolved(
    state: BriefingState, bundle: RetrievalBundle
) -> tuple[BriefingState, set[str], set[str]]:
    """Drop items whose packet/atom citations don't resolve in ``bundle``."""
    valid_packet_ids = bundle.known_packet_ids()
    packet_atom_index: dict[str, set[str]] = {}
    for p in bundle.all_packets:
        packet_atom_index[p.packet_id] = (
            set(p.governing_atom_ids)
            | set(p.supporting_atom_ids)
            | set(p.contradicting_atom_ids)
        )

    unresolved_packets: set[str] = set()
    unresolved_atoms: set[str] = set()

    update: dict[str, tuple[Any, ...]] = {}
    for section in CANONICAL_SECTIONS:
        kept: list[BriefingItem] = []
        for item in getattr(state, section):
            unknown_pkts = [
                pid
                for pid in item.supporting_packet_ids
                if pid not in valid_packet_ids
            ]
            if unknown_pkts:
                unresolved_packets.update(unknown_pkts)
                continue
            allowed_atoms: set[str] = set()
            for pid in item.supporting_packet_ids:
                allowed_atoms |= packet_atom_index.get(pid, set())
            unknown_atoms = [
                aid for aid in item.supporting_atom_ids if aid not in allowed_atoms
            ]
            if unknown_atoms:
                unresolved_atoms.update(unknown_atoms)
                item = item.model_copy(
                    update={
                        "supporting_atom_ids": tuple(
                            aid
                            for aid in item.supporting_atom_ids
                            if aid in allowed_atoms
                        )
                    }
                )
            kept.append(item)
        update[section] = tuple(kept)

    return state.model_copy(update=update), unresolved_packets, unresolved_atoms


def _skeleton_state(
    *,
    brief: BriefState,
    generated_at: str,
    domain_id: str,
    errors: tuple[str, ...],
    bundle: RetrievalBundle,
) -> BriefingState:
    """Deterministic-only state when the LLM round-trip fails."""
    packets = bundle.all_packets
    pid = packets[0].packet_id if packets else "bundle:empty"
    placeholder = BriefingItem(
        id="open_q_fallback",
        statement=(
            f"{domain_id} brain LLM call failed schema validation; "
            "no scope state derived. Errors: "
            f"{' / '.join(errors)[:300]}"
        )[:600],
        supporting_packet_ids=(pid,),
        confidence=1.0,
        metadata={"addressee": "brain_admin"},
    )
    return BriefingState(
        project_id=brief.project_id,
        compile_id=brief.compile_id,
        generated_at=generated_at,
        domain_id=domain_id,
        open_items=(placeholder,),
    )


# ───── prompts ─────


_SYSTEM_TEMPLATE = """/no_think
You are the OrbitBrief {display_name} brain (domain id: {domain_id}).
You produce a single JSON BriefingState that a project manager will
review. You DO NOT write prose, Markdown, code fences, or commentary.

Hard rules:
1. Output a single JSON object that conforms to the schema described
   in the user message. No leading or trailing whitespace.
2. The nine top-level sections you may populate are:
   scope_overview, detailed_scope_of_services, deliverables,
   assumptions, customer_responsibilities, out_of_scope,
   risks_or_dependencies, completion_criteria, open_items.
3. Every emitted item MUST include `supporting_packet_ids` with at
   least one packet_id drawn from the supplied retrieval bundle.
4. `supporting_atom_ids` (when present) MUST appear in the cited
   packet's governing_atom_ids or supporting_atom_ids.
5. Use the section_guidance and section_family_hints in the user
   message to choose target sections; do not invent items the bundle
   doesn't support.
6. statement ≤ 600 chars; metadata values ≤ 600 chars.
7. Leave provenance fields (`model_used`, `token_cost`,
   `fallback_used`, `unresolved_*`) unset; the runner stamps them.
8. Confidence: 0.95 only when a single packet is unambiguous; 0.5
   for one-source inference; 0.3 for bridging two weak packets.

Domain operating rules (from the OrbitBrief intake workbook):
{operating_rules}
"""


_USER_TEMPLATE = """
Project: {project_id}
Compile: {compile_id}
Generated at: {generated_at}
Domain: {display_name}  ({domain_id})

Below is the BriefState summary plus the retrieval bundle organized
by parser-os PacketFamily, plus per-section guidance and family hints
mined from the OrbitBrief intake workbook. Synthesize a BriefingState
JSON object using ONLY this evidence.

EXACT JSON SHAPE (use these field names verbatim — extras are rejected):

```
{{
  "project_id": "<string>",
  "compile_id": "<string>",
  "generated_at": "<ISO-8601 timestamp>",
  "domain_id": "{domain_id}",
  "scope_overview":              [{{"id": "scope_overview_001", "statement": "<≤600 chars>", "supporting_packet_ids": ["pkt_…"], "supporting_atom_ids": ["a_…"], "confidence": 0.0-1.0, "metadata": {{}}}}],
  "detailed_scope_of_services":  [{{"id": "service_001", ...}}],
  "deliverables":                [],
  "assumptions":                 [],
  "customer_responsibilities":   [],
  "out_of_scope":                [],
  "risks_or_dependencies":       [],
  "completion_criteria":         [],
  "open_items":                  []
}}
```

Notes:
* Every list element MUST include `id` + `statement` + `supporting_packet_ids` (≥1 packet) + `confidence`.
* `supporting_packet_ids` MUST contain packet ids from `packets_by_family` in the snapshot.
* `supporting_atom_ids` MUST come from the cited packet's `governing_atom_ids` / `supporting_atom_ids`.
* `metadata` is a free-form string-string dict for domain extras
  (severity, deadline, survey_type, …) — keep values ≤600 chars.
* DO NOT include `model_used`, `token_cost`, `fallback_used`,
  `unresolved_packet_ids`, or `unresolved_atom_ids`. The runner
  stamps them.

Substrate snapshot:
{snapshot_json}

Reply with the JSON object only.
"""
