"""Grounded PM briefing for executive_summary.overview.

Deterministic first (always works). Optional LLM enrichment via ChatClient
produces a denser PM-email brief from the same evidence pack.
"""
from __future__ import annotations

import json
import re
from typing import Any, Mapping, Protocol


class ChatClient(Protocol):
    def complete(self, *, system: str, user: str, temperature: float = 0.2) -> str: ...


_PM_BRIEF_SYSTEM = """You are PurTera's senior Project Manager writing the OrbitBrief
executive briefing a field PM reads before mobilizing.

You are a NO-LOSS RAG writer. The EVIDENCE PACK includes retrieved narrative
atoms that already cover scope, commercial, sites, access, BOM, risks, and
acceptance when those facets exist. You MUST surface every facet that appears
in narrative_atoms — do not drop commercial lines, access constraints, SKUs,
visit patterns, or acceptance criteria just to stay short.

Write ONLY from the EVIDENCE PACK. Do not invent sites, SKUs, fees, or
customer commitments that are not in the pack.

Voice: decisive PM email — concrete nouns, no filler, no marketing.

Structure EXACTLY three paragraphs separated by blank lines:
1) WHAT WE ARE DOING — customer, work type, site footprint, visit pattern,
   primary equipment / BOM lines, commercial shape (fixed / T&M) if present,
   provider/customer duties.
2) WHAT CAN BLOW THE JOB — open blockers + operational risks from atoms
   (access, keep/remove, pricing ambiguity, site-list authority, lifts,
   customer-furnished gear, telemetry/SAP, SKU treatment). Name the failure mode.
3) PM CONTROL — first decisions / confirms before SOW lock or mobilization.
   Imperative verbs. Reference the unresolved facets explicitly.

Rules:
- 220–420 words. Prefer specifics (site names, SKUs, dollar lines, visit counts).
- If a facet is missing from the pack, say what is unknown — do not guess.
- Do not repeat the deal number stamp; the UI already shows it.
- Output plain text paragraphs only — no markdown headings, bullets, or JSON.
"""


def _pub(s: Any) -> bool:
    if isinstance(s, Mapping):
        return bool(s.get("publishable"))
    return bool(getattr(s, "publishable", False))


def _name(s: Any) -> str:
    if isinstance(s, Mapping):
        return str(s.get("name") or "").strip()
    return str(getattr(s, "name", "") or "").strip()


def _sev(g: Any) -> str:
    if isinstance(g, Mapping):
        return str(g.get("severity") or "")
    return str(getattr(g, "severity", "") or "")


def _gap_q(g: Any) -> str:
    if isinstance(g, Mapping):
        return str(
            g.get("suggested_open_question") or g.get("message") or g.get("label") or ""
        ).strip()
    return str(
        getattr(g, "suggested_open_question", None)
        or getattr(g, "message", None)
        or getattr(g, "label", None)
        or ""
    ).strip()


def _gap_label(g: Any) -> str:
    if isinstance(g, Mapping):
        return str(g.get("label") or g.get("rule_id") or "").strip()
    return str(getattr(g, "label", None) or getattr(g, "rule_id", None) or "").strip()


def evidence_pack_for_briefing(
    *,
    label: str,
    sites: list[Any],
    gaps: list[Any],
    money_mentions: list[Any] | None = None,
    responsibilities: list[Any] | None = None,
    exclusions: list[Any] | None = None,
    domains: list[Any] | None = None,
    project_mode: str | None = None,
    fact_snippets: list[str] | None = None,
    narrative_atoms: list[Any] | None = None,
) -> dict[str, Any]:
    pub_sites = [_name(s) for s in sites if _pub(s) and _name(s)]
    blockers = [g for g in gaps if _sev(g) == "blocker"]
    warnings = [g for g in gaps if _sev(g) == "warning"]
    money = []
    for m in money_mentions or []:
        if isinstance(m, Mapping):
            money.append({"display": m.get("display"), "value": m.get("value")})
        else:
            money.append(
                {
                    "display": getattr(m, "display", None),
                    "value": getattr(m, "value", None),
                }
            )
    resp = []
    for r in responsibilities or []:
        if isinstance(r, Mapping):
            text = str(r.get("text") or "").strip()
            party = str(r.get("party") or "").strip()
        else:
            text = str(getattr(r, "text", "") or "").strip()
            party = str(getattr(r, "party", "") or "").strip()
        if text and len(text) < 400 and "polished machine" not in text.lower():
            resp.append({"party": party, "text": text[:320]})
    excl = []
    for e in exclusions or []:
        text = (
            str(e.get("text") if isinstance(e, Mapping) else getattr(e, "text", ""))
            or ""
        ).strip()
        if text and "e-mail message is intended" not in text.lower() and len(text) < 280:
            excl.append(text[:240])
    domain_labels = []
    for d in domains or []:
        if isinstance(d, Mapping):
            if d.get("selected_by_router") or d.get("active_for_sow"):
                domain_labels.append(str(d.get("label") or d.get("domain_id") or ""))
        elif getattr(d, "selected_by_router", False) or getattr(d, "active_for_sow", False):
            domain_labels.append(str(getattr(d, "label", "") or getattr(d, "domain_id", "")))
    atoms = []
    for row in narrative_atoms or []:
        if isinstance(row, Mapping):
            atoms.append(
                {
                    "facets": list(row.get("facets") or []),
                    "text": str(row.get("text") or "")[:1200],
                    "atom_type": str(row.get("atom_type") or ""),
                    "confidence": row.get("confidence"),
                }
            )
    return {
        "deal_label": label,
        "project_mode": (project_mode or "").strip() or None,
        "publishable_sites": pub_sites,
        "domains": [x for x in domain_labels if x][:4],
        "money": money[:5],
        "provider_customer_duties": resp[:6],
        "exclusions": excl[:4],
        "blocker_questions": [
            {"label": _gap_label(g), "ask": _gap_q(g)} for g in blockers[:8]
        ],
        "warning_questions": [
            {"label": _gap_label(g), "ask": _gap_q(g)} for g in warnings[:4]
        ],
        "fact_snippets": (fact_snippets or [])[:12],
        "narrative_atoms": atoms[:24],
        "narrative_atom_count": len(atoms),
    }


