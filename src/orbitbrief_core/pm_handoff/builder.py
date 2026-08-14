from __future__ import annotations

import json
import os
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
    parse_site_allocation_matrix,
    build_site_quantity_allocations,
    _is_vendor_site_key,
    _physical_site_slugs,
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
    build_crm_detection,
    build_customer_answer_slots,
    build_drift_snapshot,
    build_ocr_backend_status,
    build_parser_quality_score,
    build_run_telemetry,
    build_urgency_signals,
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
from orbitbrief_core.pm_handoff.fact_quality import (
    display_case_label,
    fact_overlaps_question,
    filter_pm_visible_atoms,
    is_av_install_gold_fact,
    polish_fact_claim,
)
from orbitbrief_core.pm_handoff.question_engine import (
    MODE_AV,
    MODE_NETWORK_EDGE_INSTALL,
    build_customer_questions,
    domain_ids_allowed_for_mode,
)
from orbitbrief_core.pm_handoff.semantic_dedupe import is_near_duplicate_of_any, semantic_dedupe
from dataclasses import asdict

MAX_FACTS_PER_CATEGORY = 12

# Info-level checklist leftovers that still clutter install handoffs even after
# the SOW validator demotes them (belt-and-suspenders with sow_completeness).
_INSTALL_IRRELEVANT_GAP_IDS = frozenset({
    "network_maintenance.routing_failover",
    "network_maintenance.port_vlan_wan",
    "network_maintenance.device_inventory",
    "network_maintenance.coverage_tier",
    "network_maintenance.firmware_change",
    "network_maintenance.firmware_baseline_missing",
    "network_maintenance.patch_window_change_calendar_missing",
    "network_maintenance.oem_tac_escalation_missing",
    "network_maintenance.vlan_port_audit_cadence_missing",
    "network_maintenance.circuit_demarc_responsibility_missing",
})


def _router_pack_menu() -> list[tuple[str, str]]:
    """(pack_id, display_name) for every pack the router may choose from."""
    try:
        path = Path(__file__).resolve().parents[1] / "world_model" / "data" / "domain_packs.yaml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        entries = raw if isinstance(raw, list) else (raw.get("packs") or [])
        return [
            (str(e.get("id") or e.get("pack_id")), str(e.get("display_name") or ""))
            for e in entries
            if isinstance(e, dict) and (e.get("id") or e.get("pack_id"))
        ]
    except Exception:
        return []


def _router_chat() -> tuple[Any | None, str]:
    """(client, model) for the LLM rung, or (None, "") when deliberately unwired.

    ``ORBITBRIEF_ROUTER_MODEL`` must be set explicitly — routing does NOT inherit
    ``ORBITBRIEF_CHAT_MODEL``. That default is qwen2.5:3b on dev, and a 3B model
    picking among 29 packs is not a router; the rung was measured on qwen3:14b.
    Silently inheriting it would look wired while answering worse than the head.
    """
    model = (os.environ.get("ORBITBRIEF_ROUTER_MODEL") or "").strip()
    base = (
        os.environ.get("ORBITBRIEF_ROUTER_BASE_URL")
        or os.environ.get("OLLAMA_BASE_URL")
        or ""
    ).strip()
    if not model or not base:
        return None, ""
    try:
        from orbitbrief_core.inference.client import OpenAIChatClient

        timeout = float(os.environ.get("ORBITBRIEF_ROUTER_TIMEOUT_S", "180") or 180)
        return (
            OpenAIChatClient(
                base_url=base,
                api_key=(os.environ.get("ORBITBRIEF_CHAT_API_KEY") or None),
                timeout_s=timeout,
            ),
            model,
        )
    except Exception:
        return None, ""


def _untruncate_report_atoms(report: Any, envelope: Any) -> Any:
    """Backfill the inspection report's per-artifact atom lists from the envelope.

    ``inspection.py`` lists at most ``_MAX_ATOMS_LISTED_PER_ARTIFACT`` (60) atoms
    per artifact. That is a dashboard-sizing decision — and 34 analytical
    builders read those same lists through ``_iter_atoms_with_files(report)``,
    so a display cap silently governs what the brief can know.

    Measured on Clayton 2026-08-13: 1907 atoms across 17 artifacts, 727 visible,
    **1180 hidden (62%)**. Clayton Homes CALC.xlsx alone lost 604 of 664 rows.

    What that cost, measured by running the builders against a truncated and an
    un-truncated report:

        build_money_mentions   28 -> 93      build_date_mentions  42 -> 77
        top money value    13,696 -> 149,764

    The executive summary quoted $13,696 on a $149,764 deal not because it chose
    badly but because every larger figure sat past row 60 — the real total was
    never a candidate.

    NOT explained by truncation, despite the obvious suspicion: acceptance_checks
    (0 -> 0), quantity_claims (0 -> 0), rfp_line_items (0 -> 0) and
    build_risk_register (4 -> 4) are unchanged with every atom visible. Their
    emptiness has some other cause and is still open.

    Backfilled rows carry every field the builders read (atom_type,
    authority_class, confidence, verified, text, locator, entity_keys,
    structured) but not the three dashboard-only flags — ``in_bundle``,
    ``cited_by_brain``, ``in_composed_brief`` — which no pm_handoff builder
    reads; only inspection.py does. Text keeps the report's 1200-char clamp so
    nothing downstream sees a longer string than it did before.

    No-op when either side is missing, so a caller without an envelope behaves
    exactly as it does today.
    """
    if not isinstance(report, dict) or not isinstance(envelope, dict):
        return report
    arts = report.get("artifacts")
    atoms = envelope.get("atoms")
    if not isinstance(arts, list) or not isinstance(atoms, list) or not atoms:
        return report
    by_art: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for a in atoms:
        if isinstance(a, dict):
            by_art[a.get("artifact_id")].append(a)
    for art in arts:
        if not isinstance(art, dict):
            continue
        rows = art.get("atoms")
        if not isinstance(rows, list):
            continue
        have = {r.get("id") for r in rows if isinstance(r, dict)}
        for a in by_art.get(art.get("artifact_id"), ()):
            aid = a.get("id")
            if aid in have:
                continue
            rows.append({
                "id": aid,
                "atom_type": a.get("atom_type"),
                "authority_class": a.get("authority_class"),
                "confidence": a.get("confidence"),
                "verified": a.get("verified"),
                "text": str(a.get("text") or "")[:1200],
                "locator": a.get("locator") or {},
                "entity_keys": list(a.get("entity_keys") or ()),
                "structured": dict(a.get("structured") or {}),
            })
    return report


class _BriefingChat:
    """Adapts OpenAIChatClient to the ``pm_briefing.ChatClient`` protocol.

    pm_briefing wants ``complete(system=..., user=...)``; the inference client
    takes a message list plus a model. Two shapes for the same thing, which is
    part of why the LLM overview path sat unused.
    """

    def __init__(self, client: Any, model: str) -> None:
        self._client, self._model = client, model

    def complete(self, *, system: str, user: str, temperature: float = 0.2) -> str:
        from orbitbrief_core.inference.client import ChatMessage

        return self._client.complete(
            [ChatMessage("system", system), ChatMessage("user", user)],
            model=self._model,
            temperature=temperature,
        )


def _raw_chat() -> tuple[Any | None, str]:
    """(OpenAIChatClient, model) — the INFERENCE protocol: complete(messages, model=).

    Distinct from _briefing_chat below, which wraps this in the pm_briefing
    protocol: complete(system=, user=). Two protocols for one idea is a trap, and
    it caught me: question_llm was handed the _BriefingChat wrapper and threw
    `_BriefingChat.complete() got an unexpected keyword argument 'model'` on
    every call, so the exposure generator produced zero questions live while
    looking wired. Callers must take the shape they actually speak.
    """
    model = (os.environ.get("ORBITBRIEF_CHAT_MODEL") or "").strip()
    base = (os.environ.get("OLLAMA_BASE_URL") or "").strip()
    if not model or not base:
        return None, ""
    try:
        from orbitbrief_core.inference.client import OpenAIChatClient

        timeout = float(os.environ.get("ORBITBRIEF_CHAT_TIMEOUT_S", "120") or 120)
        return (
            OpenAIChatClient(
                base_url=base,
                api_key=(os.environ.get("ORBITBRIEF_CHAT_API_KEY") or None),
                timeout_s=timeout,
            ),
            model,
        )
    except Exception:
        return None, ""


