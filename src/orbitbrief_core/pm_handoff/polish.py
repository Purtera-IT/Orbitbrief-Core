"""Phase 91 — PM-voice polish pass over PMHandoff text.

The raw `build_pm_handoff()` output is correct but clinical. Gaps say
"Controller deployment topology unresolved for site Airport Logistics
Annex"; risks say "C9166D1 lead time 6-8 weeks per Cisco distributor
confirmation". Accurate, but reads like a database. This stage rewrites
the text-bearing fields into the voice a PM would use when emailing
the customer or filling a SOW — preserving every fact, citation, and
identifier, only polishing the prose.

Polished fields:

* `gaps[].message`, `gaps[].suggested_open_question`
* `customer_questions[].message`, `customer_questions[].suggested_open_question`
* `risk_register[].description`, `risk_register[].mitigation`
* `executive_summary.headline`, `health_line`, `next_action`
* `customer_answer_slots[].question_text`
* SOW section narratives — handled in :mod:`sow_draft` via
  :func:`polish_sow_sections` when a chat client is supplied.

Guarantees:

1. **Content-hash cached.** Each (role, raw_text) → polished_text
   mapping is stored in a JSONL cache. Identical input produces
   identical polished output on every subsequent run. Free re-runs.
2. **Deterministic fallback.** Any LLM failure (transport, JSON
   parse, validation) returns the raw text unchanged. Polish never
   blocks a compile.
3. **Batch-call.** Up to 12 items per LLM call. A typical OPTBOT-sized
   case polishes all gaps + risks + exec summary in 3–5 calls,
   8–15 s total against `qwen3:14b`.
4. **Citation preserved.** The prompt explicitly forbids the model
   from inventing or removing IDs, dollar amounts, dates, site
   names, or stakeholder names. Validator strips any line where a
   guarded token went missing.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable

from orbitbrief_core.inference.client import (
    ChatClient,
    ChatMessage,
    InferenceError,
)
from orbitbrief_core.pm_handoff.models import (
    GapCard,
    PMHandoff,
)

# Default model. v46.1 — switched from qwen3:14b (thinking model,
# 4–6k reasoning tokens per item, ~25 min total wall time for 113
# items) to qwen2.5:3b (non-thinking, ~1.9 GB, ~5–10× faster
# generation, plenty of quality for PM-voice prose rewriting).
# Brains stay on qwen3:14b because they emit structured JSON that
# benefits from thinking chain-of-thought.  Polish only rewrites
# short prose — no reasoning needed.
DEFAULT_MODEL = "qwen2.5:3b"

# Maximum items per batched LLM call. qwen2.5:3b context is 32 K
# tokens.  Each item is ~120 tokens system + ~300 tokens raw input
# + ~200 tokens completion → bumped from 12 to 18 since the smaller
# model also has lower per-call latency, so larger batches don't
# bottleneck wall time.
_BATCH_SIZE = 18

# Hard cap on output tokens per polish call. Mirrors brain runner.
_MAX_OUTPUT_TOKENS = 4096

# Tokens we forbid the model from dropping. If any of these appear in
# the raw text and are missing from the polished text, we keep the raw.
# Dollar amounts, percentages, dates, site names, rule IDs, stakeholder
# tokens, atom_ids. Picked at runtime per-item.
_MONEY_RE = re.compile(r"\$[\d,]+(?:\.\d+)?[MK]?")
_PCT_RE = re.compile(r"\b\d{1,3}(?:\.\d+)?\s*%")
_ID_RE = re.compile(r"\b[A-Z]{2,4}[-_][A-Z0-9]{2,}[-_]?[A-Z0-9]*\b|\batm_\w+\b|\bcmp_\w+\b")
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

# Lowercase site / entity keys the model must preserve verbatim. The
# parser-os layer treats lowercase tokens like "atl hq", "atl west",
# "airport logistics annex" as canonical entity keys — title-casing them
# (which qwen3:14b loves to do) breaks joins between UI rows and atoms.
# Captures the LOWERCASE pair "<short prefix> <site-suffix>" only — this
# is narrow on purpose so it never over-captures multi-word noun phrases
# that aren't actually entity keys. The validator is case-sensitive,
# so if the polish title-cases either word the match fails.
_SITE_KEY_RE = re.compile(
    r"\b[a-z]{2,12}[\s-]"
    r"(?:hq|west|east|north|south|annex|campus|center|centre|datacenter|"
    r"datacentre|warehouse|office|branch|lab|plant)\b"
    # NOTE: deliberately NOT re.IGNORECASE — we only flag the lowercase form
)
# Bare-lowercase part numbers / SKUs / domain identifiers — e.g.,
# "c9166d1", "wlc9800", "n9k-c93180". Match alphanumeric with at least
# one digit so we don't over-catch English words.
_PART_NUMBER_RE = re.compile(
    r"\b(?=[a-z0-9-]*\d)[a-z][a-z0-9-]{2,}\b",
    re.IGNORECASE,
)
# Mixed-case hyphenated identifiers — "ATL-West", "ATL-HQ", "Net-30",
# "Net-45", "Wi-Fi", "Catalyst-9300", "Cisco-Meraki". Catches both
# directions of case-changing (lowercasing AND title-casing) because
# this is the most common shape a customer-facing identifier takes.
_HYPHEN_ID_RE = re.compile(r"\b[A-Z][A-Za-z0-9]*-[A-Za-z0-9]+\b")
# Multi-word title-cased proper nouns — "Airport Logistics Annex",
# "DNA Spaces", "Priya Narang", "Cisco Catalyst". Two or more
# consecutive Title-Case-or-ALL-CAPS words, but NOT followed by a
# hyphenated code (so "Controller R-WIFI-001" doesn't trigger).
# Case-sensitive — the polish must preserve them verbatim.
_TITLE_PHRASE_RE = re.compile(
    r"\b[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){1,4}\b"
)


@dataclass(frozen=True)
class PolishItem:
    """One unit to polish.

    ``key`` is the (role, content) hash — used both as the cache key
    and as the per-item ordinal the LLM emits in its JSON response.
    """

    key: str
    role: str
    raw_text: str
    # Optional contextual hint the model can use to phrase better.
    context: str = ""


@dataclass(frozen=True)
class PolishResult:
    """Output of one polish call."""

    key: str
    polished_text: str
    used_fallback: bool


@dataclass
class PolishCache:
    """File-backed key→polished_text cache.

    Persists across compiles so re-running on the same envelope
    doesn't burn LLM cost. JSONL on disk; one line per (key, text)
    pair.
    """

    path: Path
    _mem: dict[str, str] = field(default_factory=dict)
    _loaded: bool = False

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.path.exists():
            return
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    self._mem[row["key"]] = row["text"]
                except Exception:
                    continue
        except OSError:
            pass

    def get(self, key: str) -> str | None:
        self.load()
        return self._mem.get(key)

    def put(self, key: str, text: str) -> None:
        self.load()
        if self._mem.get(key) == text:
            return
        self._mem[key] = text
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"key": key, "text": text}, ensure_ascii=False) + "\n")
        except OSError:
            pass


def _hash_item(role: str, raw_text: str, model: str) -> str:
    """Stable hash for (role, raw_text, model). Cache key."""
    h = hashlib.sha256()
    h.update(role.encode("utf-8"))
    h.update(b"\x00")
    h.update(raw_text.encode("utf-8"))
    h.update(b"\x00")
    h.update(model.encode("utf-8"))
    return h.hexdigest()[:24]


def _guarded_tokens(raw_text: str) -> set[str]:
    """Tokens the polished output must preserve verbatim.

    Case-sensitive matches — the validator rejects both title-casing
    of lowercase canonical keys ("atl hq" → "Atlanta HQ") AND
    lowercasing of mixed-case canonical identifiers ("ATL-West" →
    "atl-west").
    """
    out: set[str] = set()
    for rx in (_MONEY_RE, _PCT_RE, _ID_RE, _DATE_RE):
        out.update(rx.findall(raw_text))
    out.update(_SITE_KEY_RE.findall(raw_text))
    out.update(_PART_NUMBER_RE.findall(raw_text))
    out.update(_HYPHEN_ID_RE.findall(raw_text))
    out.update(_TITLE_PHRASE_RE.findall(raw_text))
    return out


def _validate_polish(raw_text: str, polished_text: str) -> bool:
    """Reject the polish if it dropped a guarded token or got absurd.

    Rules:
    1. Every guarded token in raw must appear in polished — verbatim,
       case-sensitive. Catches title-casing of canonical site keys.
    2. Polished length ≤ 3× raw length.
    3. Polished length ≥ 0.4× raw length.
    """
    if not polished_text or not polished_text.strip():
        return False
    guarded = _guarded_tokens(raw_text)
    for tok in guarded:
        if tok not in polished_text:
            return False
    r_len = max(len(raw_text), 1)
    p_len = len(polished_text)
    if p_len > 3 * r_len or p_len < 0.4 * r_len:
        return False
    return True


# ──────────────────────────────────────────────────────────────────
# Prompt templates — one per role. Kept tight so batches stay small.
# ──────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a senior project manager at Purtera-IT \
polishing internal scope text for a customer-facing pre-SOW review. /no_think

Your job is to REWRITE each supplied raw item in PM-email voice: clear, \
decisive, fact-preserving, never longer than the original.

HARD RULES (the validator will REJECT and we will roll back to raw if any \
of these are violated):

1. PRESERVE EVERY IDENTIFIER VERBATIM, INCLUDING CASE. \
This applies to: dollar amounts ("$18,500", "$1,847,250"), percentages \
("99.5%", "30W"), dates in YYYY-MM-DD form ("2026-05-30"), rule IDs \
("R-WIFI-001"), atom IDs (atm_*, cmp_*), product part numbers \
("C9166D1", "WLC9800", "9300-48UXM"), hyphenated identifiers \
("ATL-HQ", "ATL-West", "Net-30", "Net-45", "Wi-Fi"), lowercase site \
keys ("atl hq", "atl west", "airport logistics annex"), and named \
proper nouns ("Airport Logistics Annex", "DNA Spaces", "Priya Narang", \
"Cisco", "Catalyst"). \
\
CASE MATTERS. "ATL-West" is NOT the same as "atl-west"; "Airport \
Annex" is NOT the same as "airport annex"; "atl hq" is NOT the same \
as "Atlanta HQ". Whatever case the raw uses, the polish uses. Do not \
title-case lowercase tokens. Do not lowercase title-cased tokens. \
Do not normalize. The validator is case-sensitive and will reject.

2. DO NOT invent: no new dates, no new dollar amounts, no new percentages, \
no new sites, no new stakeholders, no new vendors, no new rule IDs. If \
the raw doesn't mention it, you don't either.

3. NEVER ADD hedge words. Strike on sight (do not introduce these): \
"approximately", "approx", "around", "roughly", "appears to be", \
"seems", "may be", "might be", "could be", "possibly", "perhaps", \
"somewhat", "likely", "generally", "typically". If the raw ALREADY \
contains a hedge word, leave it alone (it's a fact-preserving \
constraint). You just must not ADD new ones.

4. ONE sentence per item by default. Two sentences allowed only when \
the raw genuinely contains two facts and combining them would obscure. \
Never three sentences.

REWRITE RULES — when to act, when to leave alone:

5. ACTION-NEEDED items (gap.message, gap.question, risk.mitigation, \
answer_slot.question): if the raw is a noun-phrase fragment or starts \
with a passive observation, REWRITE so the sentence opens with an \
imperative verb that names the action the PM should take. \
EXAMPLES: \
"Controller scope unresolved" → "Resolve controller scope"; \
"Net terms contradict" → "Align net terms"; \
"No RF survey on file" → "Validate the RF survey".

6. OBSERVED-STATE items (risk.description, urgency_signals.snippet, \
gap.message that begins with "X detected" or "X flagged"): \
DO NOT force an imperative — preserve the observation. \
EXAMPLES (KEEP as observations, do NOT make imperative): \
"HIPAA flag detected in Airport Annex" → keep "detected" \
(do NOT rewrite to "Detect HIPAA flag"); \
"Cutover window restricted to after 18:00 ET" → keep "restricted" \
(do NOT rewrite to "Restrict cutover window"). \
These describe states already true in the world, not actions to take.

7. PREFER ACTIVE VOICE. "is required" → "requires"; \
"will be performed by Purtera" → "Purtera will perform".

8. USE PARENTHETICAL CITATIONS for inline source pointers. \
"per the RFP" → "(per RFP)"; "according to Priya's email" → \
"(per Priya's email)". Do NOT add a citation if the raw didn't.

9. PLURALIZE NATURALLY. "5 blocker(s) and 7 warning(s)" → \
"5 blockers and 7 warnings". "site(s)" → "sites" if count > 1.

10. CONSOLIDATE FRAGMENTS. If the raw has two clauses joined by ". ", \
prefer joining with "; " when the second clause is dependent on the \
first. Drop low-content connectors. \
EXAMPLE: \
"Net payment terms contradict between source documents: the RFP \
specifies Net-30 while the signed quote specifies Net-45." → \
"Align net payment terms between RFP (Net-30) and signed quote \
(Net-45)." — drops "between source documents" because the citations \
in parens make it redundant.

11. IF RAW IS ALREADY GOOD, return the raw text unchanged. Polish is \
not a license to fiddle.

OUTPUT FORMAT: JSON object with shape \
{"items": [{"key": "<key>", "polished": "<rewrite>"}, ...]} \
exactly matching the keys provided. Do not emit markdown, prose, \
reasoning, or explanation outside the JSON."""


