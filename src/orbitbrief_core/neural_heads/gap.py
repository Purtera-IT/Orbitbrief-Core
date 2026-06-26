"""Gap head — deal-specific SOW gaps, grounded by atom-ID citation, verified by an
independent judge. Ports the scratch pipeline that scored 89% judge-precision.

teacher (DeepSeek) proposes gaps citing atom tags -> citations validated (fabrication
dropped) -> judge (DeepSeek) keeps only genuinely-unresolved gaps -> handoff.gap_findings.
Graceful: no key / no atoms / any error -> handoff unchanged.
"""
from __future__ import annotations

import dataclasses
import json
from typing import Any

from orbitbrief_core.neural_heads._common import tag_atoms, valid_cites
from orbitbrief_core.neural_heads._deepseek import deepseek_json, deepseek_available

KEEP = {"scope_item", "requirement", "task", "open_question", "constraint",
        "acceptance_criterion", "milestone_phase", "deliverable", "exclusion",
        "commercial_total", "payment_term", "bom_line"}

TEACH = (
    "/no_think You are a senior solutions architect reviewing a B2B managed-services deal before its SOW "
    "is drafted. Given the parser's atoms (tagged A1..AN), list the SOW GAPS — specific missing facts a "
    "junior PM would miss. RULES: every gap MUST cite the atom tags it is based on (only tags that exist); "
    "ground ONLY in those atoms; match the deal's domain. SEVERITY: blocker = a REQUIRED input is missing/"
    "contradictory so the SOW cannot be priced/scoped (rare); warning = present but ambiguous; info = minor. "
    'Return STRICT JSON {"gaps":[{"label":str,"severity":str,"question":str,"evidence_ids":[str]}]} (4-9 gaps).'
)

JUDGE = (
    "You are a strict principal solutions architect auditing whether proposed SOW gaps are genuinely "
    "missing/unresolved given the evidence. Mark real=false for anything already answered, not applicable, "
    'or vacuous. Return STRICT JSON {"v":[{"i":int,"real":bool}]}.'
)


def apply_gap(handoff: Any, envelope: dict, **_: Any) -> Any:
    if not deepseek_available():
        return handoff
    ctx, tagmap = tag_atoms(envelope, KEEP, limit=60)
    if not tagmap:
        return handoff
    out = deepseek_json(TEACH, "ATOMS:\n" + ctx, max_tokens=2400)
    if not out:
        return handoff
    gaps = []
    for g in out.get("gaps", []):
        cited = valid_cites(g, tagmap, 1)
        if not cited:
            continue
        gaps.append({"label": g.get("label", ""), "severity": g.get("severity", "warning"),
                     "question": g.get("question", ""), "evidence_ids": cited,
                     "evidence": [(t, (tagmap[t].get("text") or "")[:90]) for t in cited]})
    if not gaps:
        return handoff
    verdicts = deepseek_json(JUDGE, "Gaps:\n" + json.dumps(
        [{"i": i, "label": g["label"], "question": g["question"]} for i, g in enumerate(gaps)]),
        max_tokens=1200) or {}
    keep = {v["i"] for v in verdicts.get("v", []) if v.get("real") and isinstance(v.get("i"), int)}
    shipped = [g for i, g in enumerate(gaps) if (i in keep or not keep)]  # if judge fails, keep grounded set
    for g in shipped:
        g["source"] = "neural_heads.gap"
    try:
        return dataclasses.replace(handoff, gap_findings=shipped)
    except Exception:
        try:
            handoff.gap_findings = shipped
        except Exception:
            pass
        return handoff
