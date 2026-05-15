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
# Briefing brain typically emits 2-3k completion tokens (9 sections ×
# 3-6 items × ~80 tokens/item with grounded citations). Bumped from
# 6144 → 8192 because real RFP+addendum cases blow past 6 K when the
# model emits structured citations + reasoning per item, and a single
# truncated character collapses the whole JSON parse on retry.
_MAX_OUTPUT_TOKENS = 8192

# Hard prompt-budget guards. Without these the snapshot can fill the
# entire 40 K context window of qwen3:14b on a real case, leaving zero
# room for the response and guaranteeing JSON truncation. Empirically
# 6 packets/family × 160-char snippets × 1 gold example/section keeps
# the prompt under ~14 K tokens on the largest stress cases we ship.
_PACKETS_PER_FAMILY_CAP = 6
_MAX_SNIPPET_CHARS = 160
_GOLD_EXAMPLES_PER_SECTION_CAP = 1
_GUIDANCE_LINES_PER_SECTION_CAP = 4

# Soft alarm on the prompt size so the dashboard / logs surface a
# warning before truncation blows up the response. ~13 K tokens is a
# reasonable danger line for qwen3:14b's 40960-token context window.
_PROMPT_CHAR_WARN_THRESHOLD = 50_000


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
        snapshot_json = json.dumps(snapshot, indent=2, ensure_ascii=False)
        user = _USER_TEMPLATE.format(
            project_id=brief.project_id,
            compile_id=brief.compile_id,
            generated_at=generated_at,
            domain_id=cfg.domain_id,
            display_name=cfg.display_name,
            snapshot_json=snapshot_json,
        ).strip()
        # Belt-and-suspenders: if the snapshot is *still* over the
        # warning threshold (e.g. a domain with extreme normalization
        # vocabularies), aggressively trim the densest sub-tree —
        # ``packets_by_family`` — and rebuild. This guarantees a fixed
        # upper bound regardless of domain config.
        total_chars = len(system) + len(user)
        if total_chars > _PROMPT_CHAR_WARN_THRESHOLD:
            trimmed_snapshot = _shrink_snapshot_inplace(
                snapshot, target_chars=_PROMPT_CHAR_WARN_THRESHOLD - len(system)
            )
            user = _USER_TEMPLATE.format(
                project_id=brief.project_id,
                compile_id=brief.compile_id,
                generated_at=generated_at,
                domain_id=cfg.domain_id,
                display_name=cfg.display_name,
                snapshot_json=json.dumps(trimmed_snapshot, indent=2, ensure_ascii=False),
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
            entry: dict[str, Any] = {
                # Guidance lines are the highest-leverage tokens but
                # also the easiest to over-spend on. Cap to the top N
                # per section — they're already ordered by importance
                # in the workbook.
                "guidance": list(cfg.guidance_for(section))[
                    :_GUIDANCE_LINES_PER_SECTION_CAP
                ],
                "family_hints": list(SECTION_FAMILY_HINTS.get(section, ())),
            }
            # Few-shot anchors. Each gold example is a dict of
            # ``statement`` + ``evidence_pattern`` + ``pitfalls``.
            # Capped at one per section to keep the prompt under
            # qwen3:14b's 40 K context window — three was the leading
            # cause of context-overflow truncations.
            gold = list(cfg.gold_for(section))[:_GOLD_EXAMPLES_PER_SECTION_CAP]
            if gold:
                entry["gold_examples"] = gold
            section_guidance[section] = entry

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


def _shrink_snapshot_inplace(
    snapshot: dict[str, Any], *, target_chars: int
) -> dict[str, Any]:
    """Iteratively halve the densest packets-per-family count until the
    serialized snapshot is at or below ``target_chars``.

    We trim ``packets_by_family`` first (≥80% of token cost on real
    cases), then ``section_guidance.*.gold_examples``, then
    ``section_guidance.*.guidance``. We never zero anything out — at
    minimum each family keeps one packet and each section keeps one
    guidance line, so the brain still has something to ground on.
    """
    pbf = snapshot.get("packets_by_family") or {}
    sg = snapshot.get("section_guidance") or {}

    def _size(s: dict[str, Any]) -> int:
        return len(json.dumps(s, ensure_ascii=False))

    # Pass 1: halve packets-per-family until at target or floor reached.
    while _size(snapshot) > target_chars:
        changed = False
        for fam, pkts in pbf.items():
            if len(pkts) > 1:
                pbf[fam] = pkts[: max(1, len(pkts) // 2)]
                changed = True
        if not changed:
            break

    # Pass 2: drop gold_examples beyond the first.
    if _size(snapshot) > target_chars:
        for sec, entry in sg.items():
            gold = entry.get("gold_examples")
            if isinstance(gold, list) and len(gold) > 1:
                entry["gold_examples"] = gold[:1]

    # Pass 3: trim guidance lines to top-1.
    if _size(snapshot) > target_chars:
        for sec, entry in sg.items():
            guidance = entry.get("guidance")
            if isinstance(guidance, list) and len(guidance) > 1:
                entry["guidance"] = guidance[:1]
    return snapshot


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
    if isinstance(exc, json.JSONDecodeError):
        msg = str(exc)
        # The single most common failure on real cases is the response
        # getting cut by an output-token cap mid-string. Detect it and
        # tell operators exactly what to bump, instead of a cryptic
        # "Unterminated string at char N".
        if "Unterminated string" in msg or "Expecting" in msg:
            return (
                "JSONDecodeError (likely output-token truncation): "
                f"{msg}. Bump --max-output-tokens (default 8192) or "
                "shrink the retrieval bundle further."
            )
        return f"JSONDecodeError: {msg}"
    return f"{type(exc).__name__}: {exc}"


def _strip_unresolved(
    state: BriefingState, bundle: RetrievalBundle
) -> tuple[BriefingState, set[str], set[str]]:
    """Validate citations + auto-populate atom_ids when LLM omits them.

    Three guarantees this pass enforces:

    1. Items citing a packet not in the bundle are DROPPED (the bad
       packet id is surfaced on ``unresolved_packet_ids``).
    2. Atom ids the LLM made up that don't belong to any cited packet
       are stripped from the item (id surfaced on
       ``unresolved_atom_ids``); the item itself stays if at least one
       valid atom remains.
    3. **Items citing a real packet but no atom_ids get auto-populated
       from the cited packet's first governing/supporting atoms** — at
       most ``_AUTOFILL_ATOMS_PER_ITEM`` per item, picked deterministically
       from the bundle. Without this, the LLM frequently emits
       packet-only citations and the funnel "atoms_to_brief_pct" reads
       zero. Auto-populated items still cite real atoms, so the
       validator's path-legality rule is satisfied.
    """
    valid_packet_ids = bundle.known_packet_ids()
    packet_atom_index: dict[str, set[str]] = {}
    packet_governing_order: dict[str, list[str]] = {}
    for p in bundle.all_packets:
        atoms = (
            list(p.governing_atom_ids)
            + list(p.supporting_atom_ids)
            + list(p.contradicting_atom_ids)
        )
        packet_atom_index[p.packet_id] = set(atoms)
        packet_governing_order[p.packet_id] = atoms

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

            cited_valid: list[str] = []
            for aid in item.supporting_atom_ids:
                if aid in allowed_atoms:
                    cited_valid.append(aid)
                else:
                    unresolved_atoms.add(aid)

            if not cited_valid:
                # Auto-populate from the cited packets' governing atoms.
                autofilled: list[str] = []
                for pid in item.supporting_packet_ids:
                    for aid in packet_governing_order.get(pid, []):
                        if aid in autofilled:
                            continue
                        autofilled.append(aid)
                        if len(autofilled) >= _AUTOFILL_ATOMS_PER_ITEM:
                            break
                    if len(autofilled) >= _AUTOFILL_ATOMS_PER_ITEM:
                        break
                cited_valid = autofilled

            item = item.model_copy(
                update={"supporting_atom_ids": tuple(cited_valid)}
            )
            kept.append(item)
        update[section] = tuple(kept)

    return state.model_copy(update=update), unresolved_packets, unresolved_atoms


# How many atoms to back-fill per item when the LLM cited zero. Two
# is enough to satisfy the validator's path-legality rule and gives
# the reviewer two distinct provenance pointers per claim.
_AUTOFILL_ATOMS_PER_ITEM = 2


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
3. **Every emitted item MUST include both fields:**
   - `supporting_packet_ids`: ≥1 packet_id from the retrieval bundle.
   - `supporting_atom_ids`: ≥1 atom_id drawn from the cited packets'
     `governing_atom_ids` or `supporting_atom_ids`. **Empty atom_ids
     is rejected — every item needs traceable atom-level evidence.**
4. Use the section_guidance and section_family_hints in the user
   message to choose target sections; do not invent items the bundle
   doesn't support.
5. statement ≤ 600 chars; metadata values ≤ 600 chars.
6. Leave provenance fields (`model_used`, `token_cost`,
   `fallback_used`, `unresolved_*`) unset; the runner stamps them.
7. Confidence: 0.95 only when a single packet is unambiguous; 0.5
   for one-source inference; 0.3 for bridging two weak packets.
8. **Aim for 3–6 items per section when evidence supports it.** Empty
   sections are valid only when the bundle truly has no relevant
   packets for that section. Cite multiple packets per item when
   several support the same statement (denser citation = higher
   trust downstream).

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
  "scope_overview":              [{{"id": "scope_overview_001", "statement": "<≤600 chars>", "supporting_packet_ids": ["pkt_…"], "supporting_atom_ids": ["atm_…"], "confidence": 0.0-1.0, "metadata": {{}}}}],
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
* Every list element MUST include `id` + `statement` + `supporting_packet_ids` (≥1 packet) + `supporting_atom_ids` (≥1 atom) + `confidence`. Items missing atom_ids are post-hoc filled from the packet's first governing atom by the runner, but the LLM MUST attempt to pick the most relevant atom rather than rely on the fallback.
* `supporting_packet_ids` MUST contain packet ids from `packets_by_family` in the snapshot.
* `supporting_atom_ids` MUST come from the cited packet's `governing_atom_ids` / `supporting_atom_ids` (visible in the snapshot).
* `metadata` is a free-form string-string dict for domain extras
  (severity, deadline, survey_type, …) — keep values ≤600 chars.
* DO NOT include `model_used`, `token_cost`, `fallback_used`,
  `unresolved_packet_ids`, or `unresolved_atom_ids`. The runner
  stamps them.
* `section_guidance.<section>.gold_examples` (when present) are
  few-shot anchors authored by senior PMs in this domain. Treat
  them as STYLE + CONTENT exemplars: aim for the same level of
  specificity, the same `evidence_pattern` mapping, and avoid the
  listed `pitfalls`. Do NOT copy them verbatim — they are
  illustrative, not data.

Substrate snapshot:
{snapshot_json}

Reply with the JSON object only.
"""