_RETRY_PROMPT_SUFFIX = """

PRIOR ATTEMPT FAILED the validator. The polish either DROPPED a guarded \
token (dollar amount, percentage, date, rule ID, part number, stakeholder \
name) or got the length wrong (must be 0.4× to 3× the raw length). \
Be more careful this round. Do not paraphrase any token that looks like \
a number, identifier, or proper noun — copy them character-for-character."""


def _build_polish_prompt(
    items: list[PolishItem], *, retry: bool = False
) -> tuple[str, str]:
    """Return (system, user) prompt for one batch.

    When ``retry`` is True the system prompt carries an extra suffix
    telling the model the previous attempt failed validation so it
    should be more careful with guarded tokens.
    """
    system = _SYSTEM_PROMPT + (_RETRY_PROMPT_SUFFIX if retry else "")
    user_lines: list[str] = [
        "Rewrite each item below per the rules. Output JSON only:",
        '{"items": [{"key": "<key>", "polished": "<rewrite>"}, ...]}',
        "",
        "ITEMS:",
    ]
    for it in items:
        ctx = f"  context: {it.context}" if it.context else ""
        user_lines.append(f'- key: "{it.key}"')
        user_lines.append(f'  role: "{it.role}"')
        if ctx:
            user_lines.append(ctx)
        user_lines.append(f"  raw: {json.dumps(it.raw_text, ensure_ascii=False)}")
        user_lines.append("")
    return system, "\n".join(user_lines)


