from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

from orbitbrief_core.pm_handoff.business_labels import (
    CATEGORY_ORDER,
    FACT_CATEGORY_LABELS,
    SA_FOCUS_BY_DOMAIN,
    SEVERITY_SORT,
    classify_fact_category,
    compact_text,
    domain_label,
    normalize_for_dedupe,
)
from orbitbrief_core.pm_handoff.models import (
    DomainSummary,
    EvidenceCard,
    GapCard,
    PMHandoff,
    SiteSummary,
    SourceFileSummary,
    SourcePointer,
)
from orbitbrief_core.pm_handoff.reconciliation import (
    build_acceptance_checks,
    build_action_items,
    build_compliance_callouts,
    build_date_mentions,
    build_exclusions,
    build_executive_summary,
    build_money_mentions,
    build_quantity_claims,
    build_reconciliation_flags,
    build_responsibilities,
    build_rfp_line_items,
    build_risk_register,
    build_schedule_phases,
    build_site_rollups,
    build_stakeholder_contacts,
    build_stakeholder_pagers,
    find_quantity_contradictions,
    parse_bom_allocations,
)
from orbitbrief_core.pm_handoff.pm_intelligence import (
    build_change_order_triggers,
    build_critical_path,
    build_currency_conversions,
    build_currency_mentions,
    build_engagement_model,
    build_eol_flags,
    build_intake_completeness,
    build_lead_time_flags,
    build_license_items,
    build_margin_view,
    build_phase_dependencies,
    build_resource_conflicts,
    build_risk_aging,
    build_sla_penalties,
    build_subcontractor_mentions,
    build_tax_clauses,
    critical_path_from_dependencies,
    group_acceptance_by_site,
    group_actions_by_week,
    load_comparable_deals,
    risk_numeric_score,
)
from dataclasses import asdict

MAX_FACTS_PER_CATEGORY = 12