def _briefing_chat() -> tuple[Any | None, str]:
    """(client, model) for the executive-summary writer, or (None, "").

    Uses the general chat config — ORBITBRIEF_CHAT_MODEL against
    OLLAMA_BASE_URL, which is an OpenAI-compatible endpoint whatever it points
    at. Unset means no client, and the overview stays deterministic.
    """
    model = (os.environ.get("ORBITBRIEF_CHAT_MODEL") or "").strip()
    base = (os.environ.get("OLLAMA_BASE_URL") or "").strip()
    if not model or not base:
        return None, ""
    try:
        from orbitbrief_core.inference.client import OpenAIChatClient

        timeout = float(os.environ.get("ORBITBRIEF_CHAT_TIMEOUT_S", "120") or 120)
        return (
            _BriefingChat(
                OpenAIChatClient(
                    base_url=base,
                    api_key=(os.environ.get("ORBITBRIEF_CHAT_API_KEY") or None),
                    timeout_s=timeout,
                ),
                model,
            ),
            model,
        )
    except Exception:
        return None, ""


def _stash_router_diag(envelope: Any, diag: dict[str, Any]) -> None:
    """Keep the router's reasoning even when its answer is discarded.

    When the ladder declines, `service_routing` is dropped from the envelope so
    the distrusted head cannot win — which also removes the only place the
    provenance could have lived. The reason has to outlive the answer, or a
    declined rung is once again indistinguishable from a rung that never ran.
    """
    if isinstance(envelope, dict) and diag:
        envelope["service_routing_diagnostics"] = dict(diag)