def _parse_polish_response(text: str) -> dict[str, str]:
    """Extract {key: polished_text} from the model's JSON response.

    Robust against the qwen3 think-token leakage: strips any leading
    `<think>...</think>` block, finds the first balanced JSON object.
    """
    if not text:
        return {}
    # Strip qwen3 think markers if any leaked despite /no_think
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Find first '{' and last '}' — assume one JSON object
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return {}
    blob = text[start : end + 1]
    try:
        obj = json.loads(blob)
    except json.JSONDecodeError:
        return {}
    out: dict[str, str] = {}
    for row in obj.get("items", []) or []:
        if not isinstance(row, dict):
            continue
        key = row.get("key")
        polished = row.get("polished")
        if isinstance(key, str) and isinstance(polished, str):
            out[key] = polished.strip()
    return out


def _batched(seq: list[PolishItem], n: int) -> Iterable[list[PolishItem]]:
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def _attempt_batch(
    batch: list[PolishItem],
    *,
    chat_client: ChatClient,
    model: str,
    retry: bool,
) -> dict[str, str]:
    """One LLM call for a batch. Returns {key: polished_text} for items
    the model returned (validation happens at the caller).
    """
    sys_prompt, user_prompt = _build_polish_prompt(batch, retry=retry)
    messages = [
        ChatMessage(role="system", content=sys_prompt),
        ChatMessage(role="user", content=user_prompt),
    ]
    try:
        response_text = chat_client.complete(
            messages,
            model=model,
            temperature=0.2 if not retry else 0.0,
            max_tokens=_MAX_OUTPUT_TOKENS,
            response_format={"type": "json_object"},
        )
    except InferenceError:
        return {}
    return _parse_polish_response(response_text)