def build_pm_handoff(case_dir: Path) -> PMHandoff:
    case_dir = Path(case_dir)
    # Inspection report — orchestrator emits ``90_inspection_report.json``,
    # boss-bundle layout copies it as ``inspection_report.json``.
    report = (
        _read_json(case_dir / "inspection_report.json")
        or _read_json(case_dir / "90_inspection_report.json")
    )
    # SOW missingness — boss-bundle path writes per-case
    # ``sow_missingness.yaml``; auto-derive on the fly when only the
    # raw substrate dir is present.
    sow = _read_yaml(case_dir / "sow_missingness.yaml")
    if not sow:
        sow = _autogen_sow_missingness(case_dir)
    case_id = str(report.get("project_id") or sow.get("case_id") or case_dir.name)

    source_files, artifact_by_id = _build_source_files(report)
    sites = _build_site_summaries(report, case_dir)
    gaps = _build_gap_cards(sow)
    domains = _build_domains(report, sow, gaps)
    facts = _build_fact_cards(report, artifact_by_id)
    metrics = _build_metrics(report, sow, facts, gaps, sites)
    status, status_label = _derive_status(gaps, sow, report, sites)
    sa_focus = _build_sa_focus(domains)
    customer_questions = [g for g in gaps if g.severity in {"blocker", "warning"}]
    one_line = _build_one_line_summary(case_id, domains, sites, gaps)

    # A5 reconciliation: build money / date mentions and near-value
    # flags from the inspection report. These are stored as dicts so
    # PMHandoff.to_dict() stays JSON-clean (no dataclass nesting
    # depth quirks across versions).
    money = build_money_mentions(report)
    dates = build_date_mentions(report)
    flags = build_reconciliation_flags(money)
    risks = build_risk_register(report)
    phases = build_schedule_phases(report)
    site_rolls = build_site_rollups(report)
    actions = build_action_items(gaps=gaps, risk_rows=risks, schedule_phases=phases)
    pagers = build_stakeholder_pagers(
        gaps=gaps,
        risk_rows=risks,
        money_mentions=money,
        reconciliation_flags=flags,
        case_id=case_id,
    )
    compliance = build_compliance_callouts(report)
    allocations = parse_bom_allocations(report)
    accept_checks = build_acceptance_checks(report)
    rfp_items = build_rfp_line_items(report)
    contacts = build_stakeholder_contacts(report)
    exclusions = build_exclusions(report)
    responsibilities = build_responsibilities(report)
    qty_claims = build_quantity_claims(report)
    qty_contradictions = find_quantity_contradictions(qty_claims)
    exec_summary = build_executive_summary(
        case_id=case_id,
        status=status,
        status_label=status_label,
        one_line_summary=one_line,
        money_mentions=money,
        risks=risks,
        gaps=gaps,
        sites=sites,
        domains=domains,
    )
    # Tier 1-4 PM intelligence
    margin = build_margin_view(report)
    phase_dicts = [asdict(p) for p in phases]
    cp = build_critical_path(phase_dicts)
    lt_flags = build_lead_time_flags(report)
    eng_model = build_engagement_model(report)
    licenses = build_license_items(report)
    currencies = build_currency_mentions(report)
    taxes = build_tax_clauses(report)
    subs = build_subcontractor_mentions(report)
    sla_pen = build_sla_penalties(report)
    res_conflicts = build_resource_conflicts(phase_dicts)
    co_triggers = build_change_order_triggers(report)
    # risk aging proxied by earliest phase start as intake date
    intake_iso = phase_dicts[0]["start"] if phase_dicts else None
    risk_dicts = [asdict(r) for r in risks]
    aging = build_risk_aging(risk_dicts, intake_date_iso=intake_iso)
    action_dicts = [asdict(a) for a in actions]
    actions_weekly = group_actions_by_week(action_dicts)
    site_keys = [s.name for s in sites]
    accept_dicts = [asdict(a) for a in accept_checks]
    accept_by_site = group_acceptance_by_site(accept_dicts, site_keys=site_keys)
    # Final universality wave: currency conversions, EOL flags,
    # dependency-aware critical path, historical bench
    currency_convs = build_currency_conversions([asdict(c) for c in currencies])
    eol = build_eol_flags(report)
    phase_deps = build_phase_dependencies(report)
    cp_chain = critical_path_from_dependencies(phase_dicts, phase_deps)
    import os as _os
    history_path = _os.environ.get(
        "ORBITBRIEF_CORPUS_HISTORY",
        str((case_dir / ".orbitbrief_history.jsonl").resolve()),
    )
    comparable = load_comparable_deals(
        history_path,
        target_value_usd=margin.deal_total,
        target_domains=[d.label for d in domains if d.active_for_sow],
        limit=5,
    )
    completeness = build_intake_completeness(
        has_deal_total=bool(margin.deal_total),
        has_publishable_site=any(s.publishable for s in sites),
        has_schedule_phase=bool(phases),
        has_executive_stakeholder=any(
            "sponsor" in (g.message or "").lower() or "executive" in (g.message or "").lower()
            for g in gaps
        ) or bool([c for c in contacts if c.role]),
        has_vendor_line=bool(rfp_items),
        has_risk=bool(risks),
        has_exit_criteria=bool(accept_checks),
        has_payment_term=eng_model.detected_model != "unknown",
        has_exclusion=bool(exclusions),
        has_compliance_callout=bool(compliance),
    )

    return PMHandoff(
        case_id=case_id,
        status=status,
        status_label=status_label,
        one_line_summary=one_line,
        metrics=metrics,
        domains=domains,
        sites=sites,
        gaps=gaps,
        facts_by_category=facts,
        source_files=source_files,
        sa_focus=sa_focus,
        customer_questions=customer_questions,
        money_mentions=[asdict(m) for m in money],
        date_mentions=[asdict(d) for d in dates],
        reconciliation_flags=[asdict(f) for f in flags],
        risk_register=[asdict(r) for r in risks],
        schedule_phases=[asdict(p) for p in phases],
        site_rollups=[asdict(s) for s in site_rolls],
        action_items=[asdict(a) for a in actions],
        stakeholder_pagers=[asdict(p) for p in pagers],
        compliance_callouts=[asdict(c) for c in compliance],
        site_allocations=[asdict(a) for a in allocations],
        acceptance_checks=[asdict(a) for a in accept_checks],
        rfp_line_items=[asdict(r) for r in rfp_items],
        executive_summary=asdict(exec_summary),
        stakeholder_contacts=[asdict(c) for c in contacts],
        exclusions=[asdict(e) for e in exclusions],
        responsibilities=[asdict(r) for r in responsibilities],
        quantity_claims=[asdict(q) for q in qty_claims],
        quantity_contradictions=list(qty_contradictions),
        margin_view=asdict(margin),
        critical_path=[asdict(c) for c in cp],
        lead_time_flags=[asdict(f) for f in lt_flags],
        engagement_model=asdict(eng_model),
        license_items=[asdict(li) for li in licenses],
        currency_mentions=[asdict(c) for c in currencies],
        tax_clauses=[asdict(t) for t in taxes],
        subcontractor_mentions=[asdict(s) for s in subs],
        sla_penalties=[asdict(s) for s in sla_pen],
        resource_conflicts=[asdict(r) for r in res_conflicts],
        change_order_triggers=[asdict(c) for c in co_triggers],
        risk_aging=[asdict(a) for a in aging],
        actions_by_week=actions_weekly,
        acceptance_by_site=accept_by_site,
        intake_completeness=[asdict(g) for g in completeness],
        currency_conversions=[asdict(c) for c in currency_convs],
        eol_flags=[asdict(e) for e in eol],
        phase_dependencies=[asdict(d) for d in phase_deps],
        critical_path_chain=list(cp_chain),
        comparable_deals=[asdict(c) for c in comparable],
    )


