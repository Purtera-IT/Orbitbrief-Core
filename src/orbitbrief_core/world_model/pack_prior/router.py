"""Pack-prior router: keyword scoring + bounded LLM escalation.

Algorithm
---------

1. **Token sweep.** Read the envelope's atom text (and entity
   ``canonical_name`` / ``aliases``). Lowercase, tokenize on
   non-alphanumerics, drop tokens shorter than 3 chars.
2. **Score.** For each token, look up the registry's inverted
   index ``keyword → pack_ids`` and increment those packs' raw
   scores. Each pack also accrues a sorted set of matched
   keywords for transparency.
3. **Soften.** Convert raw scores to confidences via a temperature-
   scaled softmax with a tiny floor so packs with zero hits still
   get a non-zero (but tiny) probability — this prevents the
   "all-zero scores" edge case from producing NaN confidence.
4. **Escalate (optional).** If the top-1 confidence minus the
   top-2 confidence is below ``ambiguity_threshold`` (0.15 by
   spec), or if every score is zero, ask the LLM to pick from the
   top-K (K=4) candidates, citing 1–2 representative atoms per
   candidate. The LLM call is logged with a structured
   :class:`EscalationReason`.

Determinism
-----------

* Tokenization, score sort, and tie-break are pure-Python and
  fully ordered. Two runs over byte-identical envelopes produce
  byte-identical states.
* The LLM call is *not* deterministic across temperatures/models,
  so we surface it explicitly (``escalated=True``,
  ``pre_escalation_top_pack_id``) — never silently let it change
  the answer.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Iterable

from orbitbrief_core.evidence_runtime.runtime import EvidenceRuntime, RuntimeKey
from orbitbrief_core.inference.client import ChatClient, ChatMessage
from orbitbrief_core.world_model.escalation import (
    EscalationLog,
    EscalationReason,
)
from orbitbrief_core.world_model.pack_prior.state import (
    PackPriorState,
    PackScore,
)
from orbitbrief_core.world_model.registry import (
    DomainPackRegistry,
    load_default_registry,
)


_TOKEN = re.compile(r"[a-z0-9_]+")
# Length floor for unigram tokens. Two-char abbreviations (``ap``, ``rf``,
# ``av``, ``po``, ``id``) carry strong domain signal, so we accept them
# but only via the boost path — regular keyword matches still need ≥ 3
# chars so workbook noise like "of"/"to" never slips in.
_MIN_TOKEN_LEN = 2
_MIN_REGULAR_LEN = 3
# Boost weight: a hand-curated boost match counts this many times more
# than a workbook keyword match.
_BOOST_WEIGHT = 3


def _strip_think(text: str) -> str:
    """Remove Qwen3-style ``<think>...</think>`` reasoning blocks."""
    if "</think>" in text:
        return text.rsplit("</think>", 1)[1]
    return text


def _bigrams(tokens: list[str]) -> list[str]:
    """Underscore-joined bigrams to catch multi-word boost keywords."""
    return [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]


@dataclass
class PackPrior:
    """Pack-prior engine. Stateless aside from configuration."""

    registry: DomainPackRegistry
    chat_client: ChatClient | None = None
    chat_model_id: str = "qwen3:14b"
    ambiguity_threshold: float = 0.15  # spec §1
    softmax_temperature: float = 1.0
    max_escalation_candidates: int = 4

    @classmethod
    def with_default_registry(
        cls,
        chat_client: ChatClient | None = None,
        **kwargs: Any,
    ) -> "PackPrior":
        return cls(
            registry=load_default_registry(),
            chat_client=chat_client,
            **kwargs,
        )

    def compute(
        self,
        runtime: EvidenceRuntime,
        *,
        key: RuntimeKey | None = None,
    ) -> PackPriorState:
        """Score the project's envelope and return a :class:`PackPriorState`."""
        rk = key or runtime.default_key
        if rk is None:
            raise ValueError(
                "PackPrior.compute: runtime has no default key; "
                "load an envelope or pass key= explicitly"
            )
        envelope = runtime.to_envelope_dict(rk)
        log = EscalationLog()

        raw_scores, matched_kws, tokens_considered = self._score(envelope)
        confidences = self._softmax(raw_scores)

        scores = self._build_scores(raw_scores, confidences, matched_kws)
        top, runner_up = scores[0], scores[1] if len(scores) > 1 else None

        margin = top.confidence - (runner_up.confidence if runner_up else 0.0)
        escalated = False
        pre_top: str | None = None

        # Decide whether to escalate.
        ambiguous = runner_up is not None and margin < self.ambiguity_threshold
        no_signal = sum(raw_scores.values()) == 0
        if (ambiguous or no_signal) and self.chat_client is not None:
            reason = (
                EscalationReason.PACK_PRIOR_NO_SIGNAL
                if no_signal
                else EscalationReason.PACK_PRIOR_AMBIGUOUS_TOP2
            )
            top2_id = runner_up.pack_id if runner_up else "none"
            top2_conf = runner_up.confidence if runner_up else 0.0
            detail = (
                f"top1={top.pack_id}({top.confidence:.3f}) "
                f"top2={top2_id}({top2_conf:.3f}) "
                f"margin={margin:.3f}"
            )
            try:
                llm_pick = self._ask_llm(envelope, scores, reason)
            except Exception as exc:
                # Never fail the deterministic engine because the LLM
                # is down; log the attempt and fall back to keyword.
                log.record(
                    engine="pack_prior",
                    reason=reason,
                    detail=f"{detail} | llm_error={type(exc).__name__}: {exc}",
                    model_id=self.chat_model_id,
                )
            else:
                log.record(
                    engine="pack_prior",
                    reason=reason,
                    detail=f"{detail} | llm_pick={llm_pick}",
                    model_id=self.chat_model_id,
                )
                if llm_pick and llm_pick != top.pack_id and self.registry.get(
                    llm_pick
                ):
                    escalated = True
                    pre_top = top.pack_id
                    # Re-rank: move LLM pick to the top, keep the rest in order.
                    scores = self._reorder_top(scores, llm_pick)
                    top = scores[0]
                    runner_up = scores[1] if len(scores) > 1 else None
                    margin = top.confidence - (
                        runner_up.confidence if runner_up else 0.0
                    )

        return PackPriorState(
            project_id=rk.project_id,
            compile_id=rk.compile_id,
            scores=tuple(scores),
            top_pack_id=top.pack_id,
            top_confidence=top.confidence,
            runner_up_pack_id=runner_up.pack_id if runner_up else None,
            runner_up_confidence=runner_up.confidence if runner_up else 0.0,
            margin=margin,
            escalated=escalated,
            pre_escalation_top_pack_id=pre_top,
            escalation_log=log.to_dict(),
            tokens_considered=tokens_considered,
        )

    # ───── internals ─────

    def _score(
        self, envelope: dict[str, Any]
    ) -> tuple[dict[str, int], dict[str, set[str]], int]:
        """Return (pack_id → weighted score, pack_id → matched keywords, total tokens).

        Two passes per text blob:

        * **Unigram boost / regular** — emit each token once. Tokens
          ≥ 3 chars hit the regular keyword index (+1). Any token
          (≥ 2 chars) also hits the boost index (+3 if matched).
        * **Bigram boost** — emit ``a_b`` for adjacent tokens to
          catch multi-word boost keywords like ``access_point`` or
          ``chain_of_custody``. Bigrams only hit the boost index.
        """
        raw_scores: dict[str, int] = {p.id: 0 for p in self.registry}
        matched: dict[str, set[str]] = {p.id: set() for p in self.registry}
        total_tokens = 0

        for tokens in self._iter_token_streams(envelope):
            total_tokens += len(tokens)
            for tok in tokens:
                if len(tok) >= _MIN_REGULAR_LEN:
                    for pack_id in self.registry.packs_for_keyword(tok):
                        raw_scores[pack_id] += 1
                        matched[pack_id].add(tok)
                for pack_id in self.registry.packs_for_boost_keyword(tok):
                    raw_scores[pack_id] += _BOOST_WEIGHT
                    matched[pack_id].add(f"!{tok}")
            for big in _bigrams(tokens):
                for pack_id in self.registry.packs_for_boost_keyword(big):
                    raw_scores[pack_id] += _BOOST_WEIGHT
                    matched[pack_id].add(f"!{big}")

        return raw_scores, matched, total_tokens

    def _iter_token_streams(
        self, envelope: dict[str, Any]
    ) -> Iterable[list[str]]:
        """Yield one token list per text source so bigrams stay bounded by source."""
        for atom in envelope.get("atoms") or ():
            yield self._tokenize(atom.get("text") or "")
        for entity in envelope.get("entities") or ():
            yield self._tokenize(entity.get("canonical_name") or "")
            for alias in entity.get("aliases") or ():
                yield self._tokenize(alias)
        for doc in envelope.get("documents") or ():
            yield self._tokenize(doc.get("filename") or "")

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [
            m for m in _TOKEN.findall(text.lower()) if len(m) >= _MIN_TOKEN_LEN
        ]

    def _softmax(self, raw_scores: dict[str, int]) -> dict[str, float]:
        """Temperature-scaled softmax with a small floor for the all-zero case."""
        # Add 1e-3 floor so an all-zeros input still yields a uniform-ish
        # distribution rather than 0/0 NaN.
        if not raw_scores:
            return {}
        floor = 1e-3
        adjusted = {
            pid: float(s) / max(self.softmax_temperature, 1e-6) + floor
            for pid, s in raw_scores.items()
        }
        # Numerical-stability: subtract max before exp.
        m = max(adjusted.values())
        exps = {pid: math.exp(v - m) for pid, v in adjusted.items()}
        total = sum(exps.values())
        return {pid: v / total for pid, v in exps.items()}

    def _build_scores(
        self,
        raw: dict[str, int],
        conf: dict[str, float],
        matched: dict[str, set[str]],
    ) -> list[PackScore]:
        """Sort by confidence desc, tie-break by pack_id asc for stability."""
        out: list[PackScore] = []
        for pack in self.registry:
            out.append(
                PackScore(
                    pack_id=pack.id,
                    display_name=pack.display_name,
                    raw_score=raw.get(pack.id, 0),
                    confidence=conf.get(pack.id, 0.0),
                    matched_keywords=tuple(sorted(matched.get(pack.id, ()))),
                )
            )
        out.sort(key=lambda s: (-s.confidence, s.pack_id))
        return out

    @staticmethod
    def _reorder_top(scores: list[PackScore], new_top_id: str) -> list[PackScore]:
        promoted = [s for s in scores if s.pack_id == new_top_id]
        rest = [s for s in scores if s.pack_id != new_top_id]
        return promoted + rest

    def _ask_llm(
        self,
        envelope: dict[str, Any],
        scores: list[PackScore],
        reason: EscalationReason,
    ) -> str | None:
        """Ask the LLM to pick one pack id from the top-K candidates."""
        assert self.chat_client is not None  # guarded by caller
        candidates = scores[: self.max_escalation_candidates]
        # Pull 2 short atoms per candidate for context.
        snippets = self._candidate_snippets(envelope, candidates)
        candidate_lines = [
            f"- {c.pack_id} ({c.display_name}): keywords={list(c.matched_keywords)[:6]}; "
            f"sample_text={snippets.get(c.pack_id, [])}"
            for c in candidates
        ]
        sys = (
            "You are a domain router for OrbitBrief. Pick exactly one "
            "pack_id from the candidates that best fits this project. "
            "Reply with only the pack_id, no prose."
        )
        usr = (
            f"Reason for escalation: {reason.value}\n"
            f"Candidates:\n" + "\n".join(candidate_lines) + "\n"
            "Reply with one pack_id from the list."
        )
        # Generous max_tokens because Qwen3 burns tokens in its
        # ``<think>`` block before producing the final answer.
        reply = self.chat_client.complete(
            [ChatMessage("system", sys), ChatMessage("user", usr)],
            model=self.chat_model_id,
            temperature=0.0,
            max_tokens=512,
        )
        # Strip Qwen3 ``<think>`` block, then scan for a candidate id.
        text = _strip_think(reply).strip().lower()
        for c in candidates:
            if c.pack_id in text:
                return c.pack_id
        return None

    @staticmethod
    def _candidate_snippets(
        envelope: dict[str, Any], candidates: list[PackScore]
    ) -> dict[str, list[str]]:
        """Best-effort: 2 short atom snippets per candidate matching its keywords."""
        out: dict[str, list[str]] = {c.pack_id: [] for c in candidates}
        kw_to_pack: dict[str, list[str]] = {}
        for c in candidates:
            for kw in c.matched_keywords[:8]:
                kw_to_pack.setdefault(kw, []).append(c.pack_id)
        for atom in envelope.get("atoms") or ():
            text = atom.get("text") or ""
            t = text.lower()
            for kw, pack_ids in kw_to_pack.items():
                if kw in t:
                    snippet = text[:140]
                    for pid in pack_ids:
                        if len(out[pid]) < 2 and snippet not in out[pid]:
                            out[pid].append(snippet)
        return out