def polish_items(
    items: list[PolishItem],
    *,
    chat_client: ChatClient,
    model: str = DEFAULT_MODEL,
    cache: PolishCache | None = None,
    batch_size: int = _BATCH_SIZE,
) -> dict[str, PolishResult]:
    """Polish a batch of items. Returns {key: PolishResult}.

    For every item:
    * cache hit → returned with ``used_fallback=False``
    * cache miss → batched LLM call (temperature 0.2). On validation
      failure, ONE retry with a stricter prompt + temperature 0.0.
      If both attempts fail, returns raw with ``used_fallback=True``.
    """
    out: dict[str, PolishResult] = {}
    pending: list[PolishItem] = []
    for it in items:
        if cache is not None:
            cached = cache.get(it.key)
            if cached is not None:
                out[it.key] = PolishResult(it.key, cached, used_fallback=False)
                continue
        pending.append(it)

    for batch in _batched(pending, batch_size):
        polished_map = _attempt_batch(
            batch, chat_client=chat_client, model=model, retry=False
        )
        # Items the first attempt got right
        retry_batch: list[PolishItem] = []
        for it in batch:
            polished = polished_map.get(it.key, "").strip()
            if polished and _validate_polish(it.raw_text, polished):
                if cache is not None:
                    cache.put(it.key, polished)
                out[it.key] = PolishResult(it.key, polished, used_fallback=False)
            else:
                retry_batch.append(it)

        if not retry_batch:
            continue

        # Retry the rejects once with a stricter prompt
        retry_map = _attempt_batch(
            retry_batch, chat_client=chat_client, model=model, retry=True
        )
        for it in retry_batch:
            polished = retry_map.get(it.key, "").strip()
            if polished and _validate_polish(it.raw_text, polished):
                if cache is not None:
                    cache.put(it.key, polished)
                out[it.key] = PolishResult(it.key, polished, used_fallback=False)
            else:
                out[it.key] = PolishResult(it.key, it.raw_text, used_fallback=True)
    return out