def build_portfolio_handoff(cases_root: Path) -> list[PMHandoff]:
    root = Path(cases_root)
    if (root / "cases").is_dir():
        root = root / "cases"
    out: list[PMHandoff] = []
    for case_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        # Either the boss-bundle layout (``inspection_report.json``)
        # or the orchestrator layout (``90_inspection_report.json``)
        # is acceptable.
        if (
            (case_dir / "inspection_report.json").exists()
            or (case_dir / "90_inspection_report.json").exists()
        ):
            out.append(build_pm_handoff(case_dir))
    return out


def _build_source_files(report: dict[str, Any]) -> tuple[list[SourceFileSummary], dict[str, dict[str, Any]]]:
    files: list[SourceFileSummary] = []
    by_id: dict[str, dict[str, Any]] = {}
    for art in report.get("artifacts") or []:
        artifact_id = str(art.get("artifact_id") or "")
        by_id[artifact_id] = art
        # A6 graceful degradation: pull per-file parse outcome from
        # the inspection-report artifact. parser-os surfaces this as
        # ``parse_outcome`` on each document. Defaults to ``ok`` when
        # an older envelope without the field is passed in.
        outcome = art.get("parse_outcome") or {}
        files.append(
            SourceFileSummary(
                filename=str(art.get("filename") or artifact_id or "unknown"),
                artifact_type=str(art.get("artifact_type") or "unknown"),
                parser_name=str(art.get("parser_name") or "unknown"),
                evidence_items=int(art.get("atom_count") or 0),
                status=str(outcome.get("status") or "ok"),
                status_reason=(
                    str(outcome.get("reason"))[:280]
                    if outcome.get("reason") else None
                ),
            )
        )
    return files, by_id