def _resolve_service_routing(envelope: Any, case_dir: Path) -> dict[str, Any] | None:
    """Resolve ONE routing answer from the scope-router ladder.

    ``service_routing.primary`` decides ``project_mode``, which decides which
    questions the PM is asked. The contrastive head that used to decide it alone
    answered ``wireless`` on all six deals sampled 2026-08-12 — a constant
    function — including a 437-store technician dispatch job that was then asked
    for an AP count and an RF channel plan. The ladder tries the LLM first, falls
    back to the head only when the head is confident, and otherwise returns ``{}``
    meaning "no opinion", which leaves every keyword path deciding exactly as it
    does today. That is why this cannot regress routing.

    Unwired (no ``ORBITBRIEF_ROUTER_MODEL``) it is a pass-through: the head's own
    answer, unchanged.
    """
    head = envelope.get("service_routing") if isinstance(envelope, dict) else None
    try:
        from orbitbrief_core.world_model.scope_router import resolve_routing
    except Exception:
        return head if isinstance(head, dict) else None

    # The parser logs the exact string the head embedded; reuse it so the LLM
    # judges the same representation rather than a second, divergent one.
    scope_summary = ""
    if isinstance(head, dict):
        scope_summary = str(head.get("scope_summary") or "")
    chat, model = _router_chat()

    # Stamp the row with the deal it came from. training_row() accepts these and
    # my first cut passed neither, so every banked label was anonymous — fine for
    # counting, useless for the retrain it exists to feed: you cannot re-derive a
    # scope summary's deal, audit a suspicious label, or hold out by deal without
    # it. Empty strings are left in place rather than invented.
    project_id = str((envelope or {}).get("project_id") or "") if isinstance(envelope, dict) else ""
    compile_id = str((envelope or {}).get("compile_id") or "") if isinstance(envelope, dict) else ""

    def _sink(row: dict[str, Any]) -> None:
        # Serving the router IS the labelling campaign: bank one (scope, label)
        # pair per routed deal. Bookkeeping must never break a compile.
        try:
            row = dict(row)
            if not row.get("project_id"):
                row["project_id"] = project_id
            if not row.get("compile_id"):
                row["compile_id"] = compile_id
            with open(case_dir / "router_training_rows.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # Unwired is a pass-through by design: with no router model the head's own
    # answer stands, exactly as before this module existed.
    if chat is None or not model:
        return head if isinstance(head, dict) else None
    diag: dict[str, Any] = {}
    try:
        resolved = resolve_routing(
            envelope_routing=head if isinstance(head, dict) else None,
            scope_summary=scope_summary,
            packs=_router_pack_menu(),
            chat=chat,
            model=model,
            on_training_row=_sink,
            diagnostics=diag,
        )
    except Exception as exc:
        diag.update(rung="error", reason=f"{type(exc).__name__}: {exc}"[:200])
        _stash_router_diag(envelope, diag)
        return head if isinstance(head, dict) else None
    _stash_router_diag(envelope, diag)
    # `{}` is returned as `{}`, NOT collapsed to None. The two mean opposite
    # things and collapsing them is what let the head win:
    #
    #   None -> unwired / errored -> leave the envelope alone (pass-through)
    #   {}   -> wired, and the ladder declined -> the head must NOT be trusted
    #
    # `resolved or None` mapped {} to None, the write-back below was skipped, and
    # the envelope kept the parser's head answer — which question_engine reads
    # directly. So "no opinion" silently became "trust the head". Measured on
    # 02557291 2026-08-14: the LLM rung decided `staff_augmentation` on one run
    # and declined on the next, and the deal came out `wireless_install` at 0.8
    # confidence off a head that answered `wireless` on six consecutive sampled
    # deals. The PM was then asked for an AP count on a staff-aug job.
    return resolved if isinstance(resolved, dict) else None


def build_pm_handoff(case_dir: Path) -> PMHandoff:
    case_dir = Path(case_dir)
    # Inspection report — orchestrator emits ``90_inspection_report.json``,
    # boss-bundle layout copies it as ``inspection_report.json``.
    report = (
        _read_json(case_dir / "inspection_report.json")
        or _read_json(case_dir / "90_inspection_report.json")
    )
    # Full envelope, when compile_brief staged it. The inspection report lists at
    # most 60 atoms per artifact (_MAX_ATOMS_LISTED_PER_ARTIFACT) — fine for a
    # dashboard, wrong for arithmetic. Anything that must be COMPLETE rather than
    # representative reads this instead; see the margin view below.
    full_envelope = _read_json(case_dir / "00_envelope.json")
    if not (isinstance(full_envelope, dict) and full_envelope.get("atoms")):
        full_envelope = None
    # Every builder below reads atoms through the report. Un-truncate it once,
    # here, so none of them is reasoning about 38% of the deal.
    report = _untruncate_report_atoms(report, full_envelope)
    # Calibrator roll-up: ``BriefPipeline._run_stage`` writes per-pack
    # ``CalibratorReport`` JSON to ``<case>/60_calibrations/<pack_id>.json``.
    # We project a single top-level verdict for PM consumption: the
    # most-blocking individual verdict across every pack wins
    # (``reject`` > ``needs_review`` > ``auto_accept``). When no
    # calibration artifacts exist on disk (e.g. PMHandoff was built
    # directly from an inspection_report without running the full
    # pipeline), the field stays ``None``. Wiring point for live
    # integration: ``src/orbitbrief_core/orchestrator/pipeline.py``
    # populates the ``60_calibrations/`` directory.
    calibrator_verdict = _rollup_calibrator_verdict(case_dir)
    # SOW missingness — boss-bundle path writes per-case
    # ``sow_missingness.yaml``; auto-derive on the fly when only the
    # raw substrate dir is present.
    sow = _read_yaml(case_dir / "sow_missingness.yaml")
    if not sow:
        sow = _autogen_sow_missingness(case_dir)
    case_id = str(report.get("project_id") or sow.get("case_id") or case_dir.name)

    # v9: the trained service-router head writes envelope.service_routing
    # ({primary, confidence, ...}); the domain view leads with — and the SOW
    # activates — that routed primary instead of the old pack-prior top.
    envelope = (
        _read_json(case_dir / "00_envelope.json")
        or _read_json(case_dir / "envelope.json")
        or {}
    )
    service_routing = _resolve_service_routing(envelope, case_dir)
    # Write the resolved answer BACK onto the envelope. Everything downstream —
    # build_customer_questions, and through it detect_project_mode — reads
    # envelope["service_routing"] for itself rather than taking this variable, so
    # without this the ladder resolved one answer and the question engine used a
    # different one. Measured on Clayton 2026-08-12: DeepSeek returned
    # `staff_augmentation` (correct, banked in router_training_rows.jsonl with
    # head_agreed=False) while project_mode stayed `wireless_install` off the
    # head's answer, and the PM was still asked for an AP count. One resolved
    # routing answer has to mean one answer everywhere.
    if isinstance(envelope, dict) and isinstance(service_routing, dict):
        if service_routing:
            envelope["service_routing"] = service_routing
        else:
            # Wired, and the ladder declined. Dropping the key is the whole point
            # of "no opinion": it hands the decision to the keyword cascade, which
            # is what the ladder promises. Leaving the head in place instead is a
            # regression the ladder was built to prevent — and was silently
            # causing, because downstream reads the envelope rather than the
            # resolved answer.
            envelope.pop("service_routing", None)

    source_files, artifact_by_id = _build_source_files(report)
    sites = _build_site_summaries(report, case_dir)
    gaps = _semantic_dedupe_gaps(_build_gap_cards(sow))
    domains = _build_domains(report, sow, gaps, service_routing)
    facts, fact_quality_meta = _build_fact_cards(report, artifact_by_id)
    # Evidence-first curated asks (not the full YAML pack checklist).
    customer_questions, question_meta = build_customer_questions(
        gaps=gaps,
        sites=sites,
        envelope=envelope if isinstance(envelope, dict) else None,
        report=report if isinstance(report, dict) else None,
        case_dir=case_dir,
    )
    pool_raw = question_meta.get("pool") if isinstance(question_meta, dict) else None
    customer_questions_pool: list[GapCard] = []
    if isinstance(pool_raw, list):
        for row in pool_raw:
            if isinstance(row, GapCard):
                customer_questions_pool.append(row)
            elif isinstance(row, dict) and row.get("rule_id"):
                try:
                    customer_questions_pool.append(
                        GapCard(
                            rule_id=str(row.get("rule_id") or ""),
                            domain_id=str(row.get("domain_id") or ""),
                            domain_label=str(row.get("domain_label") or ""),
                            label=str(row.get("label") or ""),
                            severity=str(row.get("severity") or "warning"),
                            message=str(row.get("message") or ""),
                            suggested_open_question=str(
                                row.get("suggested_open_question") or ""
                            ),
                            observed_summary=str(row.get("observed_summary") or ""),
                            sources=list(row.get("sources") or [])
                            if isinstance(row.get("sources"), list)
                            else [],
                        )
                    )
                except (TypeError, ValueError):
                    continue
    # Keep meta lean for JSON — full pool is on the handoff field.
    if isinstance(question_meta, dict) and "pool" in question_meta:
        question_meta = {
            **question_meta,
            "pool": f"{len(customer_questions_pool)}_cards_on_handoff",
        }
    # Don't surface the same intent as both a gap/blocker and a curated question.
    gaps = _suppress_gaps_covered_by_questions(gaps, customer_questions)
    project_mode = str(question_meta.get("project_mode") or "")
    evidence_blob = ""
    if isinstance(envelope, dict):
        evidence_blob = "\n".join(
            str(a.get("text") or a.get("raw_text") or "")
            for a in (envelope.get("atoms") or [])
            if isinstance(a, dict)
        )
    gaps = _filter_gaps_for_project_mode(gaps, project_mode, evidence_blob=evidence_blob)
    # Rebuild domain rollups after mode-aware gap filtering so ops leftovers
    # do not inflate network_maintenance info counts on install deals.
    domains = _build_domains(report, sow, gaps, service_routing)
    domains = _filter_domains_for_project_mode(
        domains,
        project_mode,
        primary=str(
            (service_routing or {}).get("primary")
            if isinstance(service_routing, dict)
            else ""
        )
        or None,
    )
    # Drop/rewrite transcript scraps now that curated asks exist.
    facts, polish_meta = _polish_fact_cards(facts, customer_questions)
    fact_quality_meta = {**fact_quality_meta, **polish_meta}
    metrics = _build_metrics(report, sow, facts, gaps, sites)
    # Align metric counters with status (curated questions), not suppressed YAML gaps.
    metrics["blockers"] = sum(1 for q in customer_questions if q.severity == "blocker")
    metrics["warnings"] = sum(1 for q in customer_questions if q.severity == "warning")
    # The shortlist is capped and every real deal saturates it, so the two
    # counters above describe what the PM can SEE, not what is known. Publish the
    # pool totals beside them so "8 blockers" is never read as "8 left to clear".
    # Deliberately not folded into metrics["blockers"]: status/health_line are
    # driven by the curated shortlist, and the pool is an audit superset that is
    # itself capped (ORBITBRIEF_QUESTION_POOL_CAP), making it a floor, not a total.
    metrics["blockers_known"] = sum(
        1 for q in customer_questions_pool if q.severity == "blocker"
    )
    metrics["warnings_known"] = sum(
        1 for q in customer_questions_pool if q.severity == "warning"
    )
    metrics["questions_hidden"] = max(
        0, len(customer_questions_pool) - len(customer_questions)
    )
    metrics["project_mode"] = project_mode
    metrics["customer_question_engine"] = question_meta
    metrics["fact_quality"] = fact_quality_meta
    # Prefer project-mode label over pack primary when mode is more specific
    # (e.g. network_edge_install vs network_maintenance pack).
    mode_workstream = _project_mode_workstream_label(project_mode)
    if mode_workstream:
        metrics["top_workstream"] = mode_workstream
    # Status for the PM is driven by curated customer_questions (not the
    # full internal YAML gap list). Sites still gate "not ready".
    status, status_label = _derive_status(customer_questions, sow, report, sites)
    sa_focus = _build_sa_focus(domains, project_mode=project_mode)
    report_for_label = dict(report) if isinstance(report, dict) else {}
    if isinstance(envelope, dict) and "envelope" not in report_for_label:
        report_for_label["envelope"] = envelope
    display_label = display_case_label(
        case_id,
        report=report_for_label,
        sow=sow if isinstance(sow, dict) else None,
        case_dir_name=case_dir.name if case_dir else None,
    )
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
    # Built AFTER rollups and dates: the summary needs the equipment and the
    # window, and it used to run first and know neither.
    one_line = _build_one_line_summary(
        display_label,
        domains,
        sites,
        customer_questions,
        project_mode=project_mode,
        site_rollups=site_rolls,
        date_mentions=dates,
    )
    actions = build_action_items(gaps=gaps, risk_rows=risks, schedule_phases=phases)
    pagers = build_stakeholder_pagers(
        gaps=gaps,
        risk_rows=risks,
        money_mentions=money,
        reconciliation_flags=flags,
        case_id=case_id,
    )
    compliance = build_compliance_callouts(report)
    allocations = (
        parse_bom_allocations(report)
        + parse_site_allocation_matrix(report)
        + build_site_quantity_allocations(report)
    )
    accept_checks = build_acceptance_checks(report)
    rfp_items = build_rfp_line_items(report)
    contacts = build_stakeholder_contacts(report)
    exclusions = build_exclusions(report)
    responsibilities = build_responsibilities(report)
    qty_claims = build_quantity_claims(report)
    qty_contradictions = find_quantity_contradictions(qty_claims)
    # Money is computed BEFORE the summary now: the executive overview writer
    # needs the deal's commercial shape, and it used to run first and reason
    # about cost with no idea what the engagement was worth.
    margin = build_margin_view(full_envelope or report)
    _briefing_chat_client, _briefing_model = _briefing_chat()
    exec_summary = build_executive_summary(
        case_id=display_label,
        status=status,
        status_label=status_label,
        one_line_summary=one_line,
        money_mentions=money,
        risks=risks,
        gaps=customer_questions,
        sites=sites,
        domains=domains,
        project_mode=project_mode,
        responsibilities=responsibilities,
        exclusions=exclusions,
        # The evidence pack is built FROM these. Without them the writer has
        # only sites/gaps/money to work with, which is why the overview read as
        # a list of fragments rather than a briefing — the deal's own sentences
        # were never handed to it.
        narrative_atoms=(full_envelope or {}).get("atoms") or [],
        chat_client=_briefing_chat_client,
        overview_model=_briefing_model,
        margin_view=asdict(margin) if hasattr(margin, "__dataclass_fields__") else margin,
    )
    # Tier 1-4 PM intelligence
    # (margin computed above, before the summary — it feeds the overview writer.
    # It must read the FULL envelope, not the inspection report's 60-per-file
    # sample: a truncated corpus silently yields $0, which reads as "no pricing
    # found" rather than "I only looked at part of it".)
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
    ocr_status = build_ocr_backend_status()
    crm_detections = build_crm_detection(report)
    parser_quality = build_parser_quality_score(report)
    run_tele = build_run_telemetry(report, case_dir)
    urgency = build_urgency_signals(report)
    # Answer slots track the curated customer-facing list, not every YAML gap.
    customer_slots = build_customer_answer_slots(customer_questions)
    # Drift snapshot uses the corpus history ledger; same logic the
    # compile_brief.py append step uses, so the comparison is
    # against the LAST entry for this case_id.
    import os as _os
    drift_history_path = _os.environ.get(
        "ORBITBRIEF_CORPUS_HISTORY",
        str((case_dir / ".orbitbrief_history.jsonl").resolve()) if case_dir else "",
    )
    current_run_for_drift = {
        "deal_value_usd": int((margin.deal_total or 0)),
        "final_margin_pct": float(margin.margin_pct or 0),
        "sites_count": len(sites),
        "phase_count": len(phases),
    }
    drift = build_drift_snapshot(
        case_id=case_id,
        current_run=current_run_for_drift,
        history_path=drift_history_path,
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
        # An exec sponsor is detected when ANY contact directory row
        # has a sponsor-shaped role label OR a sponsor-shaped role
        # cell appeared in any structured atom. The previous logic
        # only checked gap messages — gaps never contain "sponsor"
        # so this was always false on every project.
        has_executive_stakeholder=any(
            any(token in (c.role or "").lower() for token in (
                "sponsor", "executive", "vp", "vice president",
                "ceo", "cfo", "cto", "cio", "ciso", "head of",
                "director of", "managing director", "chief",
            ))
            for c in contacts
        ) or any(
            "executive sponsor" in (a.get("text") or "").lower()
            or "vp " in (a.get("text") or "").lower()
            for art in (report.get("artifacts") or [])
            for a in (art.get("atoms") or [])
        ),
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
        customer_questions_pool=customer_questions_pool,
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
        ocr_backend_status=asdict(ocr_status),
        crm_detections=[asdict(c) for c in crm_detections],
        parser_quality_score=parser_quality,
        run_telemetry=asdict(run_tele),
        drift_snapshot=asdict(drift),
        urgency_signals=[asdict(u) for u in urgency],
        customer_answer_slots=[asdict(c) for c in customer_slots],
        calibrator_verdict=calibrator_verdict,
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


# A deal with this many distinct structured sites is a rollout, not a pile of
# address-line false positives. Deliberately low: the guard it relaxes only ever
# fires on clusters of <=2 atoms, and a genuine 10-site rollout has the same
# per-site evidence shape as a 400-site one.
_ROLLOUT_SITE_FLOOR = 10

# "HC-1023" / "hc 1023" / "SITE 42" — an identifier the clusterer normalised,
# carrying no facility name.
_SITE_CODE_RE = re.compile(r"^[a-z]{1,4}[\s\-_]?\d{1,6}$", re.I)


def _slugify_site_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").lower()).strip("_")


def _slugs_compatible(a: str, b: str) -> bool:
    """True when two site slugs denote the same place.

    Containment rather than equality: the clusterer's "clayton_homes_of_marion"
    and an atom's "clayton_homes_of_marion_sc" are one site, and emitting both
    double-counts a rollout.

    The containment must land on a token boundary. Bare ``startswith`` merges
    "..._town_1" with "..._town_10" through "..._town_19", which silently
    collapsed a 40-site rollout to 10 — the same under-count this whole change
    exists to fix, reintroduced one layer down.
    """
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return longer.startswith(shorter + "_")


def _prefer_structured_site_name(
    name: str, structured_by_slug: dict[str, SiteSummary]
) -> str:
    """Swap a normalised site code for the facility name the extractor resolved.

    ``11_site_reality`` reduces "HC-1023 Clayton Homes of Moncks Corner" to the
    canonical name "hc 1023" and drops the rest, so the PM sees a code. The atom
    still carries the real name; use it when the cluster name is only an id.
    """
    if not _SITE_CODE_RE.match(str(name or "").strip()):
        return name
    slug = _slugify_site_name(name)
    hit = structured_by_slug.get(slug)
    if hit and hit.name and not _SITE_CODE_RE.match(hit.name.strip()):
        return hit.name
    for cand_slug, cand in structured_by_slug.items():
        if _slugs_compatible(slug, cand_slug) and not _SITE_CODE_RE.match(cand.name.strip()):
            return cand.name
    return name


def _roster_rows(doc: Any) -> list[dict[str, Any]]:
    """Pull the site roster out of either shape that carries one.

    The envelope stores ``site_readiness`` as a **dict** — ``sites``,
    ``site_count``, ``avg_readiness``, … — with the 437 rows nested under
    ``sites``. The handoff's own enriched roster is a plain list. Reading the
    envelope's dict as if it were a list is what silently returned zero sites
    and fell through to cluster derivation.
    """
    if not isinstance(doc, dict):
        return []
    sr = doc.get("site_readiness")
    if isinstance(sr, list):
        return [r for r in sr if isinstance(r, dict)]
    if isinstance(sr, dict):
        rows = sr.get("sites")
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    return []


# "HC-100" / "hc 100" — an identifier, not something to show a PM.
_ALIAS_CODE_RE = re.compile(r"^[a-z]{1,4}[\s\-_]?\d{1,6}$", re.I)


# "615 N 48th St" / "Phoenix, AZ 85008" — a location line, not a facility name.
_ADDRESS_RE = re.compile(r"^\d|,\s*[A-Z]{2}\s*\d{5}|\b\d{5}(?:-\d{4})?$")


def _looks_like_address(text: str) -> bool:
    return bool(_ADDRESS_RE.search(str(text or "").strip()))


def _is_slug_alias(text: str) -> bool:
    """True for the extractor's own key, e.g. ``site:maricopa_county_iron_...``."""
    t = str(text or "")
    return t.startswith("site:") or ("_" in t and " " not in t)


# Tokens that should not be title-cased into "Az" / "Nc" when humanising a slug.
_UPPER_TOKENS = frozenset(
    {
        "az", "nc", "sc", "ga", "tn", "tx", "ca", "fl", "va", "pa", "ny", "oh",
        "il", "mi", "wa", "co", "mo", "ok", "ar", "ms", "al", "ky", "in", "ia",
        "hq", "dc", "idf", "mdf", "poc", "ap", "us", "usa",
    }
)


def _humanize_site_token(text: str) -> str:
    """Turn ``site:maricopa_county_iron_mountain`` into readable words."""
    t = str(text or "").strip()
    if t.startswith("site:"):
        t = t[5:]
    t = t.replace("_", " ").replace("-", " ").strip()
    if not t:
        return ""
    words = [w for w in t.split() if w]
    out = []
    for w in words:
        # Keep short all-caps tokens as acronyms ("HC", "AZ", "IDF"); title-case
        # long shouted ones ("MARICOPA" -> "Maricopa").
        if w.lower() in _UPPER_TOKENS or (w.isupper() and len(w) <= 4):
            out.append(w.upper())
        else:
            out.append(w.capitalize())
    return " ".join(out)


def _display_name_from_aliases(aliases: Any) -> str:
    """Pick the facility name out of an envelope row's aliases.

    Rows carry ``["HC-100", "Clayton Homes of Laurinburg", "12021 Andrew
    Jackson Highway"]`` — the id, the name, then the street. Take the first
    entry that is neither a bare code nor an address (addresses lead with a
    house number), so the PM sees "Clayton Homes of Laurinburg".

    Not every deal has that. Where sites are mentioned in prose rather than a
    roster table, the extractor produces no facility name and the row carries
    only a slug, or a bare code plus its address. Those are still real sites, so
    present what is there rather than printing ``site:maricopa_county_iron_...``
    at a PM:

    * slug only            -> "Maricopa County Iron Mountain Data Centers Azs 1"
    * code + address parts -> "Maricopa County - 615 N 48th St, Phoenix, AZ 85008"

    Nothing here invents data; it only formats what the row already holds.
    """
    if not isinstance(aliases, list):
        return ""
    texts = [str(a or "").strip() for a in aliases]
    texts = [t for t in texts if t]
    if not texts:
        return ""

    # 1. A real facility name: not a code, not an address, not a slug.
    #    An all-caps token like "MARICOPA-COUNTY" is an identifier, not a name —
    #    let it fall through so it gets its address attached below.
    for text in texts:
        if (
            _ALIAS_CODE_RE.match(text)
            or text[:1].isdigit()
            or _is_slug_alias(text)
            or (text.upper() == text and any(c.isalpha() for c in text))
            or _looks_like_address(text)
        ):
            continue
        return text

    # 2. Only a code (plus, usually, its address lines). Join them so the PM
    #    sees a place instead of an identifier.
    code = next((t for t in texts if _ALIAS_CODE_RE.match(t) or t.isupper()), "")
    address = [t for t in texts if t is not code and (t[:1].isdigit() or "," in t)]
    if code:
        label = _humanize_site_token(code)
        return f"{label} - {', '.join(address)}" if address else label

    # 3. Slug only — the extractor's own key is the only thing we have.
    for text in texts:
        if _is_slug_alias(text):
            return _humanize_site_token(text)
    return texts[0]


def _sites_from_canonical_roster(
    report: dict[str, Any], case_dir: Path | None
) -> list[SiteSummary]:
    """Project the site panel from ``site_readiness`` — the canonical roster.

    ``envelope.py`` already resolves every site once, with name, address and a
    readiness score, and the handoff carries all of it. Re-deriving the panel
    from ``site_reality`` clusters is the same duplicated-consumer bug that
    f257ba4 removed seven of: a 437-site rollout rendered as three entries named
    "hc 1023", while ``site_readiness`` beside it held all 437 fully populated.

    Read the roster; do not rebuild it.
    """
    rows = _roster_rows(report)
    if not rows and case_dir is not None:
        # The worker writes ``envelope.json`` beside the artifacts; the
        # ``00_`` prefix only exists in the orchestrator's own case layout.
        env = (
            _read_json(case_dir / "envelope.json")
            or _read_json(case_dir / "00_envelope.json")
            or {}
        )
        rows = _roster_rows(env)
    if not rows:
        return []

    out: list[SiteSummary] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        # Envelope rows key the site as ``site`` ("site:hc_100"); the handoff's
        # own enriched roster uses ``site_slug`` + ``name``. Accept both.
        slug = str(row.get("site_slug") or row.get("site") or "").strip()
        label = str(row.get("name") or "").strip() or _display_name_from_aliases(
            row.get("aliases")
        )
        if not label:
            # Still a real site — fall back to the slug rather than dropping it.
            label = slug.split(":", 1)[-1].replace("_", " ").strip()
        if not label:
            continue
        key = slug or label.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(
            SiteSummary(
                name=label,
                kind="physical_site",
                publishable=True,
                member_evidence_count=int(
                    row.get("atom_count") or row.get("signal_count") or 0
                ),
                artifact_count=0,
            )
        )
    return out


def _build_site_summaries(report: dict[str, Any], case_dir: Path | None = None) -> list[SiteSummary]:
    # Canonical roster first. The cluster derivation below stays only as a
    # fallback for briefs built before site_readiness existed.
    roster = _sites_from_canonical_roster(report, case_dir)
    if roster:
        return sorted(roster, key=lambda s: (not s.publishable, s.name))

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

    # Structured physical_site atoms are the ground truth the extractor already
    # resolved (site_id + name). Read them once, from the envelope as well as the
    # report — the report's cluster summary does not carry them, so anything that
    # only consults `report` silently sees zero sites.
    report_atoms = _iter_report_atoms(report)
    # Gate on the absence of SITE atoms, not on an empty atom list. The report
    # carries plenty of other atoms while omitting physical_site entirely, so a
    # "is it empty?" check reads as satisfied and the envelope is never opened —
    # which is the same mistake as gating the recovery below on `if not out`.
    if case_dir is not None and not any(
        a.get("atom_type") == "physical_site" for a in report_atoms
    ):
        envelope = (
            _read_json(case_dir / "00_envelope.json")
            or _read_json(case_dir / "envelope.json")
            or {}
        )
        if isinstance(envelope, dict):
            env_atoms = envelope.get("atoms") or []
            if env_atoms:
                report_atoms = list(report_atoms) + list(env_atoms)
    structured_sites = _site_summaries_from_physical_atoms({"atoms": report_atoms})
    # A national rollout is not a pile of false positives. When the extractor
    # resolved many distinct structured sites, each one legitimately appears in
    # only one or two documents, which is exactly the shape the micro-cluster
    # guard below was written to discard.
    rollout_mode = len(structured_sites) >= _ROLLOUT_SITE_FLOOR

    out: list[SiteSummary] = []
    physical_slugs = _physical_site_slugs(report)
    structured_by_slug = {_slugify_site_name(s.name): s for s in structured_sites}
    for cluster in (report.get("site_reality") or {}).get("clusters") or []:
        name = str(cluster.get("canonical_name") or cluster.get("cluster_id") or "Unknown site")
        # site_reality normalises "HC-1023" to "hc 1023" and drops the facility
        # name the extractor already had. Recover it rather than shipping a code.
        name = _prefer_structured_site_name(name, structured_by_slug)
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
        # Audit fix: orphan / micro-cluster sites are usually false
        # positives from address-line parsing ("Building C" inside
        # an address) or device-acronym parsing ("warehouse RF"
        # where RF is read as a site code). Drop when:
        #   * tiny cluster (≤ 2 atoms from ≤ 2 artifacts), OR
        #   * canonical name's tail token is a known device
        #     acronym (rf / ap / vms / dc / ip / poe / etc.)
        device_acronym_suffixes = {
            "rf", "ap", "aps", "vms", "ip", "poe", "ups", "pdu",
            "dc", "msa", "nda", "sla", "kvm", "san", "lan", "wan",
        }
        last_tok = name.lower().split()[-1] if name else ""
        looks_device_shaped = last_tok in device_acronym_suffixes
        if looks_device_shaped:
            continue
        if (member_count <= 2 and artifact_count <= 2) and not rollout_mode:
            continue
        cluster_slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        if not physical_slugs or cluster_slug not in physical_slugs:
            continue
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
    # Merge structured sites the clusterer missed. This must NOT be gated on an
    # empty `out`: a rollout where clustering keeps three sites and drops four
    # hundred is the failure this recovers, and "three" is truthy. Gating it is
    # how 437 resolved site atoms shipped as 3 sites named "hc 1023".
    existing_slugs = {_slugify_site_name(s.name) for s in out}
    for extra in structured_sites:
        slug = _slugify_site_name(extra.name)
        if any(_slugs_compatible(slug, e) for e in existing_slugs):
            continue
        out.append(extra)
        existing_slugs.add(slug)
    return sorted(out, key=lambda s: (not s.publishable, s.name))


def _iter_report_atoms(report: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(atom: Any) -> None:
        if not isinstance(atom, dict):
            return
        aid = str(atom.get("id") or id(atom))
        if aid in seen:
            return
        seen.add(aid)
        out.append(atom)

    for atom in report.get("atoms") or []:
        add(atom)
    for atom in report.get("atom_lineage") or []:
        add(atom)
    for artifact in report.get("artifacts") or []:
        if isinstance(artifact, dict):
            for atom in artifact.get("atoms") or []:
                add(atom)
    return out


def _site_summaries_from_physical_atoms(report: dict[str, Any]) -> list[SiteSummary]:
    """Fallback for thin deals where the only direct site evidence is the site atom."""
    atoms = _iter_report_atoms(report)
    physical_atoms = [a for a in atoms if a.get("atom_type") == "physical_site"]
    has_location_backed_site = any(_physical_atom_has_location(a) for a in physical_atoms)
    by_slug_count: Counter[str] = Counter()
    for atom in atoms:
        for key in atom.get("entity_keys") or []:
            if isinstance(key, str) and key.startswith("site:"):
                by_slug_count[key.split(":", 1)[1]] += 1

    out: list[SiteSummary] = []
    seen: set[str] = set()
    for atom in physical_atoms:
        if has_location_backed_site and not _physical_atom_has_location(atom):
            continue
        value = atom.get("value") or atom.get("structured") or {}
        if not isinstance(value, dict):
            value = {}
        site_keys = [
            key.split(":", 1)[1]
            for key in atom.get("entity_keys") or []
            if isinstance(key, str) and key.startswith("site:")
        ]
        slug = site_keys[0] if site_keys else ""
        if not slug or slug in seen or _is_vendor_site_key(slug):
            continue
        seen.add(slug)
        name = str(
            value.get("name")
            or value.get("facility_name")
            or getattr(atom, "raw_text", "")
            or atom.get("raw_text")
            or slug
        ).strip()
        if not name:
            name = slug.replace("_", " ").title()
        out.append(
            SiteSummary(
                name=name,
                kind="physical_site",
                publishable=True,
                member_evidence_count=max(1, by_slug_count.get(slug, 1)),
                artifact_count=1,
            )
        )
    return out


def _physical_atom_has_location(atom: dict[str, Any]) -> bool:
    value = atom.get("value") or atom.get("structured") or {}
    if not isinstance(value, dict):
        return False
    street = str(value.get("street_address") or value.get("address") or "").strip()
    city = str(value.get("city") or "").strip()
    state = str(value.get("state") or "").strip()
    zipc = str(value.get("zip") or value.get("postal_code") or "").strip()
    if street and (city or state or zipc):
        return True
    if street and re.search(r"\b\d{1,6}\b", street):
        return True
    return bool(city and state)


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


def _semantic_dedupe_gaps(gaps: list[GapCard]) -> list[GapCard]:
    """Collapse paraphrase-duplicate gaps/blockers to one canonical ask."""
    if len(gaps) < 2:
        return gaps

    def score(g: GapCard) -> tuple:
        return (
            -SEVERITY_SORT.get(g.severity, 9),
            min(len(g.suggested_open_question or g.message or ""), 240) / 240.0,
        )

    kept, _meta = semantic_dedupe(
        gaps,
        text_fn=lambda g: g.suggested_open_question or g.message or "",
        score_fn=score,
    )
    return sorted(kept, key=lambda g: (SEVERITY_SORT.get(g.severity, 9), g.domain_label, g.label))


# UC / Teams-room AV without a DSP/control stack should not ask Crestron/Q-SYS
# acceptance checklists. Photo-backed Neat/Yealink rooms trip this often.
_AV_DSP_CONTROL_GAP_IDS = frozenset(
    {
        "audio_visual.dsp_control",
        "audio_visual.acceptance",
    }
)
_AV_DSP_EVIDENCE_RE = re.compile(
    r"(?i)\b(?:dsp|crestron|extron|q[\-\s]?sys|biamp|tesira|symetrix|"
    r"control\s+(?:processor|system)|programming\s+acceptance)\b"
)


def _filter_gaps_for_project_mode(
    gaps: list[GapCard],
    project_mode: str,
    *,
    evidence_blob: str = "",
) -> list[GapCard]:
    """Drop checklist leftovers that do not apply to the detected project mode.

    Curated customer questions already gate YAML safety-net rows by
    ``domain_ids_allowed_for_mode``. Apply the same domain gate to the gap
    list so secondary packs weakly selected by keyword noise (UC "camera" →
    VMS, HDMI "cable" → structured cabling) cannot flood an AV handoff.
    """
    mode = (project_mode or "").strip()
    allow = domain_ids_allowed_for_mode(mode)
    filtered = gaps
    if allow is not None:
        filtered = [
            g for g in gaps if g.domain_id in allow or g.domain_id == "global"
        ]
    if mode == MODE_NETWORK_EDGE_INSTALL:
        filtered = [
            g for g in filtered if g.rule_id not in _INSTALL_IRRELEVANT_GAP_IDS
        ]
    if mode == MODE_AV and not _AV_DSP_EVIDENCE_RE.search(evidence_blob or ""):
        filtered = [g for g in filtered if g.rule_id not in _AV_DSP_CONTROL_GAP_IDS]
    return filtered


def _filter_domains_for_project_mode(
    domains: list[DomainSummary],
    project_mode: str,
    *,
    primary: str | None = None,
) -> list[DomainSummary]:
    """Hide out-of-scope secondary packs once their gaps have been pruned."""
    allow = domain_ids_allowed_for_mode(project_mode)
    if allow is None:
        return domains
    primary_id = (primary or "").strip()
    kept: list[DomainSummary] = []
    for d in domains:
        if d.domain_id in allow or d.domain_id == "global":
            kept.append(d)
            continue
        if primary_id and d.domain_id == primary_id:
            kept.append(d)
            continue
        # Belts: keep only if mode filter somehow left residual gaps.
        if d.blockers or d.warnings or d.info:
            kept.append(d)
    return kept


def _suppress_gaps_covered_by_questions(
    gaps: list[GapCard],
    questions: list[GapCard],
) -> list[GapCard]:
    """Drop gaps whose intent is already covered by a curated customer question.

    If a covered gap is a blocker and the matching question is only a warning,
    promote the question severity so the PM still sees blocker urgency — once.
    """
    if not gaps or not questions:
        return gaps
    from dataclasses import replace

    q_texts = [(q.suggested_open_question or q.message or "") for q in questions]
    # Mutable parallel list so we can promote severity on the caller's list.
    questions[:] = list(questions)
    kept: list[GapCard] = []
    for g in gaps:
        g_text = g.suggested_open_question or g.message or ""
        if not g_text:
            kept.append(g)
            continue
        if not is_near_duplicate_of_any(g_text, q_texts):
            kept.append(g)
            continue
        # Covered by a curated question — optionally upgrade that question.
        if g.severity == "blocker":
            for i, q in enumerate(questions):
                q_text = q.suggested_open_question or q.message or ""
                if is_near_duplicate_of_any(g_text, [q_text]):
                    if SEVERITY_SORT.get(q.severity, 9) > SEVERITY_SORT.get("blocker", 0):
                        questions[i] = replace(q, severity="blocker")
                    break
        # else: drop gap (do not keep duplicate surface)
    return kept


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


def _build_domains(
    report: dict[str, Any],
    sow: dict[str, Any],
    gaps: list[GapCard],
    service_routing: dict[str, Any] | None = None,
) -> list[DomainSummary]:
    pack_prior = report.get("pack_prior") or {}
    selected = set(pack_prior.get("selected_pack_ids") or [])
    top = pack_prior.get("top_pack_id")
    if top:
        selected.add(top)
    active = set(sow.get("active_domain_ids") or [])
    gap_counts: dict[str, Counter] = defaultdict(Counter)
    for g in gaps:
        gap_counts[g.domain_id][g.severity] += 1
    domain_ids = sorted(selected | active | set(gap_counts.keys()))
    # Per-pack confidence comes from the pack_prior router's ranking
    # output: ``inspection_report.pack_prior.top_scores[]`` carries
    # ``{pack_id, raw_score, confidence, matched_keywords}`` rows. We
    # also include the top-level ``top_confidence`` as a fallback for
    # ``top_pack_id`` when ``top_scores`` is truncated. If neither
    # source has a score for a domain id, ``score`` stays None so
    # consumers can distinguish "unscored" from a real 0.0.
    score_by_id: dict[str, float] = {}
    for row in pack_prior.get("top_scores") or []:
        pid = row.get("pack_id")
        conf = row.get("confidence")
        if pid and conf is not None:
            try:
                score_by_id[str(pid)] = float(conf)
            except (TypeError, ValueError):
                continue
    if top and top not in score_by_id and pack_prior.get("top_confidence") is not None:
        try:
            score_by_id[str(top)] = float(pack_prior.get("top_confidence"))
        except (TypeError, ValueError):
            pass
    # v9: lead with the trained service-router head's primary (not the pack-prior
    # top, which can be an incidentally high-scoring pack like cabling) and use the
    # head's confidence as the domain score — so "Open work by domain" reflects the
    # actual routed service. Falls back to pack-prior when the head abstains.
    from orbitbrief_core.validator.sow_completeness import _router_primary
    sr_primary, sr_conf = _router_primary(service_routing)
    if sr_primary:
        selected.add(sr_primary)
        if sr_primary not in domain_ids:
            domain_ids = sorted(set(domain_ids) | {sr_primary})
        if sr_conf > 0:
            score_by_id[sr_primary] = sr_conf
        top = sr_primary
    out = [
        DomainSummary(
            domain_id=d,
            label=domain_label(d),
            selected_by_router=d in selected,
            active_for_sow=d in active,
            blockers=gap_counts[d]["blocker"],
            warnings=gap_counts[d]["warning"],
            info=gap_counts[d]["info"],
            pack_name=domain_label(d) or d,
            score=score_by_id.get(d),
        )
        for d in domain_ids
    ]
    return sorted(
        out,
        key=lambda d: (
            0 if d.domain_id == sr_primary else 1,  # routed primary leads the view
            -(d.blockers * 100 + d.warnings * 10 + d.info),
            d.label,
        ),
    )


def _build_fact_cards(
    report: dict[str, Any], artifact_by_id: dict[str, dict[str, Any]]
) -> tuple[dict[str, list[EvidenceCard]], dict[str, Any]]:
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
            "deal_metadata": 15,  # weak default — chat often lands here
        }.get(atom_type, 30)
        if str(atom.get("verified") or "") == "verified":
            type_bonus += 10
        if (atom.get("downstream") or {}).get("bundled"):
            type_bonus += 5
        text = str(atom.get("text") or atom.get("raw_text") or "")
        # AV install gold (VESA / ceiling tiles / behind-wall / HDMI keepers)
        # must outrank verified SOW boilerplate risks (70+10=80) for the 12-card cap.
        if is_av_install_gold_fact(text):
            type_bonus = max(type_bonus, 95)
        if len(text) > 500:
            type_bonus -= 20
        return type_bonus, float(atom.get("confidence") or 0.0)

    lineage = list(report.get("atom_lineage") or [])
    # Prefer envelope atoms when lineage lacks value/flags (common on worker path).
    envelope_atoms = []
    env = report.get("envelope") if isinstance(report.get("envelope"), dict) else None
    if not env:
        # Some reports nest atoms at top level only via lineage; envelope may be absent.
        envelope_atoms = list(report.get("atoms") or [])
    else:
        envelope_atoms = list(env.get("atoms") or [])
    source_atoms: list[dict[str, Any]] = lineage if lineage else envelope_atoms
    # Merge envelope value/flags onto lineage rows by id when present.
    by_id = {
        str(a.get("id") or a.get("atom_id") or ""): a
        for a in envelope_atoms
        if isinstance(a, dict)
    }
    merged: list[dict[str, Any]] = []
    for atom in source_atoms:
        if not isinstance(atom, dict):
            continue
        aid = str(atom.get("id") or atom.get("atom_id") or "")
        env_a = by_id.get(aid) or {}
        row = dict(atom)
        if env_a.get("value") is not None and row.get("value") is None:
            row["value"] = env_a.get("value")
        # Parser marks chat filler on ``structured`` (kind=conversation_meta).
        if env_a.get("structured") and not row.get("structured"):
            row["structured"] = env_a.get("structured")
        if env_a.get("review_flags") and not row.get("review_flags"):
            row["review_flags"] = env_a.get("review_flags")
        if not row.get("text") and env_a.get("text"):
            row["text"] = env_a.get("text")
        if not row.get("raw_text") and env_a.get("raw_text"):
            row["raw_text"] = env_a.get("raw_text")
        merged.append(row)

    filtered, quality_meta = filter_pm_visible_atoms(merged)

    for atom in sorted(filtered, key=score, reverse=True):
        atom_type = str(atom.get("atom_type") or "")
        text = str(atom.get("text") or atom.get("raw_text") or "")
        if not text or len(text.strip()) < 8:
            continue
        claim = polish_fact_claim(text)
        if not claim:
            continue
        # Bucket from the polished claim (raw chat often mis-routes).
        category = classify_fact_category(atom_type, claim)
        claim_l = claim.lower()
        if any(
            x in claim_l
            for x in (
                "change order",
                "survey charge",
                "per-site fee",
                "per site fee",
                "cdw us paper",
                "us paper",
                "billing",
                "payment",
            )
        ):
            category = "commercial"
        if category not in cards:
            category = "scope"
        key = normalize_for_dedupe(claim)[:200]
        if key in seen:
            continue
        artifact = artifact_by_id.get(str(atom.get("artifact_id") or ""), {})
        card = EvidenceCard(
            title=_fact_title(atom_type, category),
            category=category,
            text=compact_text(claim, 340),
            source=SourcePointer(
                filename=str(artifact.get("filename") or atom.get("artifact_id") or "unknown source"),
                locator=_format_locator(atom.get("locator") or {}),
            ),
            confidence=_maybe_float(atom.get("confidence")),
            verified=str(atom.get("verified") or ""),
            internal_id=str(atom.get("id") or ""),
        )
        bucket = cards[category]
        if len(bucket) < MAX_FACTS_PER_CATEGORY:
            seen.add(key)
            bucket.append(card)
            continue
        # Category full: let install gold displace the weakest non-gold card.
        if is_av_install_gold_fact(claim):
            replace_at = None
            weakest = None
            for i, existing in enumerate(bucket):
                if is_av_install_gold_fact(existing.text or ""):
                    continue
                conf = float(existing.confidence or 0.0)
                if weakest is None or conf < weakest:
                    weakest = conf
                    replace_at = i
            if replace_at is not None:
                seen.add(key)
                bucket[replace_at] = card
    return {k: v for k, v in cards.items() if v}, quality_meta


def _polish_fact_cards(
    facts: dict[str, list[EvidenceCard]],
    customer_questions: list[GapCard],
) -> tuple[dict[str, list[EvidenceCard]], dict[str, Any]]:
    """Second pass: drop facts that only restate curated questions."""
    q_texts = [
        (q.suggested_open_question or q.message or "")
        for q in customer_questions
    ]
    out: dict[str, list[EvidenceCard]] = {}
    dropped = 0
    for cat, cards in facts.items():
        kept: list[EvidenceCard] = []
        for card in cards:
            # Keep install gold visible even when a curated question covers
            # the same territory (facts lane ≠ question queue).
            if is_av_install_gold_fact(card.text or ""):
                kept.append(card)
                continue
            if fact_overlaps_question(card.text, q_texts):
                dropped += 1
                continue
            kept.append(card)
        if kept:
            out[cat] = kept
    return out, {"fact_quality_dropped_question_overlap": dropped}


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


# Project modes whose copy should override the pack-primary workstream label.
# Pack routing may still select `network_maintenance` while the question engine
# correctly gates as an install / turn-up job.
_MODE_COPY_OVERRIDES: dict[str, str] = {
    "network_edge_install": "Network edge install",
    "wireless_install": "Wireless install",
    "cabling_install": "Structured cabling install",
    "av_install": "AV install",
    "access_control": "Access control",
    "alm": "Application / lifecycle management",
    "staff_aug": "Staff augmentation",
}

_MODE_SA_FOCUS: dict[str, list[str]] = {
    "network_edge_install": [
        "Confirm in-scope sites vs deferred, circuit readiness, and smart-hands "
        "boundary (rack/stack vs config/test/docs) before quoting.",
        "Lock first survey / POC site, SOP receipt + acceptance owner, and "
        "device-per-site topology before scheduling remote hands.",
    ],
}


def _project_mode_workstream_label(project_mode: str | None) -> str | None:
    mode = (project_mode or "").strip()
    if not mode or mode in {"generic", "network_ops"}:
        return None
    if mode in _MODE_COPY_OVERRIDES:
        return _MODE_COPY_OVERRIDES[mode]
    labeled = domain_label(mode)
    return labeled if labeled and labeled.lower() != mode.replace("_", " ") else None


def _build_sa_focus(
    domains: list[DomainSummary],
    *,
    project_mode: str | None = None,
) -> list[str]:
    out: list[str] = []
    mode_focus = _MODE_SA_FOCUS.get((project_mode or "").strip(), [])
    out.extend(mode_focus)
    if not mode_focus:
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


def _build_one_line_summary(
    case_id: str,
    domains: list[DomainSummary],
    sites: list[SiteSummary],
    gaps: list[GapCard],
    *,
    project_mode: str | None = None,
    site_rollups: list[Any] | None = None,
    date_mentions: list[Any] | None = None,
) -> str:
    """One line a PM can read instead of opening the brief.

    This used to be pure status — work type, site names, and two counts:

        "000050: Staff augmentation at Site 1, Site 2; 9 blocker and 3
         clarification(s) need PM/SA review."

    97 characters that restate the metadata already on screen. It says nothing
    about what is being installed, when, or what is actually blocking, so it
    previews nothing.

    What is added here is only what can be sourced: equipment kinds come from
    site_rollups, the window from date_mentions, and the leading blockers from
    the questions already computed. Deal VALUE is deliberately absent — on the
    audited deals margin_view reported deal_total 0 at low confidence, and a
    headline dollar figure that the margin view cannot stand behind is worse
    than no figure at all.
    """
    mode_label = _project_mode_workstream_label(project_mode)
    active = (
        [mode_label]
        if mode_label
        else [d.label for d in domains if d.selected_by_router or d.active_for_sow]
    )
    site_names = [s.name for s in sites if s.publishable]
    # Naming the first two sites is wrong twice over on a multi-site programme.
    # Clayton (438 stores) printed "at 5000 Clayton RD Maryville TN 37804 -
    # 5000 Clayton Rd, Maryville, TN 37804, Clayton Homes" — the SAME address in
    # two formats, and not a word about the other 436. Collapse labels where one
    # normalizes to a prefix of another, then lead with the count once there is
    # more than a handful, the way executive_summary already does.
    uniq: list[str] = []
    keys: list[str] = []
    for n in site_names:
        k = re.sub(r"[^a-z0-9]", "", (n or "").lower())
        if not k or any(k.startswith(p) or p.startswith(k) for p in keys):
            continue
        keys.append(k)
        uniq.append(n)
    if not uniq:
        where = "no confirmed site"
    elif len(uniq) <= 2:
        where = ", ".join(uniq)
    else:
        where = f"{len(site_names)} sites incl. {uniq[0]}"
    blockers = sum(1 for g in gaps if g.severity == "blocker")
    warnings = sum(1 for g in gaps if g.severity == "warning")
    label = (case_id or "This engagement").strip() or "This engagement"

    # What is being touched, from the site rollups.
    kinds: list[str] = []
    for roll in site_rollups or []:
        devices = getattr(roll, "devices", None)
        if devices is None and isinstance(roll, dict):
            devices = roll.get("devices")
        for dev in devices or []:
            d = str(dev).strip().lower()
            if d and d not in kinds:
                kinds.append(d)
    equip = ""
    if kinds:
        plural = [k if k.endswith("s") else f"{k}s" for k in kinds[:3]]
        equip = f" · {', '.join(plural)}{' and more' if len(kinds) > 3 else ''}"

    # When, from the dated evidence. A single date is a point, not a window.
    isos = sorted(
        {
            str((m.get("iso") if isinstance(m, dict) else getattr(m, "iso", "")) or "")[:10]
            for m in (date_mentions or [])
        }
        - {""}
    )
    window = ""
    if len(isos) >= 2:
        # Only claim a window the dates can support. One audited deal spanned
        # 2022-10-01 to 2026-05-26 — boilerplate and template dates swept in
        # alongside real ones. Printing that as the project window states
        # something false with the authority of a headline, so a span beyond ~18
        # months is treated as contaminated and simply omitted.
        try:
            from datetime import date

            lo = date.fromisoformat(isos[0])
            hi = date.fromisoformat(isos[-1])
            if 0 <= (hi - lo).days <= 550:
                window = f" · {isos[0]} to {isos[-1]}"
        except ValueError:
            window = ""
    elif len(isos) == 1:
        window = f" · dated {isos[0]}"

    # What is actually in the way — the leading blocker topics, not just a count.
    top = [
        (getattr(g, "label", "") or "").strip()
        for g in gaps
        if getattr(g, "severity", "") == "blocker"
    ]
    top = [t for t in top if t][:2]
    tail = (
        f" {blockers} blocker and {warnings} clarification(s) need PM/SA review"
        + (f" — leading: {'; '.join(top)}." if top else ".")
    )
    return (
        f"{label}: {', '.join(active[:4]) if active else 'unclassified scope'} at "
        f"{where}{equip}{window}.{tail}"
    )


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


# Verdict precedence for the project-level roll-up. Higher = "worse"
# / more blocking, so the project verdict is the max precedence
# observed across every per-pack calibration item.
_VERDICT_PRECEDENCE: dict[str, int] = {
    "auto_accept": 0,
    "needs_review": 1,
    "reject": 2,
}


def _rollup_calibrator_verdict(case_dir: Path) -> str | None:
    """Roll up per-pack calibration reports into a single project verdict.

    The orchestrator pipeline writes ``CalibratorReport`` JSON to
    ``<case_dir>/60_calibrations/<pack_id>.json``. Each item has a
    ``verdict`` field whose value is one of the
    :class:`Verdict` enum strings. The most-blocking verdict across
    every item in every pack wins. Returns ``None`` when no
    calibration artifacts exist on disk.
    """
    cal_dir = case_dir / "60_calibrations"
    if not cal_dir.is_dir():
        return None
    worst_rank = -1
    worst_label: str | None = None
    for path in sorted(cal_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for item in payload.get("items") or []:
            verdict = item.get("verdict")
            if not isinstance(verdict, str):
                continue
            rank = _VERDICT_PRECEDENCE.get(verdict)
            if rank is None:
                continue
            if rank > worst_rank:
                worst_rank = rank
                worst_label = verdict
    return worst_label
