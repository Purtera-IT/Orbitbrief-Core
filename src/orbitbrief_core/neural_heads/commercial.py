"""Commercial head — value + billing model + unusual-terms flags, and it flags
CONFLICTING deal totals. Replaces the raw money-atom teaser.

teacher (DeepSeek) anchored on the authoritative total -> flags cite atoms ->
judge keeps real flags -> handoff.commercial_narrative.
"""
from __future__ import annotations

import dataclasses
import json
from typing import Any

from orbitbrief_core.neural_heads._common import tag_atoms, valid_cites
from orbitbrief_core.neural_heads._deepseek import deepseek_json, deepseek_available

KEEP = {"commercial_total", "payment_term", "bom_line", "pricing_assumption", "expense",
        "license_subscription", "change_order_rule", "site_budget", "material", "service_line",
        "lead_time_constraint", "scope_item"}

TEACH = (
    "You are a deal-desk analyst writing the COMMERCIAL section of a deal brief. The AUTHORITATIVE deal "
    "value is DEAL_TOTAL_USD given at the top — use THAT as the total; do NOT recompute a different total "
    "from atoms. Produce: a 1-sentence value_summary (anchored on DEAL_TOTAL_USD), billing_model "
    "(fixed|t&m|hybrid|recurring|unknown), and UNUSUAL/RISKY terms affecting cost/margin (T&M minimums, "
    "travel reimbursement, OT/holiday rates, escalation, FX, NTE caps). If an atom states an explicit total "
    "that DISAGREES with DEAL_TOTAL_USD, add a 'blocker' flag 'Conflicting deal totals' citing both. Each "
    "flag cites ONLY the 1-3 most relevant atom tags. Return STRICT JSON "
    '{"value_summary":str,"billing_model":str,"flags":[{"label":str,"note":str,"severity":str,"atom_ids":[str]}]}.'
)

JUDGE = (
    "Skeptical reviewer. For each commercial flag, real=true only if it is a genuine, specific cost/margin-"
    'affecting term grounded in the cited atom text — not boilerplate. Return STRICT JSON {"v":[{"i":int,"real":bool}]}.'
)


def apply_commercial(handoff: Any, envelope: dict, **_: Any) -> Any:
    if not deepseek_available():
        return handoff
    total = ((envelope.get("deal_financials") or {}).get("overall_total")
             or ((envelope.get("pm_dashboard") or {}).get("money_summary") or {}).get("total"))
    ctx, tagmap = tag_atoms(envelope, KEEP, limit=55)
    if not tagmap:
        return handoff
    out = deepseek_json(TEACH, f"DEAL_TOTAL_USD: {total}\nATOMS:\n" + ctx, max_tokens=2000)
    if not out:
        return handoff
    flags = []
    for f in out.get("flags", []):
        cited = valid_cites(f, tagmap, 1)
        if not cited:
            continue
        flags.append({"label": f.get("label", ""), "note": f.get("note", ""),
                      "severity": f.get("severity", "info"), "evidence_ids": cited})
    if flags:
        verdicts = deepseek_json(JUDGE, "Flags:\n" + json.dumps(
            [{"i": i, "label": f["label"], "note": f["note"]} for i, f in enumerate(flags)]),
            max_tokens=1000) or {}
        keep = {v["i"] for v in verdicts.get("v", []) if v.get("real") and isinstance(v.get("i"), int)}
        flags = [f for i, f in enumerate(flags) if (i in keep or not keep)]
    narrative = {"value_summary": out.get("value_summary", ""),
                 "billing_model": out.get("billing_model", "unknown"),
                 "flags": flags, "source": "neural_heads.commercial"}
    try:
        return dataclasses.replace(handoff, commercial_narrative=narrative)
    except Exception:
        try:
            handoff.commercial_narrative = narrative
        except Exception:
            pass
        return handoff
