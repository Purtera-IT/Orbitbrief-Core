"""Unit tests for the PM-voice polish pass (pm_handoff/polish.py).

The polish stage is the most likely place to corrupt or hallucinate
facts in PMHandoff text. These tests pin the contract:

* validator rejects polish that drops a guarded token
* cache hit short-circuits the LLM call
* LLM failure falls back to raw — never blocks
* batched calls return a result per item
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from orbitbrief_core.inference.client import ChatMessage, InferenceError
from orbitbrief_core.pm_handoff.models import GapCard, PMHandoff
from orbitbrief_core.pm_handoff.polish import (
    PolishCache,
    PolishItem,
    _build_polish_prompt,
    _hash_item,
    _parse_polish_response,
    _validate_polish,
    polish_items,
    polish_pm_handoff,
)


@dataclass
class _StubChatClient:
    """Records calls + returns canned text per call."""

    canned: list[str]
    calls: list[tuple[list[ChatMessage], dict[str, Any]]] = None

    def __post_init__(self) -> None:
        self.calls = []

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> str:
        self.calls.append((list(messages), {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": response_format,
        }))
        if not self.canned:
            raise InferenceError("stub: no canned responses left")
        return self.canned.pop(0)

    def complete_with_usage(self, *a: Any, **kw: Any) -> Any:  # pragma: no cover
        raise NotImplementedError


class _AlwaysRaisesClient:
    def complete(self, *a: Any, **kw: Any) -> str:
        raise InferenceError("simulated outage")

    def complete_with_usage(self, *a: Any, **kw: Any) -> Any:  # pragma: no cover
        raise InferenceError("simulated outage")


# ────────────────────────────────────────────────────────────────────
# _validate_polish — guarded tokens must survive
# ────────────────────────────────────────────────────────────────────


def test_validate_keeps_money_token() -> None:
    raw = "Cisco quote shows $51,740 for ATL-HQ"
    polished = "Cisco quoted $51,740 for ATL-HQ."
    assert _validate_polish(raw, polished)


def test_validate_rejects_dropped_money() -> None:
    raw = "Cisco quote shows $51,740 for ATL-HQ"
    polished = "Cisco quoted a number for ATL-HQ."
    assert not _validate_polish(raw, polished)


def test_validate_rejects_dropped_rule_id() -> None:
    raw = "Controller scope R-WIFI-001 needs resolution before SOW lock"
    polished = "Controller scope needs resolution before SOW lock."
    assert not _validate_polish(raw, polished)


def test_validate_keeps_date() -> None:
    raw = "Cutover begins 2026-07-27 per kickoff agreement"
    polished = "Cutover starts 2026-07-27 per kickoff agreement."
    assert _validate_polish(raw, polished)


def test_validate_rejects_dropped_date() -> None:
    raw = "Cutover begins 2026-07-27 per kickoff agreement"
    polished = "Cutover starts in late July."
    assert not _validate_polish(raw, polished)


def test_validate_rejects_too_long() -> None:
    raw = "AP count is 52."
    polished = "AP count is 52. " * 30  # 30x expansion
    assert not _validate_polish(raw, polished)


def test_validate_rejects_too_short() -> None:
    raw = "Controller scope for the Airport Annex needs confirmation."
    polished = "."  # nearly empty
    assert not _validate_polish(raw, polished)


def test_validate_rejects_title_cased_site_key() -> None:
    """parser-os uses lowercase 'atl hq' as a canonical entity key —
    title-casing breaks downstream joins. The validator must reject."""
    raw = "Site access at atl hq needs confirmation by 2026-05-30."
    bad = "Site access at Atlanta HQ needs confirmation by 2026-05-30."
    assert not _validate_polish(raw, bad)


def test_validate_keeps_lowercase_site_key() -> None:
    raw = "Site access at atl hq needs confirmation by 2026-05-30."
    good = "Confirm site access at atl hq by 2026-05-30."
    assert _validate_polish(raw, good)


def test_validate_rejects_dropped_part_number() -> None:
    raw = "Cisco c9166d1 lead time 6-8 weeks; PO must clear by 2026-05-30."
    bad = "Cisco access points have a 6-8 week lead time; PO must clear by 2026-05-30."
    assert not _validate_polish(raw, bad)


def test_validate_keeps_part_number() -> None:
    raw = "Cisco c9166d1 lead time 6-8 weeks; PO must clear by 2026-05-30."
    good = "Cisco c9166d1 lead time is 6-8 weeks; PO must clear by 2026-05-30."
    assert _validate_polish(raw, good)


def test_validate_rejects_lowercased_hyphen_id() -> None:
    """ATL-West (canonical mixed-case) lowercased to atl-west breaks joins."""
    raw = "PoE budget at ATL-West appears undersized for 27 access points."
    bad = "PoE budget at atl-west appears undersized for 27 access points."
    assert not _validate_polish(raw, bad)


def test_validate_keeps_hyphen_id_case() -> None:
    raw = "PoE budget at ATL-West appears undersized for 27 access points."
    good = "Address PoE budget at ATL-West for 27 access points."
    assert _validate_polish(raw, good)


def test_validate_rejects_lowercased_title_phrase() -> None:
    """'Airport Logistics Annex' is the canonical proper noun. \
    Lowercasing breaks downstream display + joins."""
    raw = "Confirm site access for Airport Logistics Annex."
    bad = "Confirm site access for airport logistics annex."
    assert not _validate_polish(raw, bad)


def test_validate_keeps_title_phrase_case() -> None:
    raw = "Confirm site access for Airport Logistics Annex."
    good = "Confirm site access for Airport Logistics Annex by 2026-05-30."
    # Even adding a date is fine — the title-phrase is preserved verbatim
    assert _validate_polish(raw, good)


def test_validate_keeps_net_terms() -> None:
    raw = "Align net payment terms between RFP (Net-30) and signed quote (Net-45)."
    good = "Align net payment terms between RFP (Net-30) and signed quote (Net-45)."
    assert _validate_polish(raw, good)


def test_validate_rejects_dropped_net_terms() -> None:
    raw = "Align net payment terms between RFP (Net-30) and signed quote (Net-45)."
    bad = "Align net payment terms between RFP and signed quote."
    assert not _validate_polish(raw, bad)


# ────────────────────────────────────────────────────────────────────
# _parse_polish_response — robust to think tokens + trailing chatter
# ────────────────────────────────────────────────────────────────────


def test_parse_strips_think_block() -> None:
    raw = """<think>OK let me think about this carefully</think>
{"items": [{"key": "a1", "polished": "Confirm controller scope."}]}"""
    out = _parse_polish_response(raw)
    assert out == {"a1": "Confirm controller scope."}


def test_parse_handles_trailing_prose() -> None:
    raw = '{"items": [{"key": "x", "polished": "Yes."}]}\n\nThat\'s the answer.'
    out = _parse_polish_response(raw)
    assert out == {"x": "Yes."}


def test_parse_returns_empty_on_garbage() -> None:
    assert _parse_polish_response("") == {}
    assert _parse_polish_response("not json") == {}
    assert _parse_polish_response("{") == {}


# ────────────────────────────────────────────────────────────────────
# _hash_item — stable, sensitive to inputs
# ────────────────────────────────────────────────────────────────────


def test_hash_is_stable() -> None:
    assert _hash_item("gap.message", "hello", "qwen3:14b") == _hash_item(
        "gap.message", "hello", "qwen3:14b"
    )


def test_hash_changes_with_role() -> None:
    assert _hash_item("gap.message", "hello", "qwen3:14b") != _hash_item(
        "gap.question", "hello", "qwen3:14b"
    )


def test_hash_changes_with_text() -> None:
    a = _hash_item("gap.message", "hello", "qwen3:14b")
    b = _hash_item("gap.message", "world", "qwen3:14b")
    assert a != b


def test_hash_changes_with_model() -> None:
    assert _hash_item("g", "h", "qwen3:14b") != _hash_item("g", "h", "qwen3:32b")


# ────────────────────────────────────────────────────────────────────
# PolishCache — file-backed, durable across instances
# ────────────────────────────────────────────────────────────────────


def test_cache_round_trip(tmp_path: Path) -> None:
    cache = PolishCache(path=tmp_path / "polish.jsonl")
    assert cache.get("k1") is None
    cache.put("k1", "polished text")
    assert cache.get("k1") == "polished text"
    # Reload from disk
    cache2 = PolishCache(path=tmp_path / "polish.jsonl")
    assert cache2.get("k1") == "polished text"


def test_cache_appends_on_disk(tmp_path: Path) -> None:
    cache = PolishCache(path=tmp_path / "polish.jsonl")
    cache.put("a", "x")
    cache.put("b", "y")
    lines = (tmp_path / "polish.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    rows = [json.loads(line) for line in lines]
    assert {r["key"] for r in rows} == {"a", "b"}


# ────────────────────────────────────────────────────────────────────
# polish_items — happy path, cache, fallback
# ────────────────────────────────────────────────────────────────────


def test_polish_items_uses_cache(tmp_path: Path) -> None:
    cache = PolishCache(path=tmp_path / "p.jsonl")
    key = _hash_item("gap.message", "Controller R-WIFI-001 needs review", "qwen3:14b")
    cache.put(key, "Confirm controller scope (R-WIFI-001).")
    items = [
        PolishItem(
            key=key,
            role="gap.message",
            raw_text="Controller R-WIFI-001 needs review",
        )
    ]
    client = _StubChatClient(canned=[])  # never called
    out = polish_items(items, chat_client=client, model="qwen3:14b", cache=cache)
    assert len(out) == 1
    assert out[key].polished_text == "Confirm controller scope (R-WIFI-001)."
    assert not out[key].used_fallback
    assert client.calls == []  # zero LLM calls


def test_polish_items_falls_back_on_llm_failure() -> None:
    items = [
        PolishItem(
            key="k1",
            role="risk.description",
            raw_text="Cisco lead time is 6-8 weeks",
        )
    ]
    out = polish_items(
        items, chat_client=_AlwaysRaisesClient(), model="qwen3:14b", cache=None
    )
    assert out["k1"].used_fallback is True
    assert out["k1"].polished_text == "Cisco lead time is 6-8 weeks"


def test_polish_items_falls_back_on_dropped_token() -> None:
    """LLM returns text missing the guarded $X token on both attempts → fallback.

    The retry path gives the model one more chance with a stricter
    prompt. If the second attempt also drops the token, fall back to raw.
    """
    raw = "BOM total is $51,740 for ATL-HQ"
    item = PolishItem(
        key="k1",
        role="risk.description",
        raw_text=raw,
    )
    # Both attempts drop the $ amount
    bad = json.dumps({"items": [{"key": "k1", "polished": "BOM total for ATL-HQ"}]})
    client = _StubChatClient(canned=[bad, bad])
    out = polish_items([item], chat_client=client, model="qwen3:14b", cache=None)
    assert out["k1"].used_fallback is True
    assert out["k1"].polished_text == raw
    # Both attempts were made — first attempt + retry
    assert len(client.calls) == 2


def test_polish_items_retry_succeeds_after_initial_failure() -> None:
    """First LLM attempt drops a token; retry preserves it → polish wins."""
    raw = "BOM total is $51,740 for ATL-HQ"
    item = PolishItem(
        key="k1",
        role="risk.description",
        raw_text=raw,
    )
    bad = json.dumps({"items": [{"key": "k1", "polished": "BOM total for ATL-HQ"}]})
    good = json.dumps(
        {"items": [{"key": "k1", "polished": "BOM total is $51,740 for ATL-HQ."}]}
    )
    client = _StubChatClient(canned=[bad, good])
    out = polish_items([item], chat_client=client, model="qwen3:14b", cache=None)
    assert out["k1"].used_fallback is False
    assert "$51,740" in out["k1"].polished_text
    assert len(client.calls) == 2  # one bad + one retry that succeeded
    # Retry call carries the stricter prompt suffix
    retry_messages = client.calls[1][0]
    retry_system = retry_messages[0].content
    assert "PRIOR ATTEMPT FAILED" in retry_system


def test_polish_items_happy_path() -> None:
    raw = "Controller R-WIFI-001 must clarify topology"
    item = PolishItem(
        key="k1",
        role="gap.message",
        raw_text=raw,
    )
    polished = "Confirm controller topology (R-WIFI-001) before SOW lock."
    canned = json.dumps({"items": [{"key": "k1", "polished": polished}]})
    client = _StubChatClient(canned=[canned])
    out = polish_items([item], chat_client=client, model="qwen3:14b", cache=None)
    assert out["k1"].used_fallback is False
    assert out["k1"].polished_text == polished


def test_polish_items_batches_requests() -> None:
    items = [
        PolishItem(
            key=f"k{i}",
            role="gap.message",
            raw_text=f"Item {i} mentions R-RULE-{i:03d} as a placeholder fact",
        )
        for i in range(25)
    ]
    canned = [
        json.dumps(
            {
                "items": [
                    {
                        "key": it.key,
                        "polished": it.raw_text,  # echo raw — passes validator
                    }
                    for it in items[i : i + 12]
                ]
            }
        )
        for i in range(0, 25, 12)
    ]
    client = _StubChatClient(canned=list(canned))
    out = polish_items(items, chat_client=client, model="qwen3:14b", cache=None)
    assert len(out) == 25
    # 25 items / 12 per batch = 3 batches
    assert len(client.calls) == 3


# ────────────────────────────────────────────────────────────────────
# polish_pm_handoff — end-to-end, mutates the right fields
# ────────────────────────────────────────────────────────────────────


def _make_minimal_handoff() -> PMHandoff:
    return PMHandoff(
        case_id="TEST_CASE",
        status="red",
        status_label="Not SOW-ready: 1 blocker question(s) remain",
        one_line_summary="Test deal one-liner",
        metrics={"atom_count": 10},
        gaps=[
            GapCard(
                rule_id="R-WIFI-001",
                domain_id="wireless",
                domain_label="Wireless",
                label="Controller scope",
                severity="blocker",
                message="Controller deployment topology unresolved for site Airport Logistics Annex",
                suggested_open_question="Confirm whether Airport Logistics Annex requires a dedicated WLC",
            )
        ],
        customer_questions=[],
        risk_register=[
            {
                "risk_id": "RSK-001",
                "description": "C9166D1 lead time 6-8 weeks per Cisco distributor confirmation",
                "mitigation": "Place PO no later than 2026-05-30 to hit cutover",
                "severity": "high",
            }
        ],
        executive_summary={
            "headline": "TEST_CASE: deal worth $1,847,250 across 3 confirmed site(s)",
            "health_line": "Status is RED: 1 blocker and 0 warnings need PM resolution before SOW lock.",
            "next_action": "Resolve the blocker checklist below and confirm the customer clarifications email starter.",
        },
        customer_answer_slots=[],
    )


def test_polish_pm_handoff_polishes_gaps_and_risks() -> None:
    handoff = _make_minimal_handoff()

    # Pre-build canned responses keyed by the items we know polish will request.
    # Polish dedupes by hash; the call shape depends on internal hashing, so
    # we route through a stub that always polishes by echoing through a
    # "preserve everything, just append a period" transform.
    def _echo_response(items: list[dict[str, Any]]) -> str:
        rows = []
        for it in items:
            rows.append({"key": it["key"], "polished": it["raw"]})
        return json.dumps({"items": rows})

    class _EchoClient:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, messages, *, model, **kw):  # type: ignore[no-untyped-def]
            self.calls += 1
            user = next(m.content for m in messages if m.role == "user")
            # Parse out keys + raw text from our own prompt for echo-back
            items: list[dict[str, Any]] = []
            current: dict[str, Any] = {}
            for line in user.splitlines():
                line = line.strip()
                if line.startswith("- key:"):
                    if current:
                        items.append(current)
                    current = {"key": line.split(":", 1)[1].strip().strip('"')}
                elif line.startswith("raw:"):
                    current["raw"] = json.loads(line.split(":", 1)[1].strip())
            if current:
                items.append(current)
            return _echo_response(items)

        def complete_with_usage(self, *a, **kw):
            raise NotImplementedError

    polished, report = polish_pm_handoff(
        handoff, chat_client=_EchoClient(), model="qwen3:14b", cache_path=None
    )
    # All raw text is echoed verbatim → validator accepts → none fall back
    assert report.items_total > 0
    assert report.items_fallback == 0
    # Polished output preserves the original facts (echo client → identical text)
    assert "Airport Logistics Annex" in polished.gaps[0].message
    assert "$1,847,250" in polished.executive_summary["headline"]
    assert "2026-05-30" in polished.risk_register[0]["mitigation"]
    # The risk description preserves the part number, which the
    # validator must guard.
    assert "C9166D1" in polished.risk_register[0]["description"]


def test_polish_pm_handoff_handles_llm_outage_gracefully() -> None:
    handoff = _make_minimal_handoff()
    polished, report = polish_pm_handoff(
        handoff, chat_client=_AlwaysRaisesClient(), model="qwen3:14b", cache_path=None
    )
    # Everything falls back to raw text
    assert report.items_fallback == report.items_total
    assert report.items_polished == 0
    # Raw text is preserved unchanged
    assert (
        polished.gaps[0].message
        == "Controller deployment topology unresolved for site Airport Logistics Annex"
    )
    assert polished.risk_register[0]["description"].startswith("C9166D1")


def test_polish_pm_handoff_uses_persistent_cache(tmp_path: Path) -> None:
    handoff = _make_minimal_handoff()
    cache_path = tmp_path / "polish.jsonl"

    # First run: real LLM. Use an _EchoClient like above.
    class _EchoClient:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, messages, *, model, **kw):
            self.calls += 1
            user = next(m.content for m in messages if m.role == "user")
            items = []
            current = {}
            for line in user.splitlines():
                line = line.strip()
                if line.startswith("- key:"):
                    if current:
                        items.append(current)
                    current = {"key": line.split(":", 1)[1].strip().strip('"')}
                elif line.startswith("raw:"):
                    current["raw"] = json.loads(line.split(":", 1)[1].strip())
            if current:
                items.append(current)
            return json.dumps(
                {"items": [{"key": it["key"], "polished": it["raw"]} for it in items]}
            )

        def complete_with_usage(self, *a, **kw):
            raise NotImplementedError

    client1 = _EchoClient()
    _, report1 = polish_pm_handoff(
        handoff, chat_client=client1, model="qwen3:14b", cache_path=cache_path
    )
    assert client1.calls > 0
    assert report1.items_cached == 0

    # Second run: a client that would error if invoked. Cache should
    # cover every item.
    client2 = _AlwaysRaisesClient()
    _, report2 = polish_pm_handoff(
        handoff, chat_client=client2, model="qwen3:14b", cache_path=cache_path
    )
    assert report2.items_cached == report1.items_total
    assert report2.items_fallback == 0
