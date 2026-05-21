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

# Default model. Mirrors the brain runner so re-using the same Ollama
# instance is friction-free. Caller can override.
DEFAULT_MODEL = "qwen3:14b"

# Maximum items per batched LLM call. Tuned for the qwen3:14b
# 40 K-token context window: each item is ~120 tokens system + ~300
# tokens raw input + ~200 tokens completion. 12 items × ~620 tokens
# = ~7.4 K — well under the 8192 completion budget.
_BATCH_SIZE = 12

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
    """Tokens the polished output must preserve verbatim."""
    out: set[str] = set()
    for rx in (_MONEY_RE, _PCT_RE, _ID_RE, _DATE_RE):
        out.update(rx.findall(raw_text))
    return out


def _validate_polish(raw_text: str, polished_text: str) -> bool:
    """Reject the polish if it dropped a guarded token or got absurd.

    Rules:
    1. Every guarded token in raw must appear in polished.
    2. Polished length ≤ 3× raw length (model didn't go wild).
    3. Polished length ≥ 0.4× raw length (model didn't truncate to nothing).
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

_SYSTEM_PROMPT = """You are a senior project manager at Purtera-IT polishing internal scope text \
for a customer-facing pre-SOW review. /no_think

Your only job is to REWRITE the supplied raw bullets in a clear, decisive, \
PM-email voice. You may NOT:
- invent new facts, sites, names, dollar amounts, dates, IDs, or counts
- drop any dollar amount, percentage, date, rule ID (e.g. R-WIFI-001), \
atom id (atm_*, cmp_*), or stakeholder name that appears in the raw
- pad with hedging language ("we should consider", "perhaps", "it may be")
- write more than two sentences per item; many should be one sentence

You MAY:
- replace bureaucratic phrasing with plain English
- promote a single verb to the front of the sentence
- add a citation suffix like "(per <source>)" only if the raw text \
already names the source
- convert a noun-heavy fragment into a verb-led sentence

Output is JSON only. Do not include reasoning or markdown."""


def _build_polish_prompt(items: list[PolishItem]) -> tuple[str, str]:
    """Return (system, user) prompt for one batch."""
    user_lines: list[str] = [
        "Rewrite each item below in PM-email voice. Output JSON of the form:",
        '{"items": [{"key": "<key>", "polished": "<one-or-two-sentence rewrite>"}, ...]}',
        "",
        "Preserve every dollar amount, percentage, date, ID token, and named entity exactly as written.",
        "Do not add facts that are not in the raw.",
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
    return _SYSTEM_PROMPT, "\n".join(user_lines)


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
    * cache miss → batched LLM call. On success + validation, the
      polish is cached. On failure, returns raw with
      ``used_fallback=True``.
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
        sys_prompt, user_prompt = _build_polish_prompt(batch)
        messages = [
            ChatMessage(role="system", content=sys_prompt),
            ChatMessage(role="user", content=user_prompt),
        ]
        try:
            response_text = chat_client.complete(
                messages,
                model=model,
                temperature=0.2,
                max_tokens=_MAX_OUTPUT_TOKENS,
                response_format={"type": "json_object"},
            )
        except InferenceError:
            for it in batch:
                out[it.key] = PolishResult(it.key, it.raw_text, used_fallback=True)
            continue
        polished_map = _parse_polish_response(response_text)
        for it in batch:
            polished = polished_map.get(it.key, "").strip()
            if not polished or not _validate_polish(it.raw_text, polished):
                out[it.key] = PolishResult(it.key, it.raw_text, used_fallback=True)
                continue
            if cache is not None:
                cache.put(it.key, polished)
            out[it.key] = PolishResult(it.key, polished, used_fallback=False)
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
    polished: list[dict[str, Any]] = []
    for r in risks:
        rid = str(r.get("risk_id") or "")
        new = dict(r)
        desc = r.get("description") or ""
        if desc:
            res = results.get(_hash_item(f"risk.description.{rid}", desc, model))
            if res and not res.used_fallback:
                new["description"] = res.polished_text
        mit = r.get("mitigation") or ""
        if mit:
            res = results.get(_hash_item(f"risk.mitigation.{rid}", mit, model))
            if res and not res.used_fallback:
                new["mitigation"] = res.polished_text
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


def polish_pm_handoff(
    handoff: PMHandoff,
    *,
    chat_client: ChatClient,
    model: str = DEFAULT_MODEL,
    cache_path: Path | None = None,
) -> tuple[PMHandoff, PolishReport]:
    """Apply LLM polish to a built PMHandoff. Returns (polished, report).

    Cache path defaults to ``$ORBITBRIEF_POLISH_CACHE`` or
    ``.orbitbrief_polish_cache.jsonl`` next to the case directory.
    """
    import time

    started = time.monotonic()
    cache: PolishCache | None = None
    if cache_path is not None:
        cache = PolishCache(path=Path(cache_path))
    else:
        env_path = os.environ.get("ORBITBRIEF_POLISH_CACHE")
        if env_path:
            cache = PolishCache(path=Path(env_path))

    # Collect items across every field that benefits from polish
    items: list[PolishItem] = []
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

    polished_gaps = _apply_results_to_gaps(handoff.gaps, results, model)
    polished_customer_qs = _apply_results_to_gaps(handoff.customer_questions, results, model)
    polished_risks = _apply_results_to_risks(handoff.risk_register, results, model)
    polished_exec = (
        _apply_results_to_exec(handoff.executive_summary, results, model)
        if handoff.executive_summary
        else handoff.executive_summary
    )
    polished_slots = _apply_results_to_slots(handoff.customer_answer_slots, results, model)

    polished = replace(
        handoff,
        gaps=polished_gaps,
        customer_questions=polished_customer_qs,
        risk_register=polished_risks,
        executive_summary=polished_exec,
        customer_answer_slots=polished_slots,
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