# ──────────────────────────────────────────────────────────────────
# PMHandoff-level polish: walks the dataclass + mutates in place.
# ──────────────────────────────────────────────────────────────────


def _gap_polish_items(gaps: list[GapCard], model: str) -> list[PolishItem]:
    """Each gap → two polish items: message + suggested_open_question."""
    out: list[PolishItem] = []
    for g in gaps:
        msg = (g.message or "").strip()
        if msg:
            ctx = f"gap rule {g.rule_id} · domain {g.domain_label} · severity {g.severity}"
            out.append(
                PolishItem(
                    key=_hash_item(f"gap.message.{g.rule_id}", msg, model),
                    role="gap.message",
                    raw_text=msg,
                    context=ctx,
                )
            )
        q = (g.suggested_open_question or "").strip()
        if q:
            ctx = f"customer-facing question for gap {g.rule_id} · domain {g.domain_label}"
            out.append(
                PolishItem(
                    key=_hash_item(f"gap.question.{g.rule_id}", q, model),
                    role="gap.question",
                    raw_text=q,
                    context=ctx,
                )
            )
    return out


def _risk_polish_items(risks: list[dict[str, Any]], model: str) -> list[PolishItem]:
    out: list[PolishItem] = []
    for r in risks:
        rid = str(r.get("risk_id") or "")
        desc = str(r.get("description") or "").strip()
        if desc:
            out.append(
                PolishItem(
                    key=_hash_item(f"risk.description.{rid}", desc, model),
                    role="risk.description",
                    raw_text=desc,
                    context=f"risk {rid} · severity {r.get('severity', '')}",
                )
            )
        mit = str(r.get("mitigation") or "").strip()
        if mit:
            out.append(
                PolishItem(
                    key=_hash_item(f"risk.mitigation.{rid}", mit, model),
                    role="risk.mitigation",
                    raw_text=mit,
                    context=f"mitigation for risk {rid}",
                )
            )
    return out