def _build_site_summaries(report: dict[str, Any], case_dir: Path | None = None) -> list[SiteSummary]:
    md_overrides = _read_site_reality_md(case_dir)
    # The inspection report omits ``kind`` / ``publishable`` from its
    # cluster summary; fall back to the dedicated site-reality state
    # JSON when present.
    state_overrides: dict[str, dict[str, Any]] = {}
    if case_dir is not None:
        state_path = case_dir / "11_site_reality_state.json"
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8")) or {}
                for c in state.get("clusters") or []:
                    nm = str(c.get("canonical_name") or "").strip()
                    if nm:
                        state_overrides[nm] = c
            except Exception:
                pass

    out: list[SiteSummary] = []
    for cluster in (report.get("site_reality") or {}).get("clusters") or []:
        name = str(cluster.get("canonical_name") or cluster.get("cluster_id") or "Unknown site")
        md = md_overrides.get(name, {})
        st = state_overrides.get(name, {})
        publishable = _coerce_publishable(
            cluster.get("publishable", st.get("publishable", md.get("publishable", True)))
        )
        member_count = _count_any(cluster.get("member_atom_ids")) or _count_any(
            st.get("member_atom_ids")
        )
        artifact_count = _count_any(cluster.get("artifact_ids")) or _count_any(
            st.get("artifact_ids")
        )
        out.append(
            SiteSummary(
                name=name,
                kind=str(
                    cluster.get("kind")
                    or st.get("kind")
                    or md.get("kind")
                    or "unknown"
                ),
                publishable=publishable,
                member_evidence_count=member_count,
                artifact_count=artifact_count,
            )
        )
    return sorted(out, key=lambda s: (not s.publishable, s.name))


def _read_site_reality_md(case_dir: Path | None) -> dict[str, dict[str, Any]]:
    if case_dir is None:
        return {}
    path = case_dir / "synthesis" / "site_reality.md"
    if not path.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("|") or "canonical_name" in line or "---" in line:
            continue
        cells = [c.strip().strip("`") for c in line.strip("|").split("|")]
        if len(cells) >= 4:
            out[cells[1]] = {"kind": cells[2], "publishable": cells[3]}
    return out


def _coerce_publishable(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"true", "yes", "y", "1", "✓", "publishable"}


def _build_gap_cards(sow: dict[str, Any]) -> list[GapCard]:
    gaps: list[GapCard] = []
    for f in sow.get("findings") or []:
        domain_id = str(f.get("domain_id") or "other")
        gaps.append(
            GapCard(
                rule_id=str(f.get("rule_id") or "unknown_rule"),
                domain_id=domain_id,
                domain_label=domain_label(domain_id),
                label=str(f.get("label") or f.get("rule_id") or "Missing SOW item"),
                severity=str(f.get("severity") or "warning"),
                message=str(f.get("message") or ""),
                suggested_open_question=str(f.get("suggested_open_question") or f.get("message") or ""),
                observed_summary=_gap_evidence_summary(f.get("observed_support") or {}),
            )
        )
    return sorted(gaps, key=lambda g: (SEVERITY_SORT.get(g.severity, 9), g.domain_label, g.label))


def _build_domains(report: dict[str, Any], sow: dict[str, Any], gaps: list[GapCard]) -> list[DomainSummary]:
    selected = set((report.get("pack_prior") or {}).get("selected_pack_ids") or [])
    top = (report.get("pack_prior") or {}).get("top_pack_id")
    if top:
        selected.add(top)
    active = set(sow.get("active_domain_ids") or [])
    gap_counts: dict[str, Counter] = defaultdict(Counter)
    for g in gaps:
        gap_counts[g.domain_id][g.severity] += 1
    domain_ids = sorted(selected | active | set(gap_counts.keys()))
    out = [
        DomainSummary(
            domain_id=d,
            label=domain_label(d),
            selected_by_router=d in selected,
            active_for_sow=d in active,
            blockers=gap_counts[d]["blocker"],
            warnings=gap_counts[d]["warning"],
            info=gap_counts[d]["info"],
        )
        for d in domain_ids
    ]
    return sorted(out, key=lambda d: (-(d.blockers * 100 + d.warnings * 10 + d.info), d.label))


