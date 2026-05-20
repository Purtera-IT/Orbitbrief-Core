#!/usr/bin/env python3
"""Phase-1.75 envelope backfill — relational + parallel + noise-filtered.

Successor to ``envelope_backfill.py``. Adds:

  * Multiple extraction LENSES, each with a domain-specific prompt:
      - entities    — money / stakeholder / date / site / vendor (v1 path)
      - risks       — structured risk records (R-XX with prob/impact/
                      owner/mitigation/cadence), one atom per risk
      - phases      — phase-with-dates triples (start_date, end_date,
                      activities) emitted as a single atom per phase
                      with multi-key entity_keys
      - payment_terms — % + milestone keyword pairs
      - approvals   — threshold-and-approver pairs + conditional
                      "Approved pending X" approvals
      - rules       — substitution / change-order / acceptance /
                      escort rules with structured triggers + approver

    Each lens scans the same set of candidate atoms with a different
    prompt. Multiple lenses on the same atom run in parallel.

  * Concurrent LLM calls via ThreadPoolExecutor (default 4 workers).
    Mac Studio Ollama qwen3:14b handles 3-4 concurrent requests well.
    Cuts a 24-min sequential run to ~6-8 min on the same hardware.

  * Post-filter for v1-style entity noise:
      - Reject site canonical_values that are generic noun phrases
        (e.g. "atlanta_office", "office_areas", "warehouse_zones")
        unless the value is a fully-qualified place name.
      - Reject vendor canonical_values that collide with known device
        aliases (UPS, switch, ap, controller — these refer to the
        DEVICE in deal docs, not the shipping/manufacturer vendor).

  * Relational atom output: every backfill atom carries the RICH
    set of entity_keys that the regex extractor would only emit
    separately. E.g. a risk atom carries
        ``["risk:R-01", "stakeholder:renee_watkins", "site:atl_west"]``
    so Orbitbrief-Core's retrieval bundle and brain prompts see the
    relationship automatically.

  * All emitted atoms validate against orbitbrief.input.v2:
      - authority_class = machine_extractor
      - verified = unsupported
      - atom_type from the schema enum (risk / entity / decision /
        compliance), never an invented type
      - locator carries full LLM provenance (model id, rationale,
        raw_text_span)

Usage:

    python tools/envelope_backfill_v2.py \\
        /path/to/envelope.json \\
        --out /path/to/envelope_v2.json \\
        --ollama-base-url http://<host>:11434 \\
        --model qwen3:14b \\
        --lenses all \\
        --parallel 4
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Callable

# Make Orbitbrief-Core's inference client importable from a checkout.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from orbitbrief_core.inference.client import ChatMessage, OpenAIChatClient


# ─── Configuration ───

_MIN_RAW_TEXT_LEN = 40
_MAX_RAW_TEXT_CHARS = 1400
_DEFAULT_MAX_ATOMS = 500
_DEFAULT_PARALLEL = 4

_BACKFILL_ATOM_TYPES = frozenset({
    "scope_item", "constraint", "exclusion", "decision", "risk",
    "assumption", "open_question", "action_item", "meeting_commitment",
    "customer_instruction", "compliance", "vendor_line_item",
})

_VALID_ENTITY_TYPES = frozenset({
    "money", "stakeholder", "date", "milestone", "site",
    "vendor", "customer", "service",
})

# Generic noun phrases that the v1 backfill emitted as fake sites.
# A site name containing ONLY tokens from this set (no specific qualifier)
# is rejected. This catches "atlanta_office", "office_areas",
# "warehouse_zones", "atlanta_area_offices", etc.
_GENERIC_SITE_NOUNS = frozenset({
    "office", "offices", "area", "areas", "zone", "zones", "region",
    "regions", "facility", "facilities", "site", "sites", "location",
    "locations", "building", "buildings", "warehouse", "warehouses",
    "floor", "floors", "level", "levels", "wing", "wings",
    "the", "a", "an", "and", "of", "in", "at", "on", "or",
    "all", "any", "every", "each",
    # 3-word phrases like "atlanta_area_offices" — atlanta is specific
    # but area+offices makes the whole phrase generic. Reject if MORE
    # THAN HALF the tokens are generic.
})

# Known device-class words that get misclassified as vendors when they
# appear in BOM line items. "UPS" most prominently — refers to the
# device (uninterruptible power supply), not the shipping carrier.
_DEVICE_ALIAS_COLLISIONS = frozenset({
    "ups", "switch", "switches", "ap", "aps", "access_point",
    "controller", "controllers", "router", "routers", "firewall",
    "firewalls", "camera", "cameras", "speaker", "speakers",
    "microphone", "microphones", "display", "displays", "monitor",
    "monitors", "rack", "racks", "kvm", "modem", "modems",
    "tablet", "tablets", "laptop", "laptops", "desktop", "desktops",
    "printer", "printers", "scanner", "scanners", "barcode",
})


# ─── Lens framework ───


@dataclass
class LensFinding:
    """One backfill record from any lens. Renders to one EvidenceAtom."""

    atom_type: str
    entity_keys: list[str]
    text: str
    confidence: float
    rationale: str
    raw_text_span: str
    value_payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class Lens:
    name: str
    system_prompt: str
    json_root_key: str
    parse_record: Callable[[dict[str, Any], dict[str, Any], set[str]], list[LensFinding]]
    # Quick text-shape precondition: an atom only goes to the LLM if its
    # text matches this regex. ``None`` means scan every candidate atom
    # (used by the generic ``entities`` lens). Pre-filtering cuts wall-
    # clock dramatically on serialized-Ollama backends — for OPTBOT,
    # this turns ~558 jobs into ~120 jobs without changing output.
    precondition: re.Pattern[str] | None = None


# ─── Lens: entities (v1 + noise filter) ───


_LENS_ENTITIES_PROMPT = """You are an entity-extraction backfill agent for a deal-document pipeline.