def _exec_polish_items(exec_summary: dict[str, Any], model: str) -> list[PolishItem]:
    out: list[PolishItem] = []
    for field_name in ("headline", "health_line", "next_action"):
        raw = str(exec_summary.get(field_name) or "").strip()
        if not raw:
            continue
        out.append(
            PolishItem(
                key=_hash_item(f"exec.{field_name}", raw, model),
                role=f"exec.{field_name}",
                raw_text=raw,
                context=f"executive summary {field_name} — top of PM brief",
            )
        )
    return out


def _customer_answer_slot_items(
    slots: list[dict[str, Any]], model: str
) -> list[PolishItem]:
    out: list[PolishItem] = []
    for s in slots:
        slot_id = str(s.get("slot_id") or s.get("rule_id") or "")
        q = str(s.get("question_text") or s.get("question") or "").strip()
        if not q:
            continue
        out.append(
            PolishItem(
                key=_hash_item(f"answer_slot.{slot_id}", q, model),
                role="answer_slot.question",
                raw_text=q,
                context=f"customer answer slot for {slot_id}",
            )
        )
    return out


def _apply_results_to_gaps(
    gaps: list[GapCard], results: dict[str, PolishResult], model: str
) -> list[GapCard]:
    out: list[GapCard] = []
    for g in gaps:
        msg = g.message
        q = g.suggested_open_question
        if msg:
            r = results.get(_hash_item(f"gap.message.{g.rule_id}", msg, model))
            if r and not r.used_fallback:
                msg = r.polished_text
        if q:
            r = results.get(_hash_item(f"gap.question.{g.rule_id}", q, model))
            if r and not r.used_fallback:
                q = r.polished_text
        out.append(replace(g, message=msg, suggested_open_question=q))
    return out


def _apply_results_to_risks(
    risks: list[dict[str, Any]], results: dict[str, PolishResult], model: str
) -> list[dict[str, Any]]:
    """Apply polish results to risk rows with sibling-field collision guard.

    v46.3: a polish-stage failure mode was observed on R-04 where the
    polished ``description`` was set to the same prose as ``mitigation``
    (model collapsed the two slots into one).  This guard reverts the
    polished value to its raw form whenever the polished text would
    duplicate (or be contained in) the sibling field — eliminates the
    silent collision the validator's guarded-token check can't catch
    because mitigations rarely carry $/IDs/dates.

    A future training-data signal (closed deals + PM thumbs) would let a
    small reranker decide which slot a polished sentence belongs in;
    until then the validator is the safety net.
    """
    def _norm(s: str) -> str:
        return " ".join((s or "").lower().split())

    polished: list[dict[str, Any]] = []
    for r in risks:
        rid = str(r.get("risk_id") or "")
        new = dict(r)
        desc_raw = r.get("description") or ""
        mit_raw = r.get("mitigation") or ""

        desc_polished: str | None = None
        if desc_raw:
            res = results.get(_hash_item(f"risk.description.{rid}", desc_raw, model))
            if res and not res.used_fallback:
                desc_polished = res.polished_text

        mit_polished: str | None = None
        if mit_raw:
            res = results.get(_hash_item(f"risk.mitigation.{rid}", mit_raw, model))
            if res and not res.used_fallback:
                mit_polished = res.polished_text

        # Collision guard — applies to whichever polished value duplicated
        # the sibling slot (raw OR polished form).  Falls back to the raw
        # value for the offending field; keeps the other side polished.
        desc_n = _norm(desc_polished) if desc_polished is not None else _norm(desc_raw)
        mit_n = _norm(mit_polished) if mit_polished is not None else _norm(mit_raw)
        desc_raw_n = _norm(desc_raw)
        mit_raw_n = _norm(mit_raw)

        if desc_polished is not None and desc_n and (desc_n == mit_n or desc_n == mit_raw_n):
            # Polished description matches the mitigation prose — revert.
            desc_polished = None
        if mit_polished is not None and mit_n and (mit_n == desc_n or mit_n == desc_raw_n):
            # Polished mitigation matches the description prose — revert.
            mit_polished = None

        new["description"] = desc_polished if desc_polished is not None else desc_raw
        new["mitigation"] = mit_polished if mit_polished is not None else mit_raw
        polished.append(new)
    return polished


