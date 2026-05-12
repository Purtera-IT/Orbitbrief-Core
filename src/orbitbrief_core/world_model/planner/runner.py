"""Planner runner: substrate → prompt → guided JSON → :class:`BriefState`.

End-to-end flow:

1. Take an :class:`EvidenceRuntime` plus the Phase-3 outputs
   (:class:`PackPriorState`, :class:`SiteRealityState`).
2. Pull contradictions from the runtime.
3. Rank atoms per active pack by keyword density and assemble a
   :class:`PlannerInputs` bundle.
4. Run :func:`decide_tier` to pick 14B vs 32B with structured
   reasons.
5. Build a :class:`PlannerPrompt` and call the chat client with
   ``response_format={"type": "json_object"}`` so the server
   constrains output to JSON.
6. Validate the JSON against :class:`BriefState`. On the first
   failure we retry once with the validation errors fed back to
   the LLM. On the second failure we emit a deterministic
   skeleton :class:`BriefState` (no claims) and flag the
   degradation in ``review_flags``.
7. Stamp provenance: ``model_used``, ``tier``,
   ``escalation_log``, ``token_cost``.

The :func:`refine_brief` pass (``world_model.refiner``) runs
*after* this and enforces graph-consistency invariants (drops
claims with unknown atoms, dedups, etc.).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from orbitbrief_core.evidence_runtime.contradictions import ContradictionPair
from orbitbrief_core.evidence_runtime.runtime import EvidenceRuntime, RuntimeKey
from orbitbrief_core.inference.client import (
    ChatClient,
    ChatMessage,
    ChatUsage,
    InferenceError,
)
from orbitbrief_core.world_model.pack_prior.state import PackPriorState
from orbitbrief_core.world_model.planner.escalation import (
    PlannerEscalation,
    PlannerTier,
    decide_tier,
)
from orbitbrief_core.world_model.planner.prompt import (
    PlannerInputs,
    PlannerPrompt,
    build_prompt,
)
from orbitbrief_core.world_model.planner.schema import (
    BriefState,
    OrchestrationDirective,
    PackActivation,
    PackStatus,
    ReviewFlag,
    ReviewFlagCategory,
    ReviewFlagSeverity,
    SiteRole,
    SiteSummary,
)
from orbitbrief_core.world_model.registry import (
    DomainPackRegistry,
    load_default_registry,
)


_DEFAULT_MODEL = "qwen3:14b"
_ESCALATED_MODEL = "qwen3:32b"
# JSON answers for BriefState are dense; allow plenty of headroom
# for Qwen3's <think> block. Adjust per your serving budget.
_MAX_OUTPUT_TOKENS = 4096
# Top-K active packs to include in the retrieval bundle.
_DEFAULT_ACTIVE_PACKS = 4
# Top-K atoms per pack in the retrieval bundle.
_DEFAULT_TOP_K_PER_PACK = 12


@dataclass
class PlannerResult:
    """What the planner returns: the state, the escalation verdict, and the raw prompt."""

    state: BriefState
    escalation: PlannerEscalation
    prompt: PlannerPrompt
    usage: ChatUsage
    raw_response: str = ""
    fallback_used: bool = False
    validation_errors: tuple[str, ...] = ()


@dataclass
class Planner:
    """Orchestrates the planner pipeline.

    Construction is cheap; the heavy work happens in :meth:`compose`.
    A single :class:`Planner` instance is safe to call against many
    runtimes serially.
    """

    chat_client: ChatClient
    registry: DomainPackRegistry = field(default_factory=load_default_registry)
    default_model: str = _DEFAULT_MODEL
    escalated_model: str = _ESCALATED_MODEL
    max_output_tokens: int = _MAX_OUTPUT_TOKENS
    top_k_active_packs: int = _DEFAULT_ACTIVE_PACKS
    top_k_atoms_per_pack: int = _DEFAULT_TOP_K_PER_PACK
    # Retry count for invalid JSON / validation errors before
    # falling back to the deterministic skeleton.
    max_retries: int = 1

    @classmethod
    def with_default_registry(cls, chat_client: ChatClient, **kwargs: Any) -> "Planner":
        return cls(chat_client=chat_client, **kwargs)

    def compose(
        self,
        runtime: EvidenceRuntime,
        *,
        pack_prior: PackPriorState,
        site_reality,
        key: RuntimeKey | None = None,
    ) -> PlannerResult:
        """Run the planner end-to-end and return a validated :class:`BriefState`."""
        rk = key or runtime.default_key
        if rk is None:
            raise ValueError("Planner.compose: runtime has no default key")
        envelope = runtime.to_envelope_dict(rk)

        # Contradictions (deterministic; planner does not invent).
        contradictions = self._collect_contradictions(runtime, rk)

        # Decide tier BEFORE generating the prompt so the model name
        # is baked into the snapshot for audit.
        escalation = decide_tier(
            pack_prior=pack_prior,
            site_reality=site_reality,
            envelope=envelope,
            contradiction_count=len(contradictions),
        )
        model = (
            self.escalated_model
            if escalation.tier is PlannerTier.ESCALATED
            else self.default_model
        )

        # Active packs — top-K from the prior, drop near-zero scores.
        active_packs = self._pick_active_packs(pack_prior)

        # Retrieval bundle — keyword-density ranked atoms per pack.
        bundles = self._build_retrieval_bundles(envelope, active_packs)

        inputs = PlannerInputs(
            project_id=rk.project_id,
            compile_id=rk.compile_id,
            generated_at=_now_iso(),
            pack_prior=pack_prior,
            site_reality=site_reality,
            contradictions=tuple(contradictions),
            retrieval_bundles=bundles,
            active_packs=tuple(active_packs),
        )
        prompt = build_prompt(inputs, top_k_per_pack=self.top_k_atoms_per_pack)

        state, usage, raw, fallback, errors = self._run_with_retry(
            prompt, model=model, escalation=escalation, inputs=inputs
        )
        return PlannerResult(
            state=state,
            escalation=escalation,
            prompt=prompt,
            usage=usage,
            raw_response=raw,
            fallback_used=fallback,
            validation_errors=errors,
        )

    # ───── stage helpers ─────

    def _collect_contradictions(
        self, runtime: EvidenceRuntime, rk: RuntimeKey
    ) -> list[ContradictionPair]:
        # Walk every entity key; for each, ask the runtime for
        # contradictions touching that key. De-dup on edge id so the
        # same edge isn't surfaced twice for both endpoints.
        envelope = runtime.to_envelope_dict(rk)
        seen: set[str] = set()
        out: list[ContradictionPair] = []
        for ent in envelope.get("entities") or ():
            ck = ent.get("canonical_key")
            if not ck:
                continue
            for c in runtime.contradictions_for(entity=ck, key=rk):
                eid = c.edge.get("id", "")
                if eid in seen:
                    continue
                seen.add(eid)
                out.append(c)
        return out

    def _pick_active_packs(self, pack_prior: PackPriorState):
        """Top-K active packs from the prior, dropping zero-confidence dust."""
        active = []
        for s in pack_prior.scores[: self.top_k_active_packs]:
            if s.confidence <= 0.0:
                continue
            pack = self.registry.get(s.pack_id)
            if pack is not None:
                active.append(pack)
        return active

    def _build_retrieval_bundles(
        self, envelope: dict[str, Any], active_packs
    ) -> dict[str, list[dict[str, Any]]]:
        """Rank atoms per pack by keyword density (deterministic, no vectors)."""
        atoms = envelope.get("atoms") or []
        bundles: dict[str, list[dict[str, Any]]] = {}
        for pack in active_packs:
            kw_set = set(pack.keywords) | set(pack.boosted_keywords)
            scored: list[tuple[int, dict[str, Any]]] = []
            for atom in atoms:
                text = (atom.get("text") or "").lower()
                if not text:
                    continue
                # Cheap density score: keyword hits + 3 × boost hits.
                hits = 0
                for w in kw_set:
                    if w in text:
                        hits += 3 if w in pack.boosted_keywords else 1
                if hits > 0:
                    scored.append((hits, atom))
            # Sort by density desc, then by atom id for stability.
            scored.sort(key=lambda kv: (-kv[0], kv[1].get("id", "")))
            bundles[pack.id] = [a for _, a in scored]
        return bundles

    def _run_with_retry(
        self,
        prompt: PlannerPrompt,
        *,
        model: str,
        escalation: PlannerEscalation,
        inputs: PlannerInputs,
    ) -> tuple[BriefState, ChatUsage, str, bool, tuple[str, ...]]:
        """Call LLM, validate, retry on error, fall back deterministically."""
        accumulated = ChatUsage()
        last_raw = ""
        last_errors: tuple[str, ...] = ()
        messages = prompt.messages()

        for attempt in range(self.max_retries + 1):
            try:
                result = self.chat_client.complete_with_usage(
                    messages,
                    model=model,
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
                # Stamp provenance fields the LLM cannot know.
                payload.setdefault("project_id", inputs.project_id)
                payload.setdefault("compile_id", inputs.compile_id)
                payload.setdefault("generated_at", inputs.generated_at)
                payload["model_used"] = model
                payload["tier"] = escalation.tier.value
                payload["escalation_log"] = escalation.to_dict()
                payload["token_cost"] = accumulated.to_dict()
                state = BriefState.model_validate(payload)
                return state, accumulated, last_raw, False, last_errors
            except (json.JSONDecodeError, ValidationError, KeyError) as exc:
                msg = _format_validation_failure(exc)
                last_errors = (msg,)
                if attempt < self.max_retries:
                    messages = messages + [
                        ChatMessage("assistant", result.text),
                        ChatMessage(
                            "user",
                            f"Your previous response failed validation:\n{msg}\n"
                            "Reply ONLY with a corrected JSON object that "
                            "validates against the BriefState schema.",
                        ),
                    ]
                    continue

        # Hard fallback — deterministic skeleton with no LLM-derived claims.
        skeleton = _skeleton_brief(
            inputs=inputs,
            escalation=escalation,
            model=model,
            usage=accumulated,
            errors=last_errors,
        )
        return skeleton, accumulated, last_raw, True, last_errors


# ────────────────────────────── helpers ────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _extract_json(text: str) -> dict[str, Any]:
    """Extract a JSON object from LLM output that may contain ``<think>`` blocks."""
    s = text
    if "</think>" in s:
        s = s.rsplit("</think>", 1)[1]
    s = s.strip()
    # Strip Markdown code fences if the model insisted on adding them.
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if s.endswith("```"):
            s = s[: -3]
        s = s.strip()
    # Find the first ``{`` and take the slice through the matching brace.
    start = s.find("{")
    if start < 0:
        raise json.JSONDecodeError("no JSON object found in LLM output", s, 0)
    # Brace counting (cheap and good enough for well-formed JSON).
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


def _skeleton_brief(
    *,
    inputs: PlannerInputs,
    escalation: PlannerEscalation,
    model: str,
    usage: ChatUsage,
    errors: tuple[str, ...],
) -> BriefState:
    """Build a deterministic-only :class:`BriefState` when the LLM fails.

    No claims (the planner cannot fabricate them); pack activations
    mirror the prior; sites are passed through. Reviewers see a
    blocker flag explaining the degradation.
    """
    activations = tuple(
        PackActivation(
            pack_id=s.pack_id,
            status=(
                PackStatus.ACTIVE
                if i == 0 and s.confidence > 0
                else PackStatus.WATCH if s.confidence > 0 else PackStatus.INACTIVE
            ),
            confidence=s.confidence,
            rationale=(
                f"deterministic fallback; keyword score={s.raw_score}, "
                f"matched={list(s.matched_keywords)[:5]}"
            )[:400],
        )
        for i, s in enumerate(inputs.pack_prior.scores[:8])
    )
    sites = tuple(
        SiteSummary(
            cluster_id=c.cluster_id,
            canonical_name=c.canonical_name or c.cluster_id,
            role=SiteRole.PRIMARY if i == 0 else SiteRole.SECONDARY,
            confidence=c.confidence,
        )
        for i, c in enumerate(inputs.site_reality.clusters[:32])
    )
    flag = ReviewFlag(
        severity=ReviewFlagSeverity.BLOCKER,
        category=ReviewFlagCategory.AMBIGUITY,
        message=(
            "Planner LLM call failed schema validation; emitted deterministic "
            f"skeleton with no claims. Errors: {' / '.join(errors)[:300]}"
        )[:400],
    )
    directive = OrchestrationDirective(
        action="request_review",
        target="planner_admin",
        payload={"errors": list(errors)},
    )
    return BriefState(
        project_id=inputs.project_id,
        compile_id=inputs.compile_id,
        generated_at=inputs.generated_at,
        pack_activations=activations,
        sites=sites,
        claims=(),
        contradictions=(),
        review_flags=(flag,),
        orchestration=(directive,),
        model_used=model,
        tier=escalation.tier.value,
        escalation_log={
            **escalation.to_dict(),
            "planner_fallback": True,
            "errors": list(errors),
        },
        token_cost=usage.to_dict(),
    )


