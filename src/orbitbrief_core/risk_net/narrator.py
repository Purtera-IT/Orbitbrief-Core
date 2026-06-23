"""Track D — per-section PM-voice narrator.

One batched LLM call after Track A/B/C enrichers run that produces
~12 sentences total — one short PM-voice intro per v46 section
explaining what the data means and what to do about it.

Example output for ContestedScopeAlert:

    "5 IP-camera quantity conflicts: SOW says 3 at ATL-AIR but the
    vendor quote shows 15. That's a $19,200 swing on cameras alone.
    Confirm with the customer before signing — otherwise it
    becomes a change order in week 2."

Why batched:
* one round-trip, lower latency than 10 separate calls
* the model sees all sections at once → better cross-section
  framing ("…this connects to the 3 sites flagged below")
* fits comfortably in qwen2.5:3b's 32K context (input ~3K tokens,
  output ~1.5K tokens)

Falls back gracefully:
* no chat_client → handoff returned unchanged
* model returns malformed JSON → keep handoff unchanged, log warning
* individual section input missing → that section gets no narration
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from orbitbrief_core.inference.client import (
    ChatClient,
    ChatMessage,
    InferenceError,
)
from orbitbrief_core.pm_handoff.models import PMHandoff

log = logging.getLogger(__name__)


DEFAULT_MODEL = "qwen2.5:3b"   # same fast non-thinking model as polish
NARRATOR_MAX_TOKENS = 1024     # ~10 short paragraphs, conservative cap


# ── input compaction ───────────────────────────────────────────────


def _compact_project_vitals(v: dict) -> dict | None:
    if not v:
        return None
    return {
        "score_100": v.get("score_100"),
        "band": v.get("band"),
        "top_detractors": [
            d.get("name") if isinstance(d, dict) else str(d)
            for d in (v.get("top_detractors") or [])[:3]
        ],
    }


def _compact_contested(items: list | None) -> dict | None:
    if not items:
        return None
    examples = []
    for c in items[:5]:
        if not isinstance(c, dict):
            continue
        examples.append({
            "device": str(c.get("device") or "").replace("device:", ""),
            "site": str(c.get("site") or "").replace("site:", ""),
            "canonical": c.get("canonical_quantity"),
            "competing": c.get("competing_values"),
        })
    return {"count": len(items), "examples": examples}


def _dim_score(v: object) -> float:
    """Coerce a dimension value to its numeric score.

    The builder emits ``{name: {"score": float, "signals": {...}}}`` today;
    older payloads used a bare ``{name: float}``. Support both so the
    narrator never crashes on the richer shape (sorting dict values raised
    ``TypeError: '<' not supported between instances of 'dict' and 'dict'``
    and silently skipped the whole PM handoff render).
    """
    if isinstance(v, dict):
        s = v.get("score")
        return float(s) if isinstance(s, (int, float)) else 0.0
    return float(v) if isinstance(v, (int, float)) else 0.0


def _compact_sow_dims(b: dict | None) -> dict | None:
    if not b or not b.get("dimensions"):
        return None
    dims = b["dimensions"]
    scored = [(name, _dim_score(val)) for name, val in dims.items()]
    lowest = sorted(scored, key=lambda kv: kv[1])[:3]
    return {
        "grade": b.get("grade"),
        "score": round((b.get("readiness_score") or 0) * 100, 1),
        "lowest_dimensions": [{"name": d, "pct": round(s * 100, 1)} for d, s in lowest],
    }


def _compact_site_readiness(rows: list | None) -> dict | None:
    if not rows:
        return None
    sorted_rows = sorted(rows, key=lambda r: r.get("readiness_score") or 0)
    least = [
        {"name": r.get("name") or r.get("site_slug"), "readiness": r.get("readiness_score")}
        for r in sorted_rows[:5]
    ]
    return {"count": len(rows), "least_ready": least}


def _compact_milestones(rows: list | None) -> dict | None:
    if not rows:
        return None
    dated = [r for r in rows if r.get("iso_date")]
    if not dated:
        return None
    earliest = min(r["iso_date"] for r in dated)
    latest = max(r["iso_date"] for r in dated)
    return {"count": len(rows), "earliest": earliest, "latest": latest}


def _compact_stakeholder_load(rows: list | None) -> dict | None:
    if not rows:
        return None
    bottlenecks = [r for r in rows if r.get("is_bottleneck")]
    top = sorted(rows, key=lambda r: r.get("risk_severity_load") or 0, reverse=True)[:3]
    return {
        "count": len(rows),
        "bottlenecks": [r.get("slug") for r in bottlenecks],
        "top_loaded": [
            {"slug": r.get("slug"), "risks": r.get("risk_count"), "load": r.get("risk_severity_load")}
            for r in top
        ],
    }


def _compact_evidence_authority(b: dict | None) -> dict | None:
    if not b or not b.get("by_class"):
        return None
    by_class = b.get("by_class", {})
    total = b.get("total_atoms") or sum(by_class.values())
    classes = sorted(by_class.items(), key=lambda kv: kv[1], reverse=True)
    return {
        "total_atoms": total,
        "top_classes": [{"class": c, "count": n, "pct": round(100 * n / max(total, 1), 1)} for c, n in classes[:5]],
    }


def _compact_change_order(rows: list | None) -> dict | None:
    if not rows:
        return None
    return {
        "count": len(rows),
        "with_approval_signal": sum(1 for r in rows if r.get("approval_signal")),
        "earliest": min((r.get("iso_date") or "9999") for r in rows),
    }


def _compact_risk_signals(b: dict | None) -> dict | None:
    if not b:
        return None
    return {
        "atom_risk_top_count": len(b.get("atom_risk_top") or []),
        "site_cost_overrun_top": [
            {"name": s.get("name") or s.get("site_slug"), "score": s.get("score")}
            for s in (b.get("site_cost_overrun_top") or [])[:3]
        ],
        "milestone_slip_top_count": len(b.get("milestone_slip_top") or []),
        "stakeholder_bottleneck_top": [
            {"slug": p.get("slug"), "score": p.get("score")}
            for p in (b.get("stakeholder_bottleneck_top") or [])[:3]
        ],
    }


def _compact_claim_consensus(b: dict | None) -> dict | None:
    if not b or not b.get("summary"):
        return None
    s = b["summary"]
    return {
        "total": s.get("total_claims_scored"),
        "avg_ribbon": s.get("avg_confidence_ribbon"),
        "by_color": s.get("by_ribbon_color"),
    }


# ── prompt assembly ────────────────────────────────────────────────


SECTION_LABELS: dict[str, str] = {
    "project_vitals": "Project Vitals (0–100 health gauge)",
    "contested_scope_items": "Contested Scope Items (quantity conflicts)",
    "sow_readiness_dimensions": "SOW Readiness Scorecard",
    "site_readiness": "Site Readiness",
    "milestones": "Milestones",
    "stakeholder_load": "Stakeholder Load",
    "evidence_authority": "Evidence Authority",
    "change_order_timeline": "Change Order Timeline",
    "risk_signals": "Risk Signals (graph-feature scoring)",
    "claim_consensus": "Claim Confidence Atlas",
}


SYSTEM_PROMPT = (
    "You are a senior project manager who writes terse, plain-English summaries for "
    "other PMs.  For each section you're given, write ONE sentence (max 2) that "
    "(a) states the headline number and what it means, and (b) tells the PM the "
    "concrete next action.  No jargon, no buzzwords, no 'this provides insight'.  "
    "Be specific with numbers and names.  Refer to dollar amounts only if they "
    "appear in the data.  If a section has nothing actionable, write one short "
    "sentence noting that and move on."
)


def _build_payload(handoff: PMHandoff) -> dict[str, dict]:
    """Compact each section to the minimum data the narrator needs."""
    h = handoff.to_dict()
    sections: dict[str, dict] = {}
    sec_data = {
        "project_vitals": _compact_project_vitals(h.get("project_vitals") or {}),
        "contested_scope_items": _compact_contested(h.get("contested_scope_items")),
        "sow_readiness_dimensions": _compact_sow_dims(h.get("sow_readiness_dimensions")),
        "site_readiness": _compact_site_readiness(h.get("site_readiness")),
        "milestones": _compact_milestones(h.get("milestones")),
        "stakeholder_load": _compact_stakeholder_load(h.get("stakeholder_load")),
        "evidence_authority": _compact_evidence_authority(h.get("evidence_authority")),
        "change_order_timeline": _compact_change_order(h.get("change_order_timeline")),
        "risk_signals": _compact_risk_signals(h.get("risk_signals")),
        "claim_consensus": _compact_claim_consensus(h.get("claim_consensus")),
    }
    for k, v in sec_data.items():
        if v is not None:
            sections[k] = v
    return sections


def _build_user_prompt(payload: dict[str, dict]) -> str:
    lines = [
        "Here is the per-section data for this deal.  Reply with a JSON object "
        "keyed by section name; value is the one-sentence (max two) narration "
        "for that section.  No prose outside the JSON.",
        "",
        "Section labels:",
    ]
    for k, label in SECTION_LABELS.items():
        if k in payload:
            lines.append(f"  - {k}: {label}")
    lines.append("")
    lines.append("Section data (JSON):")
    lines.append(json.dumps(payload, indent=2, default=str))
    lines.append("")
    lines.append("Return EXACTLY: {\"" + '": "...", "'.join(payload.keys()) + "\": \"...\"}")
    return "\n".join(lines)


# ── cache ──────────────────────────────────────────────────────────


def _cache_path() -> Path | None:
    p = os.environ.get("ORBITBRIEF_NARRATOR_CACHE")
    return Path(p) if p else None


def _cache_key(payload: dict[str, dict], model: str) -> str:
    blob = json.dumps({"model": model, "payload": payload}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> dict[str, str] | None:
    p = _cache_path()
    if p is None or not p.is_file():
        return None
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("key") == key:
                v = row.get("value")
                if isinstance(v, dict):
                    return {str(k): str(vv) for k, vv in v.items()}
    except OSError:
        return None
    return None


def _cache_put(key: str, value: dict[str, str]) -> None:
    p = _cache_path()
    if p is None:
        return
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"key": key, "value": value}) + "\n")
    except OSError:
        pass


# ── public entry point ─────────────────────────────────────────────


def apply_section_narration(
    handoff: PMHandoff,
    *,
    chat_client: ChatClient | None,
    model: str = DEFAULT_MODEL,
) -> PMHandoff:
    """Generate per-section narration paragraphs and attach to handoff.

    Returns unchanged handoff if:
    * ``chat_client`` is None
    * no sections have data (empty payload)
    * the LLM call fails or returns malformed JSON
    """
    if chat_client is None:
        return handoff

    payload = _build_payload(handoff)
    if not payload:
        return handoff

    cache_key = _cache_key(payload, model)
    cached = _cache_get(cache_key)
    if cached is not None:
        return replace(handoff, section_narration=dict(cached))

    user_prompt = _build_user_prompt(payload)
    messages = [
        ChatMessage(role="system", content=SYSTEM_PROMPT),
        ChatMessage(role="user", content=user_prompt),
    ]

    try:
        result = chat_client.complete_with_usage(
            messages,
            model=model,
            temperature=0.2,
            max_tokens=NARRATOR_MAX_TOKENS,
            response_format={"type": "json_object"},
        )
    except InferenceError as exc:
        log.warning("narrator: LLM call failed, skipping narration: %s", exc)
        return handoff
    except Exception as exc:  # noqa: BLE001
        log.warning("narrator: unexpected error, skipping narration: %s", exc)
        return handoff

    text = (result.text or "").strip()
    if not text:
        return handoff
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Try harder — sometimes models prefix with "```json" or similar.
        cleaned = text.strip("`").lstrip("json").strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            log.warning("narrator: returned non-JSON, skipping narration: %s", text[:200])
            return handoff

    if not isinstance(parsed, dict):
        log.warning("narrator: returned non-object, skipping narration")
        return handoff

    narration: dict[str, str] = {}
    for k, v in parsed.items():
        if k in SECTION_LABELS and isinstance(v, str) and v.strip():
            narration[k] = v.strip()

    if not narration:
        return handoff

    _cache_put(cache_key, narration)
    return replace(handoff, section_narration=narration)