def _apply_results_to_exec(
    exec_summary: dict[str, Any], results: dict[str, PolishResult], model: str
) -> dict[str, Any]:
    out = dict(exec_summary)
    for field_name in ("headline", "health_line", "next_action"):
        raw = out.get(field_name) or ""
        if not raw:
            continue
        r = results.get(_hash_item(f"exec.{field_name}", raw, model))
        if r and not r.used_fallback:
            out[field_name] = r.polished_text
    return out


def _apply_results_to_slots(
    slots: list[dict[str, Any]], results: dict[str, PolishResult], model: str
) -> list[dict[str, Any]]:
    polished: list[dict[str, Any]] = []
    for s in slots:
        slot_id = str(s.get("slot_id") or s.get("rule_id") or "")
        new = dict(s)
        for key in ("question_text", "question"):
            raw = s.get(key) or ""
            if raw:
                r = results.get(_hash_item(f"answer_slot.{slot_id}", raw, model))
                if r and not r.used_fallback:
                    new[key] = r.polished_text
                    break
        polished.append(new)
    return polished


@dataclass(frozen=True)
class PolishReport:
    """Audit of what the polish stage touched.

    Used by the orchestrator's pipeline_log + the UI's "polished by
    AI on YYYY-MM-DD" provenance pill.
    """

    items_total: int
    items_polished: int
    items_fallback: int
    items_cached: int
    model: str
    elapsed_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "items_total": self.items_total,
            "items_polished": self.items_polished,
            "items_fallback": self.items_fallback,
            "items_cached": self.items_cached,
            "model": self.model,
            "elapsed_ms": self.elapsed_ms,
        }


def _one_line_polish_items(one_line: str, model: str) -> list[PolishItem]:
    raw = (one_line or "").strip()
    if not raw:
        return []
    return [
        PolishItem(
            key=_hash_item("one_line_summary", raw, model),
            role="one_line_summary",
            raw_text=raw,
            context="single-sentence deal summary shown at the top of PM brief",
        )
    ]


def _apply_one_line_result(
    one_line: str, results: dict[str, PolishResult], model: str
) -> str:
    raw = (one_line or "").strip()
    if not raw:
        return one_line
    r = results.get(_hash_item("one_line_summary", raw, model))
    if r and not r.used_fallback:
        return r.polished_text
    return one_line


# Phase ordinal for the polish_stage telemetry block. Phase 91 is the
# PM-voice polish pass that runs after Phase 90 (PMHandoff build);
# pinned here so the telemetry field is stable across builds.
_POLISH_PHASE = 91


def _polish_stage_telemetry(
    *,
    phase: int,
    model: str,
    polished_count: int,
    fallback_count: int,
    validator_enforced: bool,
) -> dict[str, Any]:
    """Shape the polish_stage telemetry dict — single source of truth so
    the no-op path and the real-LLM path emit identical keys/order."""
    return {
        "phase": phase,
        "model": model,
        "polished_count": polished_count,
        "fallback_count": fallback_count,
        "validator_enforced": validator_enforced,
    }