Given a passage from a deal document, identify entities a regex-based extractor missed.

Focus on:
- MONEY: written-out amounts ("five million dollars"), multi-currency mentions, allowance-style amounts.
- STAKEHOLDER: named approvers/owners (resolve pronouns to nearby names).
- DATE: implicit / relative dates ("30 days after kickoff").
- MILESTONE: dated project milestones the regex extractor couldn't detect.
- SITE: physical-place names parser-os missed (lowercase prose, multi-word names).
- VENDOR: vendor / supplier names mentioned in business context not in the standard list.

Hard rules:
1. Output MUST be valid JSON: {"new_entities": [...]}. NO prose, no markdown.
2. DO NOT repeat entities already in the existing_entity_keys list.
3. DO NOT extract standard dollar amounts, ISO dates, or "First Last" names with role context.
4. Each entity:
   - "entity_type": money | stakeholder | date | milestone | site | vendor | customer | service
   - "canonical_value": normalized form
   - "raw_text_span": exact span from input
   - "confidence": 0.0-1.0 (only emit ≥ 0.7)
   - "rationale": one short sentence
5. CRITICAL — DO NOT emit:
   - Site names that are generic noun phrases ("office areas", "warehouse zones", "atlanta-area offices") without a specific named facility. ONLY emit a site if it has a SPECIFIC name (proper noun like "Atlanta staging facility", "ATL-AIR warehouse").
   - Vendor names that match a device class word (UPS, switch, AP, camera, controller, firewall). These refer to the device type, not a vendor brand.
6. If unsure, SKIP. False positives cost more than misses.

/no_think"""


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _canonical_money(value: str) -> str | None:
    cleaned = re.sub(r"[^\d.]", "", value)
    try:
        num = float(cleaned)
    except ValueError:
        return None
    if num < 100 or num > 1_000_000_000_000:
        return None
    if num == int(num):
        return f"money:{int(num)}"
    return f"money:{round(num, 2)}"


def _canonical_date(value: str, *, prefix: str = "date") -> str | None:
    if not re.match(r"^20[2-9][0-9]-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$", value):
        return None
    return f"{prefix}:{value}"


def _canonical_slug_key(prefix: str, value: str) -> str | None:
    slug = _slugify(value)
    if not slug or len(slug) < 3:
        return None
    return f"{prefix}:{slug}"


def _entity_canonical_key(entity_type: str, canonical_value: str) -> str | None:
    val = canonical_value.strip()
    if not val:
        return None
    if entity_type == "money":
        return _canonical_money(val)
    if entity_type in {"date", "milestone"}:
        return _canonical_date(val, prefix=entity_type)
    if entity_type in {"stakeholder", "site", "vendor", "customer", "service"}:
        return _canonical_slug_key(entity_type, val)
    return None


def _is_generic_site_name(slug_after_prefix: str) -> bool:
    """Return True if the site slug is mostly generic nouns with no specific
    place qualifier. Catches v1 noise like atlanta_office / office_areas."""
    tokens = [t for t in slug_after_prefix.split("_") if t]
    if not tokens:
        return True
    # If MORE THAN HALF the tokens are generic nouns, reject.
    generic = sum(1 for t in tokens if t in _GENERIC_SITE_NOUNS)
    if generic >= max(1, len(tokens) // 2 + 1):
        # Borderline check — if one token is a known city/airport prefix
        # (atlanta, chicago, etc.), still accept. The token list is short
        # so a known-city allowlist would be too restrictive; instead we
        # reject only when EVERY token is a generic noun.
        if generic == len(tokens):
            return True
        # If exactly one specific token + rest generic, also reject (e.g.
        # "atlanta_office", "atlanta_area_offices") — those add no value
        # over the named sites already in the envelope.
        if generic >= len(tokens) - 1:
            return True
    return False


def _is_device_alias_collision(vendor_slug: str) -> bool:
    """Return True if the vendor slug collides with a known device class
    word (UPS, switch, AP, etc.)."""
    return vendor_slug in _DEVICE_ALIAS_COLLISIONS


def _parse_entities(
    payload: dict[str, Any],
    atom: dict[str, Any],
    global_keys: set[str],
) -> list[LensFinding]:
    findings: list[LensFinding] = []
    entities = payload.get("new_entities") or []
    if not isinstance(entities, list):
        return []
    seen_in_atom: set[str] = set()
    for ent in entities:
        if not isinstance(ent, dict):
            continue
        etype = str(ent.get("entity_type") or "").strip().lower()
        if etype not in _VALID_ENTITY_TYPES:
            continue
        canonical_value = str(ent.get("canonical_value") or "").strip()
        if not canonical_value:
            continue
        try:
            conf = float(ent.get("confidence") or 0)
        except (TypeError, ValueError):
            conf = 0.0
        if conf < 0.7:
            continue
        entity_key = _entity_canonical_key(etype, canonical_value)
        if not entity_key:
            continue
        if entity_key in seen_in_atom or entity_key in global_keys:
            continue
        # Noise filters
        slug = entity_key.split(":", 1)[1]
        if etype == "site" and _is_generic_site_name(slug):
            continue
        if etype == "vendor" and _is_device_alias_collision(slug):
            continue
        seen_in_atom.add(entity_key)
        findings.append(
            LensFinding(
                atom_type="entity",
                entity_keys=[entity_key],
                text=f"LLM-backfilled {etype}: {canonical_value}",
                confidence=conf,
                rationale=str(ent.get("rationale") or "")[:300],
                raw_text_span=str(ent.get("raw_text_span") or "")[:300],
                value_payload={
                    "entity_type": etype,
                    "canonical_value": canonical_value,
                },
            )
        )
    return findings


# ─── Lens: risks (structured risk records) ───


_LENS_RISKS_PROMPT = """You are a structured-risk extractor.

