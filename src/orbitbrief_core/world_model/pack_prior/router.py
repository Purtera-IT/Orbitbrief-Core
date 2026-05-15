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


def _atom_text_stream(atom: dict[str, Any]) -> str:
    """Concatenate all routable text fields on a parser-os atom.

    The legacy router only read ``atom["text"]``, but parser-os atoms
    actually carry the bulk of their evidence in ``raw_text``,
    ``normalized_text``, ``value`` (a dict), ``entity_keys``, and
    ``source_refs[].locator`` (filename / sheet / section_path / page).
    Reading only ``text`` is what caused security/camera/paging cases
    to route to ``other`` despite obvious vendor/device evidence.
    """
    parts: list[str] = []

    for key in ("text", "raw_text", "normalized_text", "claim", "normalized_claim"):
        v = atom.get(key)
        if isinstance(v, str) and v.strip():
            parts.append(v)

    value = atom.get("value")
    if isinstance(value, dict):
        for v in value.values():
            if isinstance(v, (str, int, float)):
                parts.append(str(v))
            elif isinstance(v, list):
                parts.extend(str(x) for x in v if isinstance(x, (str, int, float)))
            elif isinstance(v, dict):
                parts.extend(
                    str(x) for x in v.values() if isinstance(x, (str, int, float))
                )

    for key in atom.get("entity_keys") or ():
        parts.append(str(key).replace(":", " ").replace("_", " "))

    for ref in atom.get("source_refs") or ():
        if isinstance(ref, dict):
            parts.append(str(ref.get("filename") or ""))
            locator = ref.get("locator") or {}
            if isinstance(locator, dict):
                parts.append(str(locator.get("section_path") or ""))
                parts.append(str(locator.get("sheet") or ""))
                parts.append(str(locator.get("page") or ""))

    return " ".join(p for p in parts if p)