def polish_pm_handoff(
    handoff: PMHandoff,
    *,
    chat_client: ChatClient | None,
    model: str = DEFAULT_MODEL,
    cache_path: Path | None = None,
) -> tuple[PMHandoff, PolishReport]:
    """Apply LLM polish to a built PMHandoff. Returns (polished, report).

    Cache path defaults to ``$ORBITBRIEF_POLISH_CACHE`` or
    ``.orbitbrief_polish_cache.jsonl`` next to the case directory.

    Polished fields:

    * ``one_line_summary`` (single sentence shown at top of brief)
    * ``gaps[].message`` and ``gaps[].suggested_open_question``
    * ``customer_questions[].message`` and
      ``customer_questions[].suggested_open_question``
    * ``risk_register[].description`` and ``risk_register[].mitigation``
    * ``executive_summary.headline``, ``health_line``, ``next_action``
    * ``customer_answer_slots[].question_text``

    Atom-text fields (``urgency_signals[].snippet``,
    ``exclusions[].text``, ``responsibilities[].text``,
    ``compliance_callouts[].snippet``) are intentionally NOT polished —
    polishing them would break the verbatim-citation property the
    system relies on for source replay.

    When ``chat_client`` is ``None`` polish runs as a no-op: the
    returned handoff is unchanged but the ``polish_stage`` telemetry
    block is populated with ``model="none"``, zero counts, and
    ``validator_enforced=false`` so downstream observability can
    distinguish "didn't run" from "ran with zero items".
    """
    import time

    started = time.monotonic()

    # No-op path: no LLM client supplied. Emit a polish_stage
    # telemetry block but skip the polish itself. PolishReport mirrors
    # the same counters so callers reading either surface get
    # consistent values.
    if chat_client is None:
        no_op_telemetry = _polish_stage_telemetry(
            phase=_POLISH_PHASE,
            model="none",
            polished_count=0,
            fallback_count=0,
            validator_enforced=False,
        )
        no_op_handoff = replace(handoff, polish_stage=no_op_telemetry)
        no_op_report = PolishReport(
            items_total=0,
            items_polished=0,
            items_fallback=0,
            items_cached=0,
            model="none",
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
        return no_op_handoff, no_op_report

    cache: PolishCache | None = None
    if cache_path is not None:
        cache = PolishCache(path=Path(cache_path))
    else:
        env_path = os.environ.get("ORBITBRIEF_POLISH_CACHE")
        if env_path:
            cache = PolishCache(path=Path(env_path))

    # Collect items across every field that benefits from polish
    items: list[PolishItem] = []
    items.extend(_one_line_polish_items(handoff.one_line_summary, model))
    items.extend(_gap_polish_items(handoff.gaps, model))
    items.extend(_gap_polish_items(handoff.customer_questions, model))
    items.extend(_risk_polish_items(handoff.risk_register, model))
    if handoff.executive_summary:
        items.extend(_exec_polish_items(handoff.executive_summary, model))
    items.extend(_customer_answer_slot_items(handoff.customer_answer_slots, model))

    # De-duplicate by key — same raw text in multiple slots polishes once
    by_key: dict[str, PolishItem] = {}
    for it in items:
        by_key.setdefault(it.key, it)
    deduped = list(by_key.values())

    items_cached = 0
    if cache is not None:
        for it in deduped:
            if cache.get(it.key) is not None:
                items_cached += 1

    results = polish_items(
        deduped, chat_client=chat_client, model=model, cache=cache
    )

    items_polished = sum(1 for r in results.values() if not r.used_fallback)
    items_fallback = sum(1 for r in results.values() if r.used_fallback)

    polished_one_line = _apply_one_line_result(
        handoff.one_line_summary, results, model
    )
    polished_gaps = _apply_results_to_gaps(handoff.gaps, results, model)
    polished_customer_qs = _apply_results_to_gaps(handoff.customer_questions, results, model)
    polished_risks = _apply_results_to_risks(handoff.risk_register, results, model)
    polished_exec = (
        _apply_results_to_exec(handoff.executive_summary, results, model)
        if handoff.executive_summary
        else handoff.executive_summary
    )
    polished_slots = _apply_results_to_slots(handoff.customer_answer_slots, results, model)

    # validator_enforced reflects whether _validate_polish was the
    # gate that decided cache-vs-LLM. polish_items always runs the
    # validator on LLM output, so this is True whenever LLM polish
    # actually ran for at least one item.
    polish_stage = _polish_stage_telemetry(
        phase=_POLISH_PHASE,
        model=model,
        polished_count=items_polished,
        fallback_count=items_fallback,
        validator_enforced=bool(deduped),
    )

    polished = replace(
        handoff,
        one_line_summary=polished_one_line,
        gaps=polished_gaps,
        customer_questions=polished_customer_qs,
        risk_register=polished_risks,
        executive_summary=polished_exec,
        customer_answer_slots=polished_slots,
        polish_stage=polish_stage,
    )

    elapsed_ms = int((time.monotonic() - started) * 1000)
    report = PolishReport(
        items_total=len(deduped),
        items_polished=items_polished,
        items_fallback=items_fallback,
        items_cached=items_cached,
        model=model,
        elapsed_ms=elapsed_ms,
    )
    return polished, report


__all__ = [
    "DEFAULT_MODEL",
    "PolishCache",
    "PolishItem",
    "PolishReport",
    "PolishResult",
    "polish_items",
    "polish_pm_handoff",
]