If the passage contains risk-register content (typically "Risk ID: R-XX | Description: ... | Probability: ... | Impact: ... | Mitigation: ... | Owner: ... | Review Cadence: ..."), emit one record per risk.

Output JSON shape:
{"new_risks": [
  {
    "risk_id": "R-01",
    "description": "...",
    "probability": "low" | "medium" | "high",
    "impact": "low" | "medium" | "high",
    "mitigation": "...",
    "owner_name": "First Last",  // null if not named
    "review_cadence": "...",
    "affected_site_slug": "atl_west",  // if a specific site appears in description; null otherwise
    "confidence": 0.0-1.0,
    "raw_text_span": "...",
    "rationale": "..."
  }
]}

Only emit risks with confidence ≥ 0.8 AND a clear risk_id pattern (R-NN or similar).
If no risks present, return {"new_risks": []}.

/no_think"""


def _parse_risks(
    payload: dict[str, Any],
    atom: dict[str, Any],
    global_keys: set[str],
) -> list[LensFinding]:
    findings: list[LensFinding] = []
    risks = payload.get("new_risks") or []
    if not isinstance(risks, list):
        return []
    for r in risks:
        if not isinstance(r, dict):
            continue
        risk_id = str(r.get("risk_id") or "").strip()
        if not re.match(r"^[A-Z]+-?\d+$", risk_id):
            continue
        try:
            conf = float(r.get("confidence") or 0)
        except (TypeError, ValueError):
            conf = 0.0
        if conf < 0.8:
            continue
        risk_key = f"risk:{_slugify(risk_id)}"
        if risk_key in global_keys:
            continue
        keys = [risk_key]
        owner_name = (r.get("owner_name") or "").strip()
        if owner_name:
            owner_key = _canonical_slug_key("stakeholder", owner_name)
            if owner_key:
                keys.append(owner_key)
        site_slug = (r.get("affected_site_slug") or "").strip()
        if site_slug:
            site_key = _canonical_slug_key("site", site_slug)
            if site_key:
                keys.append(site_key)
        description = str(r.get("description") or "")[:280]
        text = (
            f"Risk {risk_id}: {description} "
            f"[prob={r.get('probability')} impact={r.get('impact')} "
            f"owner={owner_name or 'unassigned'}]"
        )
        findings.append(
            LensFinding(
                atom_type="risk",
                entity_keys=keys,
                text=text,
                confidence=conf,
                rationale=str(r.get("rationale") or "")[:300],
                raw_text_span=str(r.get("raw_text_span") or "")[:300],
                value_payload={
                    "risk_id": risk_id,
                    "description": description,
                    "probability": r.get("probability"),
                    "impact": r.get("impact"),
                    "mitigation": str(r.get("mitigation") or "")[:600],
                    "owner_name": owner_name or None,
                    "review_cadence": str(r.get("review_cadence") or "") or None,
                    "affected_site": site_slug or None,
                },
            )
        )
    return findings


# ─── Lens: phases (phase-with-dates triples) ───


_LENS_PHASES_PROMPT = """You are a project-phase extractor.

If the passage contains a phase schedule (e.g. "Phase 3 Site implementation | 2026-07-06 to 2026-07-24 | activities..."), emit one record per phase.

Output JSON shape:
{"new_phases": [
  {
    "phase_number": 3,
    "phase_name": "Site implementation",
    "start_date": "2026-07-06",   // ISO YYYY-MM-DD
    "end_date": "2026-07-24",     // ISO
    "activities": ["install site waves", "commission rooms", ...],
    "confidence": 0.0-1.0,
    "raw_text_span": "...",
    "rationale": "..."
  }
]}

Only emit phases with confidence ≥ 0.8 AND both dates in ISO format.
If no phase schedule present, return {"new_phases": []}.