def _build_fact_cards(report: dict[str, Any], artifact_by_id: dict[str, dict[str, Any]]) -> dict[str, list[EvidenceCard]]:
    cards: dict[str, list[EvidenceCard]] = {c: [] for c in CATEGORY_ORDER}
    seen: set[str] = set()

    def score(atom: dict[str, Any]) -> tuple[int, float]:
        atom_type = str(atom.get("atom_type") or "")
        type_bonus = {
            "site_roster": 120,
            "asset_record": 95,
            "port_vlan_assignment": 90,
            "circuit_inventory": 90,
            "support_entitlement": 85,
            "alert_route": 85,
            "cutover_validation": 80,
            "vendor_line_item": 75,
            "quantity": 72,
            "risk": 70,
            "exclusion": 70,
            "open_question": 65,
            "form_option_state": 62,
            "rfi_row": 80,
            "runbook_row": 80,
            "working_measurement_row": 75,
        }.get(atom_type, 30)
        if str(atom.get("verified") or "") == "verified":
            type_bonus += 10
        if (atom.get("downstream") or {}).get("bundled"):
            type_bonus += 5
        text = str(atom.get("text") or "")
        if len(text) > 500:
            type_bonus -= 20
        return type_bonus, float(atom.get("confidence") or 0.0)

    for atom in sorted(report.get("atom_lineage") or [], key=score, reverse=True):
        atom_type = str(atom.get("atom_type") or "")
        text = str(atom.get("text") or "")
        if not text or len(text.strip()) < 8:
            continue
        category = classify_fact_category(atom_type, text)
        if len(cards[category]) >= MAX_FACTS_PER_CATEGORY:
            continue
        key = normalize_for_dedupe(text)[:200]
        if key in seen:
            continue
        seen.add(key)
        artifact = artifact_by_id.get(str(atom.get("artifact_id") or ""), {})
        cards[category].append(
            EvidenceCard(
                title=_fact_title(atom_type, category),
                category=category,
                text=compact_text(text, 340),
                source=SourcePointer(
                    filename=str(artifact.get("filename") or atom.get("artifact_id") or "unknown source"),
                    locator=_format_locator(atom.get("locator") or {}),
                ),
                confidence=_maybe_float(atom.get("confidence")),
                verified=str(atom.get("verified") or ""),
                internal_id=str(atom.get("id") or ""),
            )
        )
    return {k: v for k, v in cards.items() if v}


def _fact_title(atom_type: str, category: str) -> str:
    mapping = {
        "site_roster": "Confirmed site / facility evidence",
        "asset_record": "Asset inventory record",
        "port_vlan_assignment": "Port / VLAN assignment",
        "circuit_inventory": "Circuit inventory row",
        "support_entitlement": "Support / license entitlement",
        "alert_route": "NOC/SOC alert routing row",
        "vendor_line_item": "BOM / vendor line item",
        "quantity": "Quantity evidence",
        "risk": "Risk or constraint",
        "exclusion": "Exclusion / boundary",
        "open_question": "Open question from source",
        "form_option_state": "Form option state",
        "cutover_validation": "Cutover / validation item",
        "rfi_row": "RFI row",
        "runbook_row": "Runbook row",
        "working_measurement_row": "Field measurement row",
    }
    return mapping.get(atom_type, FACT_CATEGORY_LABELS.get(category, category.replace("_", " ").title()))


def _build_metrics(report: dict[str, Any], sow: dict[str, Any], facts: dict[str, list[EvidenceCard]], gaps: list[GapCard], sites: list[SiteSummary]) -> dict[str, Any]:
    funnel = report.get("funnel") or {}
    counts = Counter(g.severity for g in gaps)
    return {
        "source_files": int(funnel.get("source_artifacts") or 0),
        "evidence_items_extracted": int(funnel.get("atoms_extracted") or 0),
        "evidence_groups_certified": int(funnel.get("packets_certified") or 0),
        "sites_published": sum(1 for s in sites if s.publishable),
        "pm_visible_fact_cards": sum(len(v) for v in facts.values()),
        "missing_sow_items": len(gaps),
        "blockers": counts["blocker"],
        "warnings": counts["warning"],
        "info": counts["info"],
        "sow_validator_status": sow.get("status") or "unknown",
        "top_workstream": domain_label(str((report.get("pack_prior") or {}).get("top_pack_id") or "unknown")),
    }