# Length floor for unigram tokens. Two-char abbreviations (``ap``, ``rf``,
# ``av``, ``po``, ``id``) carry strong domain signal, so we accept them
# but only via the boost path — regular keyword matches still need ≥ 3
# chars so workbook noise like "of"/"to" never slips in.
_MIN_TOKEN_LEN = 2
_MIN_REGULAR_LEN = 3
# Boost weight: a hand-curated boost match counts this many times more
# than a workbook keyword match.
_BOOST_WEIGHT = 3
# PR13 — per-source keyword cap. A single chatty atom (e.g. a long
# Markdown paragraph repeating "service desk" 40 times) was inflating
# one pack's score with boilerplate. Cap unique-keyword contribution
# per source so the dominant pack must come from breadth of evidence,
# not chatty boilerplate density.
_MAX_HITS_PER_SOURCE_PER_KEYWORD = 1
# PR12 — "other" is a fallback sink, not a competitive pack. After
# scoring, if any specialized pack has a meaningful share of the top
# raw_score, force "other" to lose. The threshold is loose on
# purpose: any specialized pack with raw_score >= 20% of the top
# raw_score is enough to demote "other".
_OTHER_FALLBACK_PACK_ID = "other"
_OTHER_DEMOTE_FRACTION = 0.20


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

        # PR12 — "other" is a fallback. If any specialized pack has a
        # meaningful share of the top raw_score, demote "other" so it
        # cannot win top-1 or be selected as a brain target. We still
        # report its score for transparency.
        raw_scores = self._demote_other_when_specialized_exists(raw_scores)

        # PR13 — replace softmax confidence with a margin + support
        # signal that doesn't saturate at 1.0.
        confidences = self._calibrated_confidences(raw_scores)

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

        # Boss-review v9 C001-F1 / C002-F1 — apply pack-level
        # ``required_anchor_regex_any`` AFTER raw selection, so packs
        # like wireless / audio_visual whose generic vocabulary
        # matches a cabling case can't carry a brain unless real
        # equipment evidence appears in the corpus text.
        anchor_text = " ".join(
            _atom_text_stream(a) for a in (envelope.get("atoms") or ())
        )
        selected_pack_ids = self._select_pack_ids(
            scores,
            registry=self.registry,
            anchor_text=anchor_text,
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
            selected_pack_ids=tuple(selected_pack_ids),
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
            # PR13 — per-source de-dup so a chatty atom that repeats
            # one keyword 40 times only counts once for that pack.
            seen_per_pack: dict[str, set[str]] = {}
            for tok in tokens:
                if len(tok) >= _MIN_REGULAR_LEN:
                    for pack_id in self.registry.packs_for_keyword(tok):
                        seen = seen_per_pack.setdefault(pack_id, set())
                        if tok in seen:
                            continue
                        seen.add(tok)
                        raw_scores[pack_id] += 1
                        matched[pack_id].add(tok)
                for pack_id in self.registry.packs_for_boost_keyword(tok):
                    seen = seen_per_pack.setdefault(pack_id, set())
                    if f"!{tok}" in seen:
                        continue
                    seen.add(f"!{tok}")
                    raw_scores[pack_id] += _BOOST_WEIGHT
                    matched[pack_id].add(f"!{tok}")
            for big in _bigrams(tokens):
                for pack_id in self.registry.packs_for_boost_keyword(big):
                    seen = seen_per_pack.setdefault(pack_id, set())
                    if f"!{big}" in seen:
                        continue
                    seen.add(f"!{big}")
                    raw_scores[pack_id] += _BOOST_WEIGHT
                    matched[pack_id].add(f"!{big}")

        return raw_scores, matched, total_tokens

    def _iter_token_streams(
        self, envelope: dict[str, Any]
    ) -> Iterable[list[str]]:
        """Yield one token list per text source so bigrams stay bounded by source."""
        for atom in envelope.get("atoms") or ():
            text = _atom_text_stream(atom)
            if text:
                yield self._tokenize(text)
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
        """Temperature-scaled softmax — kept for back-compat tests; the
        live ``compute`` path uses :meth:`_calibrated_confidences`."""
        if not raw_scores:
            return {}
        floor = 1e-3
        adjusted = {
            pid: float(s) / max(self.softmax_temperature, 1e-6) + floor
            for pid, s in raw_scores.items()
        }
        m = max(adjusted.values())
        exps = {pid: math.exp(v - m) for pid, v in adjusted.items()}
        total = sum(exps.values())
        return {pid: v / total for pid, v in exps.items()}

    @staticmethod
    def _demote_other_when_specialized_exists(
        raw_scores: dict[str, int],
    ) -> dict[str, int]:
        """PR12 — make "other" a fallback sink, not a competitive pack.

        If any specialized pack has raw_score >= 20 % of the top
        specialized raw_score, set ``other`` to 0 so it can never
        win top-1 or be selected as a brain target. The intent: the
        ``other`` pack is for engagements with no recognizable
        domain, not for splitting credit with real packs.
        """
        if _OTHER_FALLBACK_PACK_ID not in raw_scores:
            return raw_scores
        specialized = {
            pid: s for pid, s in raw_scores.items()
            if pid != _OTHER_FALLBACK_PACK_ID
        }
        if not specialized:
            return raw_scores
        top_specialized = max(specialized.values())
        if top_specialized <= 0:
            return raw_scores
        # Anyone with >= 20 % of the top specialized score qualifies.
        strong_specialized = [
            pid for pid, s in specialized.items()
            if s >= _OTHER_DEMOTE_FRACTION * top_specialized
        ]
        if strong_specialized:
            out = dict(raw_scores)
            out[_OTHER_FALLBACK_PACK_ID] = 0
            return out
        return raw_scores

    @staticmethod
    def _calibrated_confidences(raw_scores: dict[str, int]) -> dict[str, float]:
        """PR13 — margin + support based confidence.

        Replaces the softmax that saturated at 1.0 on every case
        with a sigmoid over (top - runner_up) / max(top, 1). The
        confidence ceiling is 0.985 — any pack at exactly 1.0 means
        we picked the wrong calibrator.
        """
        if not raw_scores:
            return {}
        sorted_scores = sorted(raw_scores.values(), reverse=True)
        top = float(sorted_scores[0])
        if top <= 0:
            # No signal — uniform low confidence.
            return {pid: 0.0 for pid in raw_scores}
        runner_up = float(sorted_scores[1]) if len(sorted_scores) > 1 else 0.0
        margin_ratio = (top - runner_up) / top  # 0..1
        # Sigmoid centered around a 10 % margin so a thin win is ~0.55,
        # a 30 % margin is ~0.78, a 60 % margin is ~0.94.
        ceiling = 0.985
        center = 0.10
        steepness = 6.0
        top_conf = ceiling / (1 + math.exp(-steepness * (margin_ratio - center)))
        # Distribute remaining mass to runner-ups proportional to their
        # raw_score so secondaries still get a useful confidence number.
        out: dict[str, float] = {}
        for pid, s in raw_scores.items():
            if s == 0:
                out[pid] = 0.0
                continue
            if s == int(top):
                out[pid] = top_conf
            else:
                # Other packs scale to top_conf * (s/top).
                out[pid] = round(top_conf * (s / top), 4)
        return out

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
    def _select_pack_ids(
        scores: list[PackScore],
        *,
        registry: "DomainPackRegistry | None" = None,
        anchor_text: str = "",
    ) -> list[str]:
        # PR12 — never select "other" as a brain target. The
        # _demote_other_when_specialized_exists step zeros it out
        # when specialized packs exist; we still skip it explicitly
        # here for the all-zero corner case.
        scores = [s for s in scores if s.pack_id != _OTHER_FALLBACK_PACK_ID]
        """Pick top pack + secondary packs that carry meaningful evidence.

        Selection rules (order matters; first match wins per pack):

        * The top raw-score pack is always selected.
        * Other packs join the selection if any of:
          - ``raw_score >= 60`` (absolute strength), OR
          - ``raw_score >= 0.20 * top_raw_score`` (relative strength), OR
          - ≥ 2 boosted-keyword hits (curated boost wins are rare and
            deliberately strong evidence).

        Capped at 4 to bound brain fan-out. Stops softmax saturation
        from hiding strong secondary signal.
        """
        if not scores:
            return []

        by_raw = sorted(scores, key=lambda s: (-s.raw_score, s.pack_id))
        top = by_raw[0]
        selected = [top.pack_id]

        for score in by_raw[1:]:
            if score.raw_score <= 0:
                continue
            strong_absolute = score.raw_score >= 60
            strong_fraction = (
                top.raw_score > 0 and score.raw_score >= 0.20 * top.raw_score
            )
            boosted_hits = (
                sum(1 for kw in score.matched_keywords if kw.startswith("!")) >= 2
            )
            if strong_absolute or strong_fraction or boosted_hits:
                selected.append(score.pack_id)

        selected = selected[:6]

        # PR (post-v3) — boosted-keyword sweep. Any specialized pack
        # with >= 2 BOOSTED keyword hits gets included even when its
        # raw_score puts it outside the top-N by sort. Boost matches
        # are curated, intentional, and high-precision (e.g.
        # "alertus", "valcom", "bogen" → paging_mass_notification).
        # Without this, a corpus with lots of generic msp / monitoring
        # vocab can squeeze paging / fire / das / electrical out of
        # the brain fan-out even when their vendor names are in the
        # source.
        for score in by_raw:
            if score.pack_id in selected:
                continue
            boosted_hits = sum(
                1 for kw in score.matched_keywords if kw.startswith("!")
            )
            if boosted_hits >= 2 and score.raw_score > 0:
                selected.append(score.pack_id)
                if len(selected) >= 8:
                    break

        # Boss-review v9 C001-F1 / C002-F1 — pack-level anchor gate.
        # Drop selected packs that declare ``required_anchor_regex_any``
        # in domain_packs.yaml unless the corpus has the required
        # number of distinct anchor matches. Top pack is preserved
        # (we still need to RECORD what the router thought) but
        # excluded from selected_pack_ids so brains don't run on it.
        if registry is not None and anchor_text:
            top_id = selected[0] if selected else None
            kept: list[str] = []
            for pid in selected:
                pack = registry.get(pid)
                anchors = tuple(getattr(pack, "required_anchor_regex_any", ()) or ())
                if not anchors:
                    kept.append(pid)
                    continue
                min_hits = int(
                    getattr(pack, "required_anchor_min_distinct_hits", 2) or 2
                )
                distinct: set[str] = set()
                ok = False
                for pat in anchors:
                    try:
                        rx = re.compile(pat, re.I)
                    except re.error:
                        continue
                    for m in rx.finditer(anchor_text):
                        distinct.add(m.group(0).lower())
                        if len(distinct) >= min_hits:
                            ok = True
                            break
                    if ok:
                        break
                if ok or pid == top_id:
                    kept.append(pid)
            selected = kept

        return selected

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
            "/no_think\n"
            "You are a domain router for OrbitBrief. Pick exactly one "
            "pack_id from the candidates that best fits this project. "
            "Reply with only the pack_id, no prose."
        )
        usr = (
            f"Reason for escalation: {reason.value}\n"
            f"Candidates:\n" + "\n".join(candidate_lines) + "\n"
            "Reply with one pack_id from the list."
        )
        # Even with ``/no_think`` Qwen3 emits ~110 tokens of empty
        # think markers before the answer; 1024 leaves comfortable room.
        reply = self.chat_client.complete(
            [ChatMessage("system", sys), ChatMessage("user", usr)],
            model=self.chat_model_id,
            temperature=0.0,
            max_tokens=1024,
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