/no_think"""


def _parse_phases(
    payload: dict[str, Any],
    atom: dict[str, Any],
    global_keys: set[str],
) -> list[LensFinding]:
    findings: list[LensFinding] = []
    phases = payload.get("new_phases") or []
    if not isinstance(phases, list):
        return []
    for p in phases:
        if not isinstance(p, dict):
            continue
        try:
            num = int(p.get("phase_number"))
        except (TypeError, ValueError):
            continue
        try:
            conf = float(p.get("confidence") or 0)
        except (TypeError, ValueError):
            conf = 0.0
        if conf < 0.8:
            continue
        start_date = str(p.get("start_date") or "").strip()
        end_date = str(p.get("end_date") or "").strip()
        sk = _canonical_date(start_date, prefix="milestone")
        ek = _canonical_date(end_date, prefix="milestone")
        if not sk or not ek:
            continue
        phase_key = f"phase:{num}"
        if phase_key in global_keys:
            continue
        phase_name = str(p.get("phase_name") or "").strip()
        activities = p.get("activities") or []
        if not isinstance(activities, list):
            activities = []
        keys = [phase_key, sk, ek]
        text = (
            f"Phase {num} ({phase_name}): {start_date} to {end_date}. "
            f"Activities: {', '.join(str(a) for a in activities[:6])}"
        )
        findings.append(
            LensFinding(
                atom_type="entity",
                entity_keys=keys,
                text=text,
                confidence=conf,
                rationale=str(p.get("rationale") or "")[:300],
                raw_text_span=str(p.get("raw_text_span") or "")[:300],
                value_payload={
                    "phase_number": num,
                    "phase_name": phase_name,
                    "start_date": start_date,
                    "end_date": end_date,
                    "activities": [str(a)[:120] for a in activities[:12]],
                },
            )
        )
    return findings


# ─── Lens: payment terms ───


_LENS_PAYMENT_TERMS_PROMPT = """You are a payment-schedule extractor.

If the passage contains a payment schedule with percentages tied to milestones (e.g. "30% at order acceptance, 40% on equipment receipt, 20% at site acceptance, 10% after hypercare closeout"), emit one record per payment term.

Output JSON shape:
{"new_payment_terms": [
  {
    "percentage": 30,
    "milestone_label": "order acceptance",
    "milestone_slug": "order_acceptance",
    "confidence": 0.0-1.0,
    "raw_text_span": "...",
    "rationale": "..."
  }
]}

Only emit terms with confidence ≥ 0.8.
If no payment schedule present, return {"new_payment_terms": []}.

/no_think"""


def _parse_payment_terms(
    payload: dict[str, Any],
    atom: dict[str, Any],
    global_keys: set[str],
) -> list[LensFinding]:
    findings: list[LensFinding] = []
    terms = payload.get("new_payment_terms") or []
    if not isinstance(terms, list):
        return []
    for t in terms:
        if not isinstance(t, dict):
            continue
        try:
            pct = int(t.get("percentage"))
        except (TypeError, ValueError):
            continue
        if not 1 <= pct <= 100:
            continue
        try:
            conf = float(t.get("confidence") or 0)
        except (TypeError, ValueError):
            conf = 0.0
        if conf < 0.8:
            continue
        milestone_slug = _slugify(str(t.get("milestone_slug") or t.get("milestone_label") or ""))
        if not milestone_slug:
            continue
        pt_key = f"payment_term:{pct}pct_at_{milestone_slug}"
        if pt_key in global_keys:
            continue
        text = (
            f"Payment term: {pct}% at {t.get('milestone_label') or milestone_slug}"
        )
        findings.append(
            LensFinding(
                atom_type="entity",
                entity_keys=[pt_key, f"milestone:{milestone_slug}"],
                text=text,
                confidence=conf,
                rationale=str(t.get("rationale") or "")[:300],
                raw_text_span=str(t.get("raw_text_span") or "")[:300],
                value_payload={
                    "percentage": pct,
                    "milestone_label": str(t.get("milestone_label") or "")[:120],
                    "milestone_slug": milestone_slug,
                },
            )
        )
    return findings


# ─── Lens: approvals (threshold + approver, conditional approvals) ───


_LENS_APPROVALS_PROMPT = """You are an approval-record extractor.

Two patterns to detect:
1. THRESHOLD-APPROVER: "X approval required over $N" / "approval > $N requires Y".
2. CONDITIONAL APPROVAL: "Person: Approved (pending|subject to|contingent on) X".

Output JSON shape:
{"new_approvals": [
  {
    "kind": "threshold" | "conditional",
    "approver_role": "CFO" | "Budget Owner" | ...,           // for threshold
    "approver_name": "Jordan Ames" | null,                    // for conditional
    "amount_usd": 1500000 | null,                             // for threshold
    "condition_text": "final cutover calendar" | null,        // for conditional
    "subject": "business case" | "technical design" | ...,    // what was approved
    "confidence": 0.0-1.0,
    "raw_text_span": "...",
    "rationale": "..."
  }
]}

Only emit approvals with confidence ≥ 0.8.
If no approvals present, return {"new_approvals": []}.