def build_pm_briefing_overview_deterministic(pack: dict[str, Any]) -> str:
    """Always-available multi-paragraph brief from the evidence pack."""
    sites = pack.get("publishable_sites") or []
    site_phrase = (
        f"{len(sites)} confirmed sites ({', '.join(sites[:3])}"
        + (f" +{len(sites) - 3} more" if len(sites) > 3 else "")
        + ")"
        if sites
        else "no confirmed publishable sites yet"
    )
    duties = pack.get("provider_customer_duties") or []
    provider = next((d["text"] for d in duties if d.get("party") == "provider"), "")
    customer = next((d["text"] for d in duties if d.get("party") == "customer"), "")
    money = pack.get("money") or []
    fee = next((m.get("display") for m in money if m.get("display")), None)
    domains = pack.get("domains") or []
    mode = pack.get("project_mode") or ""
    mode_labels = {
        "network_edge_install": "Network edge install",
        "wireless_install": "Wireless install",
        "cabling_install": "Structured cabling install",
        "av_install": "AV install",
        "access_control": "Access control",
        "alm": "Application / lifecycle management",
        "staff_aug": "Staff augmentation",
    }
    work = (
        mode_labels.get(mode)
        or (", ".join(domains[:2]) if domains else None)
        or (mode.replace("_", " ") if mode else None)
        or "scoped field work"
    )

    p1_bits = [
        f"Engagement covers {work} across {site_phrase}.",
    ]
    if provider:
        p1_bits.append(provider.rstrip(".") + ".")
    narrative = pack.get("narrative_atoms") or []

    def _facet_row_priority(row: Mapping[str, Any], facet: str) -> int:
        """Prefer atoms typed for this facet over lexical cross-tags."""
        atype = str(row.get("atom_type") or "").strip().lower()
        type_map = {
            "scope": {
                "scope_item",
                "work_package",
                "service_line",
                "deliverable",
                "exclusion",
                "responsibility",
                "open_question",
            },
            "commercial": {
                "money",
                "pricing",
                "commercial_term",
                "vendor_line_item",
                "quantity",
                "deal_metadata",
            },
            "sites": {"physical_site", "address", "site_roster", "site"},
            "access": {"access_requirement", "constraint", "safety", "badge"},
            "bom": {
                "asset_record",
                "device",
                "bom_line",
                "vendor_line_item",
                "circuit_inventory",
                "port_vlan_assignment",
            },
            "risks": {"risk", "open_question", "constraint"},
            "acceptance": {
                "acceptance",
                "cutover_validation",
                "exit_criteria",
                "checklist_item",
            },
            "schedule": {"schedule_phase", "date", "milestone"},
            "stakeholders": {"stakeholder", "contact", "role"},
        }
        if atype in type_map.get(facet, set()):
            return 2
        return 1 if facet in set(row.get("facets") or []) else 0

    def _add_facet_bits(
        target: list[str],
        facets: tuple[str, ...],
        *,
        limit: int,
        max_len: int = 200,
        used: set[str] | None = None,
    ) -> None:
        seen = used if used is not None else set()
        for facet in facets:
            if len(target) >= limit:
                return
            for a in sorted(
                narrative,
                key=lambda row, f=facet: (
                    _facet_row_priority(row, f),
                    1 if "$" in str(row.get("text") or "") and f == "commercial" else 0,
                    1
                    if re.search(
                        r"(?i)\b(confirm|tank|anova|ppe|escort|authoritative|fixed)",
                        str(row.get("text") or ""),
                    )
                    else 0,
                    len(str(row.get("text") or "")) < 320,
                ),
                reverse=True,
            ):
                if facet not in (a.get("facets") or []):
                    continue
                snippet = str(a.get("text") or "").strip()
                if not snippet:
                    continue
                key = re.sub(r"\s+", " ", snippet.lower())[:120]
                if key in seen:
                    continue
                seen.add(key)
                if len(snippet) > max_len:
                    snippet = snippet[: max_len - 3].rstrip() + "..."
                target.append(snippet if snippet.endswith(".") else snippet + ".")
                break

    used_p1: set[str] = set()
    # Cover every operational facet that exists — do not stop at the first hit.
    _add_facet_bits(
        p1_bits,
        ("scope", "sites", "commercial", "bom", "schedule", "stakeholders"),
        limit=8,
        max_len=220,
        used=used_p1,
    )
    if fee and not any("$" in b for b in p1_bits):
        p1_bits.append(
            f"Money signals in intake include {fee} (verify which line is the quote)."
        )
    if customer:
        p1_bits.append(f"Customer duty on record: {customer.rstrip('.')}.")

    blockers = pack.get("blocker_questions") or []
    failure_bits: list[str] = []
    used_p2: set[str] = set()
    for b in blockers[:5]:
        ask = (b.get("ask") or b.get("label") or "").strip()
        if not ask:
            continue
        failure_bits.append(ask.rstrip("?") + ".")
    _add_facet_bits(
        failure_bits,
        ("access", "risks", "acceptance"),
        limit=8,
        max_len=180,
        used=used_p2,
    )
    if failure_bits:
        p2 = "What can blow the job if left open: " + " ".join(failure_bits[:7])
    else:
        p2 = "No blocker-severity clarifications are open in the curated queue."

    control_bits: list[str] = []
    used_p3: set[str] = set()
    if blockers:
        control_bits.append(
            f"Settle the blocker checklist in Review Queue ({len(blockers)} open)."
        )
    _add_facet_bits(
        control_bits,
        ("acceptance", "access", "commercial", "stakeholders"),
        limit=5,
        max_len=160,
        used=used_p3,
    )
    if len(control_bits) <= (1 if blockers else 0):
        control_bits.append(
            "Walk remaining clarifications, confirm pricing + signatures, "
            "then proceed to SOW drafting from SOW_DRAFT.md."
        )
    else:
        control_bits.append(
            "Lock the authoritative site list and do not mobilize until "
            "access / keep-remove / commercial treatment are confirmed in writing."
        )
    p3 = "PM control before SOW lock: " + " ".join(control_bits)

    return "\n\n".join([" ".join(p1_bits), p2, p3]).strip()


