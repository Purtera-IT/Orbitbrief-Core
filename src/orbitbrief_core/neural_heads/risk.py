"""Risk head — synthesized, ranked risk portfolio (vs the legacy raw risk-atom list).
Ports the scratch pipeline that scored 83% judge-precision.

teacher (DeepSeek) synthesizes deal risks citing atoms -> citations validated ->
judge (DeepSeek) drops boilerplate -> handoff.risk_synthesis.
"""
from __future__ import annotations

import dataclasses
import json
from typing import Any

from orbitbrief_core.neural_heads._common import tag_atoms, valid_cites
from orbitbrief_core.neural_heads._deepseek import deepseek_json, deepseek_available

KEEP = {"risk", "constraint", "dependency", "exclusion", "mitigation", "compliance",
        "compliance_classification", "lead_time_constraint", "change_order_rule",
        "acceptance_criterion", "open_question", "customer_instruction"}

TEACH = (
    "You are a senior solutions architect building the RISK PORTFOLIO for a deal brief. From the atoms "
    "(tagged A1..AN), synthesize the TOP deal risks, each specific to THIS deal and citing the atom tag(s) "
    "it is based on (only tags that exist). For each: title, likelihood (low|medium|high), impact "
    "(low|medium|high), business_impact (1 phrase on cost/timeline/margin), mitigation (concrete), severity "
    "(blocker|warning|info). Do NOT invent generic risks. Return STRICT JSON "
    '{"risks":[{"title":str,"likelihood":str,"impact":str,"business_impact":str,"mitigation":str,'
    '"severity":str,"atom_ids":[str]}]} (3-7 risks).'
)

JUDGE = (
    "Skeptical reviewer. For each proposed deal risk, real=true only if it is a GENUINE, specific risk "
    "grounded in the cited evidence — not boilerplate ('project may face delays'), not a restated fact. "
    'Default to rejecting generic risks. Return STRICT JSON {"v":[{"i":int,"real":bool}]}.'
)


def apply_risk(handoff: Any, envelope: dict, **_: Any) -> Any:
    if not deepseek_available():
        return handoff
    ctx, tagmap = tag_atoms(envelope, KEEP, limit=55)
    if not tagmap:
        return handoff
    out = deepseek_json(TEACH, "ATOMS:\n" + ctx, max_tokens=2200)
    if not out:
        return handoff
    risks = []
    for r in out.get("risks", []):
        cited = valid_cites(r, tagmap, 1)
        if not cited:
            continue
        risks.append({k: r.get(k, "") for k in
                      ("title", "likelihood", "impact", "business_impact", "mitigation", "severity")}
                     | {"evidence_ids": cited,
                        "evidence": [(t, (tagmap[t].get("text") or "")[:90]) for t in cited]})
    if not risks:
        return handoff
    verdicts = deepseek_json(JUDGE, "Risks:\n" + json.dumps(
        [{"i": i, "title": r["title"], "business_impact": r["business_impact"]} for i, r in enumerate(risks)]),
        max_tokens=1200) or {}
    keep = {v["i"] for v in verdicts.get("v", []) if v.get("real") and isinstance(v.get("i"), int)}
    shipped = [r for i, r in enumerate(risks) if (i in keep or not keep)]
    for r in shipped:
        r["source"] = "neural_heads.risk"
    try:
        return dataclasses.replace(handoff, risk_synthesis=shipped)
    except Exception:
        try:
            handoff.risk_synthesis = shipped
        except Exception:
            pass
        return handoff