/no_think"""


def _parse_approvals(
    payload: dict[str, Any],
    atom: dict[str, Any],
    global_keys: set[str],
) -> list[LensFinding]:
    findings: list[LensFinding] = []
    approvals = payload.get("new_approvals") or []
    if not isinstance(approvals, list):
        return []
    for a in approvals:
        if not isinstance(a, dict):
            continue
        kind = str(a.get("kind") or "").strip().lower()
        if kind not in {"threshold", "conditional"}:
            continue
        try:
            conf = float(a.get("confidence") or 0)
        except (TypeError, ValueError):
            conf = 0.0
        if conf < 0.8:
            continue
        keys: list[str] = []
        if kind == "threshold":
            try:
                amount = int(a.get("amount_usd"))
            except (TypeError, ValueError):
                continue
            if amount < 100:
                continue
            approver_role = str(a.get("approver_role") or "").strip()
            if not approver_role:
                continue
            approver_slug = _slugify(approver_role)
            keys = [
                f"money:{amount}",
                f"approval_threshold:{amount}_{approver_slug}",
                f"stakeholder:{approver_slug}",
            ]
            uniq = f"approval_threshold:{amount}_{approver_slug}"
            if uniq in global_keys:
                continue
            text = (
                f"Approval threshold: ${amount:,} requires sign-off by {approver_role}"
            )
            value = {
                "kind": "threshold",
                "amount_usd": amount,
                "approver_role": approver_role,
                "subject": str(a.get("subject") or "")[:200],
            }
        else:  # conditional
            approver_name = str(a.get("approver_name") or "").strip()
            if not approver_name:
                continue
            condition = str(a.get("condition_text") or "").strip()
            if not condition:
                continue
            subject = str(a.get("subject") or "").strip()
            approver_slug = _slugify(approver_name)
            uniq = f"approval_conditional:{approver_slug}_{_slugify(subject)[:30]}_{_slugify(condition)[:30]}"
            if uniq in global_keys:
                continue
            keys = [uniq, f"stakeholder:{approver_slug}"]
            text = (
                f"Conditional approval: {approver_name} approved "
                f"{subject or 'item'} pending {condition}"
            )
            value = {
                "kind": "conditional",
                "approver_name": approver_name,
                "condition": condition[:400],
                "subject": subject[:200],
            }
        findings.append(
            LensFinding(
                atom_type="decision",
                entity_keys=keys,
                text=text,
                confidence=conf,
                rationale=str(a.get("rationale") or "")[:300],
                raw_text_span=str(a.get("raw_text_span") or "")[:300],
                value_payload=value,
            )
        )
    return findings


# ─── Lens: rules (substitution, change-order, acceptance, escort) ───


_LENS_RULES_PROMPT = """You are a contract-rule extractor.

Detect rules of these kinds:
- SUBSTITUTION: "substitutions require written approval from X"
- CHANGE_ORDER: "change orders required for X, Y, Z"
- ACCEPTANCE: "acceptance tests required: X"
- ESCORT: "after-hours escort required" + who/when
- LIFT_ACCESS: "lift required by X for Y"
- BADGE_ACCESS: "badged access for X"

Output JSON shape:
{"new_rules": [
  {
    "rule_kind": "substitution" | "change_order" | "acceptance" | "escort" | "lift_access" | "badge_access",
    "trigger": "what triggers the rule",
    "required_action": "what must happen",
    "approver_name": "First Last" | null,
    "approver_role": "CFO" | "Vendor PM" | null,
    "site_slug": "atl_west" | null,
    "confidence": 0.0-1.0,
    "raw_text_span": "...",
    "rationale": "..."
  }
]}

Only emit rules with confidence ≥ 0.8.
If no rules present, return {"new_rules": []}.