def _derive_status(gaps: list[GapCard], sow: dict[str, Any], report: dict[str, Any], sites: list[SiteSummary]) -> tuple[str, str]:
    blockers = sum(1 for g in gaps if g.severity == "blocker")
    warnings = sum(1 for g in gaps if g.severity == "warning")
    if not any(s.publishable for s in sites):
        return "red", "Not ready: no confirmed physical site"
    if blockers:
        return "red", f"Not SOW-ready: {blockers} blocker question(s) remain"
    if warnings:
        return "yellow", f"PM review required: {warnings} clarification(s) remain"
    if str(sow.get("status") or "").lower() == "green":
        return "green", "Draft-ready: no required SOW gaps found"
    return "yellow", "PM review required"


def _build_sa_focus(domains: list[DomainSummary]) -> list[str]:
    out: list[str] = []
    for d in domains:
        if d.selected_by_router or d.active_for_sow:
            out.extend(SA_FOCUS_BY_DOMAIN.get(d.domain_id, []))
    seen: set[str] = set()
    unique: list[str] = []
    for item in out:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique[:18]


def _build_one_line_summary(case_id: str, domains: list[DomainSummary], sites: list[SiteSummary], gaps: list[GapCard]) -> str:
    active = [d.label for d in domains if d.selected_by_router or d.active_for_sow]
    site_names = [s.name for s in sites if s.publishable]
    blockers = sum(1 for g in gaps if g.severity == "blocker")
    warnings = sum(1 for g in gaps if g.severity == "warning")
    return f"{case_id}: {', '.join(active[:4]) if active else 'unclassified scope'} at {', '.join(site_names[:2]) if site_names else 'no confirmed site'}; {blockers} blocker and {warnings} warning SOW question(s) need PM/SA review."


def _format_locator(locator: dict[str, Any]) -> str:
    parts: list[str] = []
    if "page" in locator:
        parts.append(f"page {locator['page']}")
    if "sheet" in locator:
        parts.append(f"sheet {locator['sheet']}")
    if "row" in locator:
        parts.append(f"row {locator['row']}")
    if "line_start" in locator:
        end = locator.get("line_end")
        parts.append(f"lines {locator['line_start']}-{end}" if end and end != locator["line_start"] else f"line {locator['line_start']}")
    section_path = locator.get("section_path")
    if isinstance(section_path, list) and section_path:
        parts.append(" > ".join(str(x) for x in section_path[-2:]))
    return "; ".join(parts)


def _gap_evidence_summary(observed: dict[str, Any]) -> str:
    if not observed:
        return "No matching evidence found."
    bits: list[str] = []
    if observed.get("matched_regex"):
        bits.append("source text matched")
    if observed.get("matched_atom_type"):
        bits.append("evidence type matched")
    if observed.get("matched_packet_family"):
        bits.append("evidence group matched")
    if not bits:
        bits.append("no matching evidence found")
    if "publishable_site_count" in observed:
        bits.append(f"{observed.get('publishable_site_count')} confirmed site(s)")
    return ", ".join(bits)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _autogen_sow_missingness(case_dir: Path) -> dict[str, Any]:
    """When a per-case ``sow_missingness.yaml`` isn't on disk yet,
    derive one on the fly from the substrate envelope + pack-prior +
    site-reality artifacts. This keeps ``build_pm_handoff`` usable
    against a raw orchestrator output dir without requiring the
    boss-bundle pre-pass."""
    envelope_path = case_dir / "00_envelope.json"
    pack_prior_path = case_dir / "10_pack_prior_state.json"
    site_reality_path = case_dir / "11_site_reality_state.json"
    if not envelope_path.exists():
        return {}
    try:
        from orbitbrief_core.validator.sow_completeness import (
            evaluate_from_case_payloads,
        )
    except Exception:
        return {}
    envelope = _read_json(envelope_path)
    pack_prior = _read_json(pack_prior_path) or {}
    site_reality = _read_json(site_reality_path) or {}
    try:
        result = evaluate_from_case_payloads(
            envelope=envelope,
            pack_prior=pack_prior,
            site_reality=site_reality,
        )
        return result.to_dict()
    except Exception:
        return {}


def _maybe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _count_any(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return 1 if value else 0
    if isinstance(value, (list, tuple, set)):
        return len(value)
    return 0
