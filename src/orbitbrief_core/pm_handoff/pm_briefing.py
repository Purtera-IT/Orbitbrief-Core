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

Voice: diagnostic PM brief — concrete nouns, evidence-backed, no filler.
Do NOT write a to-do list. Do NOT open sentences with Confirm / Verify / Settle /
Lock / Walk. State what is true, what is still open, and why it matters.

Structure EXACTLY three paragraphs separated by blank lines:
1) WHAT WE ARE DOING — customer, work type, site footprint, visit pattern,
   primary equipment / BOM lines, commercial shape (fixed / T&M) if present,
   provider/customer duties.
2) WHAT CAN BLOW THE JOB — for each open blocker, name the failure mode and the
   evidence gap (what intake shows vs what is missing). Use blocker detail /
   observed summary when present; cite sites, gear, commercial lines, access.
3) PM CONTROL — state what remains unresolved before SOW lock / mobilization
   and what evidence already exists. Informative status, not imperative orders.

Rules:
- 220–420 words. Prefer specifics (site names, SKUs, dollar lines, visit counts).
- If a facet is missing from the pack, say what is unknown — do not guess.
- Do not repeat the deal number stamp; the UI already shows it.
- Output plain text paragraphs only — no markdown headings, bullets, or JSON.
- Paragraph 2 must start with a capital letter after any label.
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


def _gap_detail(g: Any) -> str:
    """Prefer the diagnostic message / observed summary over the Confirm-ask."""
    if isinstance(g, Mapping):
        return str(
            g.get("message")
            or g.get("observed_summary")
            or g.get("evidence_summary")
            or ""
        ).strip()
    return str(
        getattr(g, "message", None)
        or getattr(g, "observed_summary", None)
        or getattr(g, "evidence_summary", None)
        or ""
    ).strip()


def _gap_source_snippets(g: Any) -> list[str]:
    """Full evidence quotes from gap sources (preferred over truncated observed_summary)."""
    raw = []
    if isinstance(g, Mapping):
        raw = list(g.get("sources") or [])
    else:
        raw = list(getattr(g, "sources", None) or [])
    out: list[str] = []
    for src in raw:
        if isinstance(src, Mapping):
            snip = str(src.get("snippet") or src.get("text") or "").strip()
        else:
            snip = str(getattr(src, "snippet", None) or getattr(src, "text", None) or "").strip()
        if len(snip) >= 18:
            out.append(snip)
    return out


def _clean_quote_candidate(text: str) -> str:
    """Normalize a quote; reject chrome / mid-word stubs; soft-trim at words."""
    t = re.sub(r"\s+", " ", (text or "").strip(" \"'"))
    if len(t) < 18:
        return ""
    if re.search(
        r"(?i)^olin\s+corpora|purtera will provide field services to support anova|"
        r"no change or modification to this sow shall be effective|"
        r"SAP\s*S4|Shipment and Delivery numbers|"
        r"devices with batteries may have been shipped|"
        r"^olin corporation site forest park",
        t,
    ):
        return ""
    # Reject upstream mid-word truncation (ends with 1–3 letter stub, no terminal punct).
    if re.search(r"(?i)\s[a-z]{1,3}$", t) and not re.search(r"[.?!…”\"]$", t):
        # Prefer trim back to last clean word ≥4 chars instead of dropping entirely
        # when the rest of the sentence is usable.
        parts = t.rsplit(" ", 1)
        if len(parts) == 2 and len(parts[1]) <= 3:
            t = parts[0].rstrip(" ,;:.-")
            if not t.endswith((".", "?", "!")):
                t += "..."
    if len(t) > 280:
        cut = t[:280]
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        t = cut.rstrip(" ,;:.-") + "..."
    if len(t) < 18:
        return ""
    return t


def _gap_best_quote(g: Any) -> str:
    """Prefer complete source snippets; fall back to cleaned observed_summary."""
    snips = _gap_source_snippets(g)
    ranked = sorted(snips, key=len, reverse=True)
    for snip in ranked:
        cleaned = _clean_quote_candidate(snip)
        if cleaned:
            return cleaned
    return _extract_evidence_quote(_gap_observed_raw(g))


def _gap_observed_raw(g: Any) -> str:
    if isinstance(g, Mapping):
        return str(g.get("observed_summary") or "").strip()
    return str(getattr(g, "observed_summary", None) or "").strip()


def _extract_evidence_quote(observed: str) -> str:
    """Pull the actionable quote from observed_summary chrome."""
    t = (observed or "").strip()
    if not t:
        return ""
    t = re.sub(r"(?i)^Evidence:\s*", "", t)
    lower = t.lower()
    for marker in (
        "customer_instruction:",
        "constraint:",
        "scope_item:",
        "change_order_rule:",
        "deal_metadata:",
        "assumption:",
    ):
        idx = lower.rfind(marker)
        if idx >= 0:
            t = t[idx + len(marker) :].strip()
            lower = t.lower()
    # Drop leading section path "DELIVERABLES / … —"
    t = re.sub(r"^[^—]{0,90}—\s*", "", t)
    return _clean_quote_candidate(t)