def _parse_brief_text(raw: str) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None
    # Strip accidental fences / labels
    text = re.sub(r"^```(?:text|markdown)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    # Reject tiny / single-line fluff
    if len(text) < 120:
        return None
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paras) < 2:
        return None
    return "\n\n".join(paras[:4])


def enrich_pm_briefing_with_llm(
    pack: dict[str, Any],
    *,
    chat_client: ChatClient,
    model: str = "gpt-4.1-mini",
) -> str | None:
    user = (
        "EVIDENCE PACK (JSON):\n"
        + json.dumps(pack, ensure_ascii=False, indent=2)[:14000]
        + "\n\nWrite the three-paragraph PM briefing now. Cover EVERY facet present "
        "in narrative_atoms (scope, commercial, sites, access, bom, risks, "
        "acceptance, schedule, stakeholders)."
    )
    try:
        raw = chat_client.complete(system=_PM_BRIEF_SYSTEM, user=user, temperature=0.2)
    except Exception:
        return None
    return _parse_brief_text(raw)


def build_pm_briefing_overview(
    *,
    label: str,
    sites: list[Any],
    gaps: list[Any],
    money_mentions: list[Any] | None = None,
    responsibilities: list[Any] | None = None,
    exclusions: list[Any] | None = None,
    domains: list[Any] | None = None,
    project_mode: str | None = None,
    fact_snippets: list[str] | None = None,
    narrative_atoms: list[Any] | None = None,
    chat_client: ChatClient | None = None,
    model: str = "gpt-4.1-mini",
) -> str:
    pack = evidence_pack_for_briefing(
        label=label,
        sites=sites,
        gaps=gaps,
        money_mentions=money_mentions,
        responsibilities=responsibilities,
        exclusions=exclusions,
        domains=domains,
        project_mode=project_mode,
        fact_snippets=fact_snippets,
        narrative_atoms=narrative_atoms,
    )
    if chat_client is not None:
        enriched = enrich_pm_briefing_with_llm(pack, chat_client=chat_client, model=model)
        if enriched:
            return enriched
    return build_pm_briefing_overview_deterministic(pack)


__all__ = [
    "build_pm_briefing_overview",
    "build_pm_briefing_overview_deterministic",
    "enrich_pm_briefing_with_llm",
    "evidence_pack_for_briefing",
    "_PM_BRIEF_SYSTEM",
]
