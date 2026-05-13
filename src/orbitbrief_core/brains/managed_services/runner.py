"""Runner for :class:`ManagedServicesBrain`.

End-to-end:

1. Build the (system, user) prompt from BriefState + bundle.
2. Call the chat client with ``response_format={"type":"json_object"}``.
3. Validate the LLM's JSON against
   :class:`ManagedServicesScopeState`.
4. On parse / validation failure, retry once with the validation
   message fed back. Second failure → deterministic skeleton with
   a BLOCKER ``open_question`` so reviewers see the degradation.
5. Run a post-call validator that strips out items whose
   ``supporting_packet_ids`` aren't in the supplied bundle (or
   whose ``supporting_atom_ids`` aren't in the cited packets).
   Stripped ids are surfaced in ``unresolved_*`` for audit.
6. Stamp ``model_used`` / ``token_cost`` / ``fallback_used``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from orbitbrief_core.brains._retrieval_bundle import RetrievalBundle
from orbitbrief_core.brains.managed_services.prompt import (
    BrainPrompt,
    BrainPromptInputs,
    build_prompt,
)
from orbitbrief_core.brains.managed_services.schema import (
    ManagedServicesScopeState,
    OpenQuestion,
)
from orbitbrief_core.inference.client import (
    ChatClient,
    ChatMessage,
    ChatUsage,
    InferenceError,
)
from orbitbrief_core.world_model.planner.schema import BriefState


_DEFAULT_MODEL = "qwen3:14b"
_MAX_OUTPUT_TOKENS = 8192


@dataclass
class ManagedServicesBrainResult:
    """Runner return: state + prompt + cost + raw + validation footprints."""

    state: ManagedServicesScopeState
    prompt: BrainPrompt
    usage: ChatUsage
    raw_response: str = ""
    fallback_used: bool = False
    validation_errors: tuple[str, ...] = ()
    unresolved_packet_ids: tuple[str, ...] = ()
    unresolved_atom_ids: tuple[str, ...] = ()


@dataclass
class ManagedServicesBrain:
    """Stateless brain. One instance is safe to reuse across many briefs."""

    chat_client: ChatClient
    model: str = _DEFAULT_MODEL
    max_output_tokens: int = _MAX_OUTPUT_TOKENS
    max_retries: int = 1

    def compose(
        self,
        brief: BriefState,
        bundle: RetrievalBundle,
    ) -> ManagedServicesBrainResult:
        """Run the brain end-to-end."""
        if brief.project_id != bundle.project_id or brief.compile_id != bundle.compile_id:
            raise ValueError(
                f"brief/bundle mismatch: brief=({brief.project_id},{brief.compile_id}) "
                f"bundle=({bundle.project_id},{bundle.compile_id})"
            )
        generated_at = _now_iso()
        prompt = build_prompt(
            BrainPromptInputs(brief=brief, bundle=bundle, generated_at=generated_at)
        )

        state, usage, raw, fallback, errors = self._run_with_retry(
            prompt, brief=brief, bundle=bundle, generated_at=generated_at
        )
        # Post-call validator: drop anything that doesn't ground.
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
        return ManagedServicesBrainResult(
            state=cleaned,
            prompt=prompt,
            usage=usage,
            raw_response=raw,
            fallback_used=fallback,
            validation_errors=errors,
            unresolved_packet_ids=tuple(unresolved_packets),
            unresolved_atom_ids=tuple(unresolved_atoms),
        )

    def _run_with_retry(
        self,
        prompt: BrainPrompt,
        *,
        brief: BriefState,
        bundle: RetrievalBundle,
        generated_at: str,
    ) -> tuple[
        ManagedServicesScopeState, ChatUsage, str, bool, tuple[str, ...]
    ]:
        """Same retry-then-fallback shape as the planner runner."""
        accumulated = ChatUsage()
        last_raw = ""
        last_errors: tuple[str, ...] = ()
        messages = prompt.messages()

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
                # Stamp project/compile/generated_at the LLM cannot know.
                payload.setdefault("project_id", brief.project_id)
                payload.setdefault("compile_id", brief.compile_id)
                payload.setdefault("generated_at", generated_at)
                state = ManagedServicesScopeState.model_validate(payload)
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
                            "validates against the ManagedServicesScopeState schema.",
                        ),
                    ]
                    continue

        skeleton = _skeleton_state(
            brief=brief,
            generated_at=generated_at,
            errors=last_errors,
            bundle=bundle,
        )
        return skeleton, accumulated, last_raw, True, last_errors


# ────────────────────────────── helpers ────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _extract_json(text: str) -> dict[str, Any]:
    """Same Qwen3-tolerant extractor used in the planner runner."""
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


# Sections of :class:`ManagedServicesScopeState` that hold grounded items.
_GROUNDED_SECTIONS: tuple[str, ...] = (
    "scope_items",
    "exclusions",
    "customer_responsibilities",
    "milestones",
    "assumptions",
    "dispatch_readiness_flags",
    "open_questions",
)


def _strip_unresolved(
    state: ManagedServicesScopeState, bundle: RetrievalBundle
) -> tuple[ManagedServicesScopeState, set[str], set[str]]:
    """Validate citations + auto-populate atom_ids when the LLM omits them.

    Same shape as the briefing-runner variant — kept distinct because
    the managed_services schema has 7 sections rather than 9. Items
    citing a packet not in the bundle are dropped; atom_ids are
    auto-populated from the cited packets' first governing atoms when
    the LLM emitted only packet_ids (so the funnel always reflects
    real atom-level provenance).
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
    for section in _GROUNDED_SECTIONS:
        kept: list[Any] = []
        for item in getattr(state, section):
            unknown_pkts = [
                pid for pid in item.supporting_packet_ids if pid not in valid_packet_ids
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

    cleaned = state.model_copy(update=update)
    return cleaned, unresolved_packets, unresolved_atoms


_AUTOFILL_ATOMS_PER_ITEM = 2


def _skeleton_state(
    *,
    brief: BriefState,
    generated_at: str,
    errors: tuple[str, ...],
    bundle: RetrievalBundle,
) -> ManagedServicesScopeState:
    """Deterministic-only state when the LLM round-trip fails."""
    # Cite the first packet in the bundle so the skeleton's open question
    # still satisfies the schema's "≥1 supporting_packet_id" rule. If the
    # bundle is empty we synthesize a sentinel id; the post-call validator
    # will park it in ``unresolved_packet_ids`` for the reviewer.
    packets = bundle.all_packets
    pid = packets[0].packet_id if packets else "bundle:empty"
    placeholder = OpenQuestion(
        id="open_q_fallback",
        statement=(
            "Managed Services brain LLM call failed schema validation; "
            "no scope state derived. Errors: "
            f"{' / '.join(errors)[:300]}"
        )[:500],
        supporting_packet_ids=(pid,),
        confidence=1.0,
        addressee="brain_admin",
    )
    return ManagedServicesScopeState(
        project_id=brief.project_id,
        compile_id=brief.compile_id,
        generated_at=generated_at,
        open_questions=(placeholder,),
    )