def _failure_sentence_from_blocker(row: Mapping[str, Any]) -> str:
    """Turn a blocker into an informative failure-mode sentence (not a to-do)."""
    detail = str(row.get("detail") or "").strip()
    label = str(row.get("label") or "").strip()
    ask = str(row.get("ask") or "").strip()
    quote = str(row.get("quote") or "").strip() or _extract_evidence_quote(
        str(row.get("observed") or "")
    )

    blob = " ".join([detail, quote, ask, label])
    if re.search(r"(?i)SAP\s*S4|Shipment and Delivery numbers", blob):
        return ""

    generic = bool(
        re.search(
            r"(?i)requires a PM decision|needs PM confirmation|"
            r"site-level decision still open|scope commitment needs PM|"
            r"requirement/constraint needs",
            detail or "",
        )
    )

    if detail and not generic:
        s = detail.rstrip(" .") + "."
        return s[0].upper() + s[1:]

    if quote:
        lab = label.strip()
        if re.search(r"(?i)^customer instruction$", lab):
            s = f'Customer wrote: "{quote}" — still open against the kit.'
        elif re.search(r"(?i)^constraint$", lab):
            s = f'Constraint on record: "{quote}" — still unresolved for field planning.'
        elif lab and not re.search(r"(?i)^scope", lab):
            s = f'{lab} — intake evidence: "{quote}".'
        else:
            s = f'Intake evidence: "{quote}" — still unresolved.'
        return s[0].upper() + s[1:]

    body = ask or label
    body = re.sub(
        r"(?i)^(confirm|verify|clarify|please\s+confirm|ensure|make\s+sure)\s+",
        "",
        body,
    ).strip()
    body = re.sub(
        r"(?i)\s*[—\-]\s*(?:customer confirms.*|or send revised.*|included as written.*)$",
        "",
        body,
    ).strip()
    body = body.rstrip(" ?.")
    if not body:
        return ""
    if re.match(r"(?i)^(which|what|who|where|whether)\b", body):
        s = f"Open risk — {body}."
    elif label and label.lower() not in body.lower():
        s = f"{label} remains unresolved — {body}."
    else:
        s = f"{body} is still unresolved in intake."
    return s[0].upper() + s[1:]


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
            {
                "label": _gap_label(g),
                "ask": _gap_q(g),
                "detail": _gap_detail(g),
                "quote": _gap_best_quote(g),
                "observed": _gap_observed_raw(g),
            }
            for g in blockers[:8]
        ],
        "warning_questions": [
            {
                "label": _gap_label(g),
                "ask": _gap_q(g),
                "detail": _gap_detail(g),
                "quote": _gap_best_quote(g),
            }
            for g in warnings[:4]
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
    # Prefer substance from narrative atoms over a mis-routed project_mode label.
    try:
        from orbitbrief_core.pm_handoff.question_genre_gates import FIELD_SENSOR_INSTALL_RE

        narr_blob = " ".join(
            str(a.get("text") or "") for a in (pack.get("narrative_atoms") or [])[:16]
        )
        if FIELD_SENSOR_INSTALL_RE.search(narr_blob) and (
            mode in {"", "av_install", "generic"}
            or "av install" in work.lower()
        ):
            work = "Field tank / telemetry install"
    except Exception:
        pass
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
                "commercial_total",
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
                    2
                    if f == "commercial"
                    and str(row.get("text") or "").lower().startswith(
                        "fixed commercial line:"
                    )
                    else 0,
                    1 if "$" in str(row.get("text") or "") and f == "commercial" else 0,
                    1
                    if re.search(
                        r"(?i)\b(confirm|tank|anova|ppe|escort|authoritative|fixed|survey)\b",
                        str(row.get("text") or ""),
                    )
                    else 0,
                    0 if re.search(r"(?i)^(?:hi|hey)\s+\w+", str(row.get("text") or "")) else 1,
                    len(str(row.get("text") or "")) < 320,
                ),
                reverse=True,
            ):
                if facet not in (a.get("facets") or []):
                    continue
                snippet = str(a.get("text") or "").strip()
                if not snippet:
                    continue
                # Never surface OEM manual PN dumps in the brief.
                if re.search(
                    r"(?i)user\s+guide|part\s+number\s+d[pw]a|mains\s+power\s+supply\s*\(with\s+heater\)",
                    snippet,
                ):
                    continue
                # Skip chrome that slipped into the pack.
                if facet == "stakeholders" and re.match(
                    r"(?i)^[A-Z][a-z]+(?:\s+[A-Z][a-z.'-]+){0,3}\s*[|—-]",
                    snippet,
                ):
                    continue
                if facet == "sites" and re.search(
                    r"(?i)^\d{2,5}\s+\S+.*\b(?:st|street|ave|rd|blvd)\b",
                    snippet,
                ):
                    # Publishable site names already open the paragraph.
                    continue
                if re.search(
                    r"(?i)ted\s*fees?\s*sd|^\(?\s*\)\s*\$|col_\d+|descrip|surcharge_\d+",
                    snippet,
                ):
                    continue
                if re.match(r"(?i)^[A-Z]{2,}_[A-Z0-9]+\s+\d+\.?$", snippet.strip()):
                    continue
                if re.match(r"^[A-Z0-9]{8,}\s+\d+\.?$", snippet.strip()):
                    continue
                if len(snippet) < 28 and re.fullmatch(r"[A-Z0-9][A-Z0-9\s./_-]{4,40}", snippet.strip()):
                    continue
                if re.search(
                    r"(?i)^the estimated fees for services outlined below are fixed fee",
                    snippet,
                ):
                    continue
                if re.search(r"(?i)billing\s+increment", snippet) and not snippet.lower().startswith(
                    "fixed commercial line:"
                ):
                    continue
                # Avoid repeating the same scope sentence in control.
                if facet in {"stakeholders", "commercial"} and any(
                    snippet[:50].lower() in (x.lower()) for x in target
                ):
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
        ("scope", "commercial", "bom", "schedule"),
        limit=7,
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
    for b in blockers[:6]:
        if not isinstance(b, Mapping):
            continue
        sent = _failure_sentence_from_blocker(b)
        if not sent:
            continue
        key = re.sub(r"\s+", " ", sent.lower())[:100]
        if key in used_p2:
            continue
        used_p2.add(key)
        failure_bits.append(sent)
    # Ground with operational evidence atoms (access / risk / acceptance), not to-dos.
    evidence_bits: list[str] = []
    _add_facet_bits(
        evidence_bits,
        ("access", "risks", "acceptance"),
        limit=5,
        max_len=180,
        used=used_p2,
    )
    for bit in evidence_bits:
        # Skip imperative leftovers that slipped into atoms.
        if re.match(r"(?i)^(confirm|verify|settle|lock|walk)\b", bit):
            continue
        failure_bits.append(bit)
        if len(failure_bits) >= 7:
            break
    if failure_bits:
        # Short label the UI can strip completely; body starts capitalized.
        p2 = "What can blow the job: " + " ".join(failure_bits[:7])
    else:
        p2 = "What can blow the job: No blocker-severity clarifications are open in the curated queue."

    control_bits: list[str] = []
    used_p3: set[str] = set()
    if blockers:
        # Prefer distinctive labels; collapse duplicate "Customer instruction".
        labels: list[str] = []
        seen_lab: set[str] = set()
        for b in blockers:
            if not isinstance(b, Mapping):
                continue
            lab = str(b.get("label") or "").strip()
            if not lab:
                continue
            key = lab.lower()
            if key in seen_lab and key in {"customer instruction", "constraint"}:
                quote = str(b.get("quote") or "").strip() or _extract_evidence_quote(
                    str(b.get("observed") or "")
                )
                if quote:
                    # Soft word-boundary label, not mid-token chop.
                    lab = quote if len(quote) <= 52 else quote[:52].rsplit(" ", 1)[0] + "…"
                    key = lab.lower()
            if key in seen_lab:
                continue
            seen_lab.add(key)
            labels.append(lab)
        label_phrase = ", ".join(labels[:4])
        if len(labels) > 4:
            label_phrase += f", +{len(labels) - 4} more"
        control_bits.append(
            f"{len(blockers)} blocker-severity items remain open in the Review Queue"
            + (f" ({label_phrase})" if label_phrase else "")
            + "; SOW lock and mobilization stay blocked until those gaps close."
        )
    _add_facet_bits(
        control_bits,
        ("acceptance", "access"),
        limit=4,
        max_len=160,
        used=used_p3,
    )
    # Drop imperative chrome from control fill.
    control_bits = [
        b
        for b in control_bits
        if not re.match(r"(?i)^(confirm|verify|settle|lock|walk)\b", b)
    ]
    if len(control_bits) <= (1 if blockers else 0):
        control_bits.append(
            "Pricing, signatures, and the remaining clarifications still need "
            "written customer resolution before SOW drafting proceeds from SOW_DRAFT.md."
        )
    else:
        control_bits.append(
            "Site-list authority, access treatment, and commercial shape still "
            "lack written customer confirmation in the kit."
        )
    p3 = "PM control: " + " ".join(control_bits)

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