/no_think"""


def _parse_rules(
    payload: dict[str, Any],
    atom: dict[str, Any],
    global_keys: set[str],
) -> list[LensFinding]:
    findings: list[LensFinding] = []
    rules = payload.get("new_rules") or []
    if not isinstance(rules, list):
        return []
    for r in rules:
        if not isinstance(r, dict):
            continue
        kind = str(r.get("rule_kind") or "").strip().lower()
        if kind not in {
            "substitution", "change_order", "acceptance",
            "escort", "lift_access", "badge_access",
        }:
            continue
        try:
            conf = float(r.get("confidence") or 0)
        except (TypeError, ValueError):
            conf = 0.0
        if conf < 0.8:
            continue
        trigger = str(r.get("trigger") or "").strip()
        action = str(r.get("required_action") or "").strip()
        if not trigger or not action:
            continue
        approver_name = (r.get("approver_name") or "").strip()
        approver_role = (r.get("approver_role") or "").strip()
        site_slug = (r.get("site_slug") or "").strip()
        rule_slug = f"{kind}_{_slugify(trigger)[:40]}"
        rule_key = f"rule:{rule_slug}"
        if rule_key in global_keys:
            continue
        keys = [rule_key]
        if approver_name:
            keys.append(_canonical_slug_key("stakeholder", approver_name) or "")
        if site_slug:
            keys.append(_canonical_slug_key("site", site_slug) or "")
        keys = [k for k in keys if k]
        text = (
            f"Rule ({kind}): {trigger} → {action}"
            + (f" [approver: {approver_name or approver_role}]" if (approver_name or approver_role) else "")
        )
        findings.append(
            LensFinding(
                atom_type="compliance",
                entity_keys=keys,
                text=text,
                confidence=conf,
                rationale=str(r.get("rationale") or "")[:300],
                raw_text_span=str(r.get("raw_text_span") or "")[:300],
                value_payload={
                    "rule_kind": kind,
                    "trigger": trigger[:300],
                    "required_action": action[:300],
                    "approver_name": approver_name or None,
                    "approver_role": approver_role or None,
                    "affected_site": site_slug or None,
                },
            )
        )
    return findings


# ─── Lens registry ───


# Pre-condition regexes route only relevant atoms to each lens. This
# is the biggest single perf win on a serialized-Ollama backend —
# 558 jobs → ~120 jobs without changing output quality, because most
# atoms genuinely have no risk/phase/payment content.
_RE_RISKS = re.compile(r"\bRisk\s+ID\s*:\s*[A-Z]+-?\d+|\bR-\d{1,3}\b", re.IGNORECASE)
_RE_PHASES = re.compile(
    r"\bPhase\s*\d+\b.*\b20[2-9][0-9]-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])\b",
    re.IGNORECASE | re.DOTALL,
)
_RE_PAYMENT = re.compile(
    r"\b\d{1,3}%\s+(?:at|on|upon|after|order|equipment|site|hypercare|"
    r"acceptance|signoff|installation|completion|delivery|kickoff)",
    re.IGNORECASE,
)
_RE_APPROVALS = re.compile(
    r"\bapprove(?:s|d|r|d\s+pending|d\s+subject\s+to|d\s+contingent)|"
    r"\bapproval\s+(?:required|threshold|matrix)|"
    r"\bCFO\b|\bCISO\b|\bbudget\s+owner|\bsponsor\b",
    re.IGNORECASE,
)
_RE_RULES = re.compile(
    r"\bsubstitut|\bchange\s+order|\bescort|\blift\s+(?:required|access)|"
    r"\bbadge(?:d)?\s+access|\bacceptance\s+(?:test|criteria)|"
    r"\bhypercare|\bblackout\b",
    re.IGNORECASE,
)


LENSES: dict[str, Lens] = {
    "entities": Lens(
        name="entities", system_prompt=_LENS_ENTITIES_PROMPT,
        json_root_key="new_entities", parse_record=_parse_entities,
        precondition=None,  # scan all candidate atoms
    ),
    "risks": Lens(
        name="risks", system_prompt=_LENS_RISKS_PROMPT,
        json_root_key="new_risks", parse_record=_parse_risks,
        precondition=_RE_RISKS,
    ),
    "phases": Lens(
        name="phases", system_prompt=_LENS_PHASES_PROMPT,
        json_root_key="new_phases", parse_record=_parse_phases,
        precondition=_RE_PHASES,
    ),
    "payment_terms": Lens(
        name="payment_terms", system_prompt=_LENS_PAYMENT_TERMS_PROMPT,
        json_root_key="new_payment_terms", parse_record=_parse_payment_terms,
        precondition=_RE_PAYMENT,
    ),
    "approvals": Lens(
        name="approvals", system_prompt=_LENS_APPROVALS_PROMPT,
        json_root_key="new_approvals", parse_record=_parse_approvals,
        precondition=_RE_APPROVALS,
    ),
    "rules": Lens(
        name="rules", system_prompt=_LENS_RULES_PROMPT,
        json_root_key="new_rules", parse_record=_parse_rules,
        precondition=_RE_RULES,
    ),
}


# ─── Shared helpers ───


def _atom_text(atom: dict[str, Any]) -> str:
    val = atom.get("text") or atom.get("raw_text") or ""
    return val if isinstance(val, str) else ""


def _stable_id(prefix: str, *parts: str) -> str:
    h = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{h}"


def _extract_json(text: str) -> dict[str, Any]:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start != -1:
                candidate = text[start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    start = -1
                    continue
    return {}


_WS_NORM_RE = re.compile(r"\s+")


def _verify_span(span: str, source: str, *, min_len: int = 8) -> bool:
    """D2 hallucination guard: does ``span`` actually appear in ``source``?

    Comparison is whitespace-collapsed and case-folded. A finding
    is kept when its raw_text_span matches verbatim modulo
    whitespace + case. Empty / trivially-short spans
    (under ``min_len`` chars after normalization) are kept by
    default because the LLM sometimes returns a single token
    (e.g. ``"yes"``, ``"required"``) that's still a faithful
    quote — verifying every micro-span would create too many
    false-positive drops. Real hallucinations tend to be
    paragraph-shaped invented text, which this catches.

    Returns True when the span verifies (or is too short to
    verify) and the finding should be kept.
    """
    if not span:
        # No span supplied — keep the finding (older lenses may
        # not emit raw_text_span; the verification is opportunistic).
        return True
    norm_span = _WS_NORM_RE.sub(" ", span).strip().lower()
    if len(norm_span) < min_len:
        return True
    norm_source = _WS_NORM_RE.sub(" ", source or "").lower()
    return norm_span in norm_source


def _build_user_message(
    *, raw_text: str, existing_entity_keys: list[str], atom_id: str, atom_type: str,
) -> str:
    existing_summary = ", ".join(sorted(set(existing_entity_keys))[:40]) or "(none)"
    return (
        f'atom_id: "{atom_id}"\n'
        f"atom_type: {atom_type}\n"
        f"existing_entity_keys: [{existing_summary}]\n"
        f"raw_text:\n"
        f'"""\n{raw_text[:_MAX_RAW_TEXT_CHARS]}\n"""'
    )


def _finding_to_atom(
    finding: LensFinding,
    *,
    project_id: str,
    source_atom: dict[str, Any],
    lens_name: str,
    model: str,
) -> dict[str, Any]:
    src_atom_id = source_atom["id"]
    artifact_id = source_atom["artifact_id"]
    new_id = _stable_id(
        f"atm_llm_{lens_name}",
        project_id, src_atom_id, "|".join(finding.entity_keys), model,
    )
    locator = dict(source_atom.get("locator") or {})
    locator["extracted_via"] = f"llm_backfill_v2::{lens_name}::{model}"
    locator["source_atom_id"] = src_atom_id
    locator["lens"] = lens_name
    locator["llm_rationale"] = finding.rationale[:280]
    locator["llm_raw_text_span"] = finding.raw_text_span[:280]
    if finding.value_payload:
        locator["structured_value"] = finding.value_payload
    return {
        "id": new_id,
        "artifact_id": artifact_id,
        "atom_type": finding.atom_type,
        "authority_class": "machine_extractor",
        "confidence": float(finding.confidence),
        "text": finding.text,
        "section_path": list(source_atom.get("section_path") or []),
        "locator": locator,
        "verified": "unsupported",
        "entity_keys": list(finding.entity_keys),
    }


def _scan_atom_with_lens(
    *,
    atom: dict[str, Any],
    lens: Lens,
    chat: OpenAIChatClient,
    model: str,
    project_id: str,
    global_keys_snapshot: set[str],
) -> list[dict[str, Any]]:
    """Send one atom to one lens, return new envelope-shape atoms."""
    raw_text = _atom_text(atom)
    if len(raw_text.strip()) < _MIN_RAW_TEXT_LEN:
        return []
    atom_local_keys = list(atom.get("entity_keys") or [])
    user_msg = _build_user_message(
        raw_text=raw_text,
        existing_entity_keys=sorted(set(atom_local_keys) | global_keys_snapshot),
        atom_id=atom["id"],
        atom_type=atom.get("atom_type") or "unknown",
    )
    messages = [
        ChatMessage(role="system", content=lens.system_prompt),
        ChatMessage(role="user", content=user_msg),
    ]
    # Retry-with-backoff for transport-level errors. On a Tailscale-
    # relayed Ollama backend, parallel client load occasionally trips
    # WinError 10060 / connection-refused / read-timeout — the model
    # itself is fine, the transport just needs a moment. We retry up
    # to 3 times with 5s/15s/45s backoff.
    last_exc: Exception | None = None
    for attempt, delay in enumerate((0, 5, 15, 45), start=1):
        if delay:
            time.sleep(delay)
        try:
            result = chat.complete_with_usage(
                messages, model=model, temperature=0.0, max_tokens=2048,
            )
            last_exc = None
            break
        except Exception as exc:
            last_exc = exc
            continue
    if last_exc is not None:
        sys.stderr.write(
            f"  llm error on atom={atom['id']} lens={lens.name} "
            f"after retries: {last_exc}\n"
        )
        return []
    payload = _extract_json(result.text)
    findings = lens.parse_record(payload, atom, global_keys_snapshot)
    # D2 hallucination guard: drop any LLM finding whose
    # ``raw_text_span`` doesn't actually appear in the source
    # atom's text (after whitespace + case normalization). LLMs
    # sometimes return plausible-looking spans that aren't in the
    # source — those are unverifiable and dangerous to ship as
    # evidence-shaped atoms, so we filter them here before they
    # become atoms.
    verified_findings = [
        f for f in findings if _verify_span(f.raw_text_span, raw_text)
    ]
    new_atoms = [
        _finding_to_atom(
            f, project_id=project_id, source_atom=atom,
            lens_name=lens.name, model=model,
        )
        for f in verified_findings
    ]
    return new_atoms


# ─── Orchestrator ───


def _enrich_envelope(
    envelope: dict[str, Any],
    *,
    chat: OpenAIChatClient,
    model: str,
    lens_names: list[str],
    max_atoms: int,
    parallel: int,
    verbose: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    project_id = envelope.get("project_id", "unknown")
    atoms = envelope.get("atoms") or []
    candidates = [
        a for a in atoms
        if (a.get("atom_type") in _BACKFILL_ATOM_TYPES)
        and len(_atom_text(a)) >= _MIN_RAW_TEXT_LEN
    ]
    candidates = candidates[:max_atoms]
    # Build initial global key set
    global_keys: set[str] = set()
    for a in atoms:
        for k in a.get("entity_keys") or []:
            global_keys.add(k)
    for e in envelope.get("entities") or []:
        if e.get("canonical_key"):
            global_keys.add(e["canonical_key"])
        for alias in e.get("aliases") or []:
            global_keys.add(alias)
    global_keys_lock = Lock()
    lens_objs = [LENSES[n] for n in lens_names if n in LENSES]
    if verbose:
        print(
            f"envelope_backfill_v2: scanning {len(candidates)} atoms × "
            f"{len(lens_objs)} lenses = {len(candidates) * len(lens_objs)} jobs "
            f"via {model} ({parallel} parallel workers); "
            f"existing global entity_keys={len(global_keys)}...",
            file=sys.stderr,
        )
    # Pre-condition routing: skip atom×lens pairs where the atom text
    # doesn't contain the lens's domain signal (e.g. don't send every
    # atom to the risks lens — only atoms containing "Risk ID:" or
    # "R-NN"). Massive perf win on serialized-Ollama backends.
    jobs: list[tuple[dict[str, Any], Lens]] = []
    skipped_by_lens: Counter[str] = Counter()
    for atom in candidates:
        atom_text_val = _atom_text(atom)
        for lens in lens_objs:
            if lens.precondition is not None and not lens.precondition.search(atom_text_val):
                skipped_by_lens[lens.name] += 1
                continue
            jobs.append((atom, lens))
    if verbose:
        print(
            f"envelope_backfill_v2: pre-condition routing → "
            f"{len(jobs)} jobs (skipped by lens: {dict(skipped_by_lens)})",
            file=sys.stderr,
        )
    new_atoms: list[dict[str, Any]] = []
    by_lens: Counter[str] = Counter()
    by_atom_type: Counter[str] = Counter()
    by_entity_type: Counter[str] = Counter()
    t0 = time.perf_counter()
    completed = 0
    progress_lock = Lock()
    new_atoms_lock = Lock()

    def _run_job(atom, lens):
        with global_keys_lock:
            snapshot = set(global_keys)
        atoms_from = _scan_atom_with_lens(
            atom=atom, lens=lens, chat=chat, model=model,
            project_id=project_id, global_keys_snapshot=snapshot,
        )
        with global_keys_lock:
            for na in atoms_from:
                for k in na.get("entity_keys") or []:
                    global_keys.add(k)
        return lens.name, atoms_from

    with ThreadPoolExecutor(max_workers=parallel) as executor:
        futures = {
            executor.submit(_run_job, atom, lens): (atom["id"], lens.name)
            for atom, lens in jobs
        }
        for fut in as_completed(futures):
            atom_id, lens_name = futures[fut]
            try:
                lname, atoms_from = fut.result()
            except Exception as exc:
                sys.stderr.write(
                    f"  job error atom={atom_id} lens={lens_name}: {exc}\n"
                )
                atoms_from = []
                lname = lens_name
            with new_atoms_lock:
                new_atoms.extend(atoms_from)
                by_lens[lname] += len(atoms_from)
                for a in atoms_from:
                    by_atom_type[a["atom_type"]] += 1
                    for k in a.get("entity_keys") or []:
                        if ":" in k:
                            by_entity_type[k.split(":", 1)[0]] += 1
            with progress_lock:
                completed += 1
                if verbose and completed % 20 == 0:
                    elapsed = time.perf_counter() - t0
                    pct = 100.0 * completed / len(jobs)
                    print(
                        f"  [{completed}/{len(jobs)} = {pct:.0f}%] "
                        f"new={len(new_atoms)} ({elapsed:.0f}s)",
                        file=sys.stderr,
                    )

    # Update envelope
    enriched = dict(envelope)
    enriched["atoms"] = list(atoms) + new_atoms
    summary = dict(enriched.get("summary") or {})
    summary["atom_count"] = len(enriched["atoms"])
    summary["llm_backfill_v2_atom_count"] = len(new_atoms)
    enriched["summary"] = summary

    # Update indexes
    indexes = dict(enriched.get("indexes") or {})
    if "atoms_by_atom_type" in indexes:
        ab = dict(indexes["atoms_by_atom_type"])
        for new_atom in new_atoms:
            t = new_atom["atom_type"]
            ab.setdefault(t, [])
            ab[t] = list(ab[t]) + [new_atom["id"]]
        indexes["atoms_by_atom_type"] = ab
    if "atoms_by_entity_key" in indexes:
        be = dict(indexes["atoms_by_entity_key"])
        for new_atom in new_atoms:
            for k in new_atom.get("entity_keys") or []:
                be.setdefault(k, [])
                if new_atom["id"] not in be[k]:
                    be[k] = list(be[k]) + [new_atom["id"]]
        indexes["atoms_by_entity_key"] = be
    enriched["indexes"] = indexes

    stats = {
        "scanned_atom_count": len(candidates),
        "lens_count": len(lens_objs),
        "total_jobs": len(jobs),
        "parallel_workers": parallel,
        "new_atom_count": len(new_atoms),
        "by_lens": dict(by_lens),
        "by_atom_type": dict(by_atom_type),
        "by_entity_type": dict(by_entity_type),
        "duration_s": round(time.perf_counter() - t0, 1),
        "model": model,
    }
    return enriched, stats


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="envelope_backfill_v2")
    p.add_argument("envelope", help="parser-os envelope.json path")
    p.add_argument("--out", required=True, help="enriched envelope output path")
    p.add_argument("--ollama-base-url", default="http://localhost:11434")
    p.add_argument("--model", default="qwen3:14b")
    p.add_argument("--max-atoms", type=int, default=_DEFAULT_MAX_ATOMS)
    p.add_argument("--parallel", type=int, default=_DEFAULT_PARALLEL)
    p.add_argument("--timeout-s", type=float, default=300.0)
    p.add_argument(
        "--lenses", default="all",
        help=(
            "comma-separated list: entities,risks,phases,payment_terms,"
            "approvals,rules — or 'all' (default)"
        ),
    )
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)
    env_path = Path(args.envelope)
    if not env_path.is_file():
        print(f"envelope_backfill_v2: not found: {env_path}", file=sys.stderr)
        return 1
    envelope = json.loads(env_path.read_text(encoding="utf-8"))
    if envelope.get("schema_version") != "orbitbrief.input.v2":
        print(
            f"envelope_backfill_v2: warning — schema is "
            f"{envelope.get('schema_version')!r}; expected orbitbrief.input.v2",
            file=sys.stderr,
        )
    if args.lenses == "all":
        lens_names = list(LENSES.keys())
    else:
        lens_names = [n.strip() for n in args.lenses.split(",") if n.strip()]
        unknown = [n for n in lens_names if n not in LENSES]
        if unknown:
            print(
                f"envelope_backfill_v2: unknown lens(es): {unknown}; "
                f"valid: {list(LENSES.keys())}",
                file=sys.stderr,
            )
            return 1
    chat = OpenAIChatClient(base_url=args.ollama_base_url, timeout_s=args.timeout_s)
    enriched, stats = _enrich_envelope(
        envelope, chat=chat, model=args.model,
        lens_names=lens_names, max_atoms=args.max_atoms,
        parallel=args.parallel, verbose=not args.quiet,
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(enriched, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(stats, indent=2), file=sys.stderr)
    print(f"envelope_backfill_v2: wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
