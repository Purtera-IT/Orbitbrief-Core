"""Exec-summary head — replaces the degenerate template headline
("<uuid>: deal across no confirmed...") with a grounded, business-facing summary.

Generated from STRUCTURED deal facts (domain, value, readiness, blockers) via the
same chat client the brains use — so it inherits the wired Mac/Ollama backend with
no new dependency. Writes ``executive_summary.{headline, health_line, next_action}``
— the exact fields the UI's ExecutiveSummaryStrip reads.

Graceful: missing client / bad JSON / any error -> handoff unchanged.
"""
from __future__ import annotations

import dataclasses
import json
import re
from typing import Any

from orbitbrief_core.inference.client import ChatMessage

SYSTEM = (
    "You write the executive summary line of a B2B managed-services deal brief for a sales engineer. "
    "Given structured deal facts, write a TIGHT, specific summary. Rules: NO deal UUIDs, NO placeholder "
    "text, NO generic 'deal across no confirmed' filler, and NEVER mention internal parser metrics like "
    "'atoms', 'packets', or 'edges'. Use BUSINESS language: deal value in $, domain, scale, readiness, "
    "blocker count. Ground ONLY in the facts. Return STRICT JSON "
    '{"headline":str (<=18 words: what the deal is + readiness), '
    '"health_line":str (1 sentence on the biggest risk/blocker theme), '
    '"next_action":str (the single most important next step)}.'
)


def _facts(handoff: Any, envelope: dict) -> dict:
    s = envelope.get("summary") or {}
    sr = envelope.get("service_routing") or {}
    vit = envelope.get("project_vitals") or {}
    rd = envelope.get("sow_readiness_scorecard") or {}
    money = (((envelope.get("pm_dashboard") or {}).get("money_summary") or {}).get("total"))
    fin = (envelope.get("deal_financials") or {}).get("overall_total")
    gaps = list(getattr(handoff, "gaps", []) or [])
    def _sev(g):
        return getattr(g, "severity", None) or (g.get("severity") if isinstance(g, dict) else None)
    def _lbl(g):
        return getattr(g, "label", None) or (g.get("label") if isinstance(g, dict) else None)
    blockers = sum(1 for g in gaps if _sev(g) == "blocker")
    f = {
        "domain": sr.get("primary"),
        "vitals_100": vit.get("score_100"), "vitals_band": vit.get("band"),
        "readiness": rd.get("readiness_score"), "grade": rd.get("grade"),
        "deal_total_usd": fin or money,
        "sites": (envelope.get("scope_truth") or {}).get("site_count") or None,
        "gap_count": len(gaps), "blocker_count": blockers,
        "top_gaps": [_lbl(g) for g in gaps[:5] if _lbl(g)],
    }
    return {k: v for k, v in f.items() if v is not None}


def _parse(text: str) -> dict | None:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        d = json.loads(re.sub(r",\s*([}\]])", r"\1", m.group(0)))
    except Exception:
        return None
    return d if isinstance(d, dict) and d.get("headline") else None


def _safe_headline(f: dict) -> str:
    bits = []
    if f.get("domain"):
        bits.append(str(f["domain"]).replace("_", " ").title())
    if f.get("deal_total_usd"):
        bits.append(f"${int(f['deal_total_usd']):,}")
    tail = f"readiness {f.get('grade', 'unknown')}"
    if f.get("blocker_count"):
        tail += f", {f['blocker_count']} blocker(s)"
    return (" ".join(bits) + " deal — " + tail).strip(" —") or "Deal brief"


def apply_exec_summary(handoff: Any, envelope: dict, *, chat_client: Any = None,
                       model: str = "qwen3:14b") -> Any:
    if chat_client is None:
        return handoff
    f = _facts(handoff, envelope)
    es: dict | None = None
    try:
        res = chat_client.complete_with_usage(
            [ChatMessage(role="system", content=SYSTEM),
             ChatMessage(role="user", content="Deal facts:\n" + json.dumps(f))],
            model=model, temperature=0.2, max_tokens=512,
        )
        es = _parse(getattr(res, "text", None) or getattr(res, "content", "") or str(res))
    except Exception:
        es = None
    if not es:
        # never ship a degenerate headline — fall back to a safe factual one
        es = {"headline": _safe_headline(f),
              "health_line": (f"{f.get('blocker_count', 0)} blocker(s) to resolve before SOW."
                              if f.get("blocker_count") else "No blockers flagged."),
              "next_action": "Review the gap checklist below."}
    merged = {**(getattr(handoff, "executive_summary", None) or {}),
              "headline": es.get("headline"),
              "health_line": es.get("health_line"),
              "next_action": es.get("next_action"),
              "source": "neural_heads.exec_summary"}
    try:
        return dataclasses.replace(handoff, executive_summary=merged)
    except Exception:
        try:
            handoff.executive_summary = merged
        except Exception:
            pass
        return handoff
