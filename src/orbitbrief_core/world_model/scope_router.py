"""Classify a deal's scope into its primary managed-service pack.

`service_routing.primary` decides `project_mode`, which decides which questions
the PM asks the customer, which gaps are shown, and which domains survive
filtering. Today it comes from a contrastive kNN head measured at **0.529
held-out** that failed its own eval gate. On Clayton it returned `wireless` for
a 437-store onsite dispatch job, and the PM was asked for an AP count, a channel
plan and a wireless design owner. There is no wireless design.

This is the same job the DeepSeek teacher already does well — every gold label
in ``_router_cache`` came from it, judged on scope of work rather than file
names, and it is right about Clayton (`staff_augmentation`). So ask a model.

**One decision, not a third voice.** The system already had two routers
disagreeing; adding another would repeat the mistake. This resolves a single
ladder and emits a single answer:

    LLM (reachable, confident)  ->  head (confident, not abstaining)  ->  {}

An empty result means "no opinion", and every existing keyword path downstream
behaves exactly as it does today. Nothing here can make routing worse than not
running at all.

Off unless a client is wired. Cache the result per compile: this is one call per
deal against a representation that excludes bill-of-material noise, not a call
per atom.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

log = logging.getLogger(__name__)

# Below this, the head's own guess is not worth overriding the keyword cascade
# for. 0.529 held-out means a coin flip near the middle of its range.
_HEAD_MIN_CONFIDENCE = 0.75

# The scope summary is already BOM-filtered upstream; this is a backstop so one
# pathological deal cannot blow the context window.
_MAX_SCOPE_CHARS = 8000


class ChatLike(Protocol):
    """Minimal shape of :class:`OpenAIChatClient` we depend on."""

    def complete(self, messages: list[Any], *, model: str, **kwargs: Any) -> str: ...


@dataclass(frozen=True)
class RoutingDecision:
    primary: str
    confidence: float
    source: str
    abstained: bool = False
    abstain_reason: str = ""

    def as_service_routing(self) -> dict[str, Any]:
        """The envelope shape every downstream consumer already reads."""
        return {
            "enabled": True,
            "primary": self.primary,
            "secondary": [],
            "confidence": round(self.confidence, 4),
            "source": self.source,
            "abstained": self.abstained,
            "abstain_reason": self.abstain_reason,
        }


_PROMPT = (
    "You classify a services deal into its PRIMARY managed-service pack.\n"
    "Judge by the ACTUAL SCOPE OF WORK, not the customer name or file names. A "
    "customer called \"Data Center Warehouse\" buying TV installs is "
    "audio_visual, not datacenter. A job dispatching technicians to stores is "
    "staff_augmentation even if those stores have wifi.\n\n"
    "Packs:\n{packs}\n\n"
    "Deal scope:\n{scope}\n\n"
    "Reply with ONLY the pack id, nothing else."
)


def _extract_pack(reply: str, valid: frozenset[str]) -> str:
    """Take the first valid pack id the model says.

    A small model pads with prose or code fences; a large one usually does not.
    Accepting the first valid token handles both without accepting garbage.
    """
    text = (reply or "").strip().lower()
    for token in re.findall(r"[a-z_]+", text):
        if token in valid:
            return token
    for pid in sorted(valid, key=len, reverse=True):
        if pid in text:
            return pid
    return ""


def classify_scope(
    *,
    scope_summary: str,
    packs: Sequence[tuple[str, str]],
    chat: ChatLike | None,
    model: str,
) -> RoutingDecision | None:
    """Ask the model which pack this scope is. ``None`` means no opinion."""
    if chat is None or not scope_summary.strip() or not packs:
        return None
    valid = frozenset(pid for pid, _ in packs)
    prompt = _PROMPT.format(
        packs="\n".join(f"- {pid}: {name}" for pid, name in packs),
        scope=scope_summary[:_MAX_SCOPE_CHARS],
    )
    try:
        reply = chat.complete(
            [{"role": "user", "content": prompt}], model=model, max_tokens=16
        )
    except Exception as exc:  # a dead endpoint must never fail a compile
        log.warning("scope_router: model call failed (%s); deferring", exc)
        return None
    pack = _extract_pack(reply if isinstance(reply, str) else str(reply), valid)
    if not pack:
        log.warning("scope_router: no valid pack in reply %r; deferring", str(reply)[:120])
        return None
    return RoutingDecision(primary=pack, confidence=0.9, source="llm_scope_router")


def resolve_routing(
    *,
    envelope_routing: Mapping[str, Any] | None,
    scope_summary: str,
    packs: Sequence[tuple[str, str]],
    chat: ChatLike | None = None,
    model: str = "",
) -> dict[str, Any]:
    """Resolve ONE routing answer from the ladder, or ``{}`` for no opinion.

    Returning ``{}`` is a real answer: it means every keyword path downstream
    decides exactly as it does today. That is why this cannot regress routing —
    the worst case is the current behaviour.
    """
    if chat is not None and model:
        decided = classify_scope(
            scope_summary=scope_summary, packs=packs, chat=chat, model=model
        )
        if decided is not None:
            return decided.as_service_routing()

    head = dict(envelope_routing or {})
    if not head:
        return {}
    if head.get("abstained") or str(head.get("abstain_reason") or "").strip():
        return {}
    primary = str(head.get("primary") or "").strip()
    if not primary:
        return {}
    try:
        confidence = float(head.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < _HEAD_MIN_CONFIDENCE:
        # Deliberate: a sub-threshold head is worse than no head. Measured over
        # 20 live deals, deferring to today's head scores 6/20 where the keyword
        # cascade alone scores 5/20 — inside the noise, and not worth
        # overriding evidence for.
        log.info(
            "scope_router: head primary %r at confidence %.2f is below %.2f; deferring",
            primary, confidence, _HEAD_MIN_CONFIDENCE,
        )
        return {}
    return dict(head)


__all__ = ["RoutingDecision", "classify_scope", "resolve_routing"]
