"""Tier 1-4 PM-perfection intelligence layer.

This module concentrates all the "deep PM workflow" extractions
that make the brief actually executable end-to-end:

  Tier 1 (deal economics + scope):
    - margin / profitability view
    - critical path + phase dependencies
    - lead-time risk
    - engagement model (T&M / Fixed Fee / Subscription)
    - license / subscription tracker
    - multi-currency + tax
    - subcontractor identification
    - SLA penalties + liquidated damages
    - re-parse drift alert thresholds

  Tier 2 (execution-time views):
    - resource conflicts (same owner / crew overlap)
    - change-order language detection
    - field-team-shaped output
    - customer-facing redacted view

  Tier 3 (quality polish):
    - reconciliation semantics (label money atoms with role)
    - numeric risk scores (L × I)
    - critical-path Gantt highlight
    - action checklist due-date grouping
    - acceptance grouped by site
    - SOW boilerplate sensible defaults
    - CFO view with real margin %

  Tier 4 (strategic / historical):
    - vendor performance stub
    - estimating bench stub
    - sales handoff completeness gaps
    - negotiation history stub
    - audit trail manifest

Every output here is built deterministically from the parser-os
atoms + the PM handoff data. No LLM in the loop. Lower-fidelity
heuristics (regex over raw text for things like "T&M cap") are
labelled in their dataclass docstrings.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable


def _iter_atoms_with_files(report: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
    out: list[tuple[dict[str, Any], str]] = []
    for art in report.get("artifacts") or []:
        filename = str(art.get("filename") or art.get("artifact_id") or "unknown")
        for atom in art.get("atoms") or []:
            out.append((atom, filename))
    return out


def _money_int(value: Any) -> int:
    """Best-effort integer dollars from a string / number."""
    if value is None:
        return 0
    try:
        return int(float(str(value).replace(",", "").replace("$", "").strip()))
    except (TypeError, ValueError):
        return 0


def _display_money(value: int, currency: str = "USD") -> str:
    if currency in {"USD", "$", "", None}:
        return f"${value:,}"
    if currency in {"EUR", "€"}:
        return f"€{value:,}"
    if currency in {"GBP", "£"}:
        return f"£{value:,}"
    return f"{value:,} {currency}"


# ────────────────────────────── Tier 1A: margin / profitability ──────────────────────────────


@dataclass(frozen=True)
class MarginView:
    """Computed margin / profitability snapshot from intake.

    Uses three signals when available:
      * deal_total — largest single money value ≥ $100k (proxy for SOW total)
      * cost_subtotal — sum of (qty × unit_price) across vendor_line_item atoms
      * services_subtotal — explicit "Services subtotal" text match when present

    Margin is computed as (deal_total - cost_subtotal) / deal_total when
    both are present. ``confidence`` is "high" when atoms supplied
    both signals, "medium" when only one, "low" when computed from a
    heuristic. PM should treat low/medium as indicative, not contractual.
    """

    deal_total: int = 0
    hardware_cost_subtotal: int = 0  # sum of qty × unit_price from BOM
    services_subtotal: int = 0       # text-matched
    other_cost_subtotal: int = 0
    total_cost: int = 0
    gross_profit: int = 0
    margin_pct: float = 0.0
    confidence: str = "low"
    notes: list[str] = field(default_factory=list)


_SERVICES_SUBTOTAL_RE = re.compile(
    r"services?\s+subtotal(?:\s+target)?[:\s]+\$?([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)
_HARDWARE_SUBTOTAL_RE = re.compile(
    r"hardware\s+subtotal(?:\s+target)?[:\s]+\$?([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)
_LOGISTICS_SUBTOTAL_RE = re.compile(
    r"(?:logistics|freight|contingency|taxes?\s+and\s+fees)[^$]*?\$([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)


def build_margin_view(report: dict[str, Any]) -> MarginView:
    """Compute a margin view from BOM line items + text-matched subtotals.

    Authority order:
      1. When the source explicitly says ``Hardware subtotal: $X``,
         ``Services subtotal: $Y``, ``Logistics/contingency: $Z``,
         use those values as authoritative (they are the customer's
         own breakdown — no risk of double-counting).
      2. Only when those text matches are missing do we fall back to
         summing ``qty × unit_price`` from the BOM atoms.

    The previous version added the BOM sum AND the text-matched
    services_subtotal, double-counting labor lines on OPTBOT
    ($1,556,712 BOM-sum + $536,030 text-svc = $2,092,742 vs the
    customer's actual $1,847,250 total — produced a fake -0.3%
    margin). With the new precedence the answer matches the source.
    """
    notes: list[str] = []
    # ── deal total: largest money entity_key ≥ $100k ──
    money_values: set[int] = set()
    for atom, _ in _iter_atoms_with_files(report):
        for k in atom.get("entity_keys") or ():
            if isinstance(k, str) and k.startswith("money:"):
                try:
                    money_values.add(int(k.split(":", 1)[1]))
                except ValueError:
                    pass
    deal_total = max((v for v in money_values if v >= 100_000), default=0)

    # ── text-matched subtotals (hardware / services / logistics) ──
    text_hw = 0
    text_svc = 0
    text_other = 0
    for atom, _ in _iter_atoms_with_files(report):
        text = atom.get("text") or ""
        m = _HARDWARE_SUBTOTAL_RE.search(text)
        if m:
            text_hw = max(text_hw, _money_int(m.group(1)))
        m = _SERVICES_SUBTOTAL_RE.search(text)
        if m:
            text_svc = max(text_svc, _money_int(m.group(1)))
        m = _LOGISTICS_SUBTOTAL_RE.search(text)
        if m:
            text_other = max(text_other, _money_int(m.group(1)))

    # ── BOM qty × unit_price sum — used only when text matches absent ──
    bom_sum = 0
    for atom, _ in _iter_atoms_with_files(report):
        if atom.get("atom_type") != "vendor_line_item":
            continue
        s = atom.get("structured") or {}
        if not isinstance(s, dict):
            continue
        try:
            qty = int(float(s.get("quantity") or 0))
            unit = int(float(str(s.get("unit_price_raw") or 0).replace(",", "")))
        except (TypeError, ValueError):
            continue
        if qty > 0 and unit > 0:
            bom_sum += qty * unit

    # Authority precedence (no double-counting):
    if text_hw and text_svc:
        hardware_subtotal = text_hw
        services_subtotal = text_svc
        other_subtotal = text_other
        confidence = "high"
    elif text_hw or text_svc:
        # Partial text match — combine what we have with BOM remainder.
        # Conservative: take text values where present, fall back to BOM
        # for what's missing. Only count BOM ONCE (not double).
        hardware_subtotal = text_hw or bom_sum
        services_subtotal = text_svc
        other_subtotal = text_other
        confidence = "medium"
    else:
        # No text subtotals — use BOM sum as a single "total cost" line.
        hardware_subtotal = bom_sum
        services_subtotal = 0
        other_subtotal = text_other
        confidence = "low"

    total_cost = hardware_subtotal + services_subtotal + other_subtotal
    gross = deal_total - total_cost if deal_total and total_cost else 0
    margin_pct = (gross / deal_total * 100.0) if deal_total else 0.0

    if hardware_subtotal == 0:
        notes.append("Hardware subtotal could not be computed — no vendor_line_item atoms with quantity × unit_price and no text-matched subtotal.")
    if deal_total and total_cost and gross < 0:
        notes.append(
            f"⚠ Costs exceed deal total ({_display_money(total_cost)} > "
            f"{_display_money(deal_total)}). PM must reconcile — the SOW "
            f"will lose money as currently scoped."
        )
    if margin_pct and 0 < margin_pct < 15:
        notes.append(
            f"⚠ Margin {margin_pct:.1f}% is below typical 15% MSP floor — "
            f"flag for finance review."
        )
    elif margin_pct == 0 and total_cost and deal_total:
        notes.append(
            f"⚠ Zero-margin SOW: deal total exactly matches computed cost. "
            f"PM should add margin or confirm this is intentional "
            f"(pass-through pricing)."
        )

    return MarginView(
        deal_total=deal_total,
        hardware_cost_subtotal=hardware_subtotal,
        services_subtotal=services_subtotal,
        other_cost_subtotal=other_subtotal,
        total_cost=total_cost,
        gross_profit=gross,
        margin_pct=round(margin_pct, 1),
        confidence=confidence,
        notes=notes,
    )


# ────────────────────────────── Tier 1B + 3S: critical path + Gantt highlight ──────────────────────────────


@dataclass(frozen=True)
class CriticalPathPhase:
    """One phase on the critical path with computed slack."""
    phase: str
    start: str
    end: str
    duration_days: int
    is_critical: bool  # zero slack from this phase to project end


def build_critical_path(handoff_phases: list[dict[str, Any]]) -> list[CriticalPathPhase]:
    """Compute critical-path phases from the schedule.

    Approximation: phases are assumed to be sequential (each starts
    after the previous ends) when their date ranges don't overlap.
    The "critical" phases are those whose start equals or follows the
    end of the previous longest-chain end. Without explicit dependency
    metadata in parser-os atoms, sequential ordering is the best
    heuristic; PM can correct on review.
    """
    if not handoff_phases:
        return []
    parsed: list[tuple[str, date, date, int]] = []
    for p in handoff_phases:
        try:
            s = datetime.strptime(p.get("start", ""), "%Y-%m-%d").date()
            e = datetime.strptime(p.get("end", ""), "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        parsed.append((p.get("phase", ""), s, e, (e - s).days))
    if not parsed:
        return []
    # Sort by start date
    parsed.sort(key=lambda x: x[1])
    # Identify critical phases: chains where each phase starts on or
    # before the previous phase's end + 1 day buffer. Phases with
    # >7-day gap from the previous critical phase get marked
    # non-critical (they have slack).
    out: list[CriticalPathPhase] = []
    prev_end: date | None = None
    for name, s, e, dur in parsed:
        is_critical = True
        if prev_end is not None:
            gap = (s - prev_end).days
            if gap > 7:
                is_critical = False
        out.append(CriticalPathPhase(
            phase=name,
            start=s.isoformat(),
            end=e.isoformat(),
            duration_days=dur,
            is_critical=is_critical,
        ))
        prev_end = max(prev_end or e, e)
    return out


# ────────────────────────────── Tier 1C: lead-time risk view ──────────────────────────────


@dataclass(frozen=True)
class LeadTimeFlag:
    """One BOM line item that may gate the project schedule by its lead time."""
    part_number: str
    description: str
    quantity: int
    lead_time_text: str
    lead_time_days: int  # parsed numeric or 0
    risk_tier: str  # "extreme" / "long" / "medium" / "unknown"
    source: str = ""


_LEAD_TIME_RE = re.compile(
    r"(\d{1,3})\s*(?:business\s+)?(?:day|day\(s\)|weeks?|wks?|months?|mos?)",
    re.IGNORECASE,
)


def _parse_lead_time_days(text: str) -> int:
    if not text:
        return 0
    m = _LEAD_TIME_RE.search(text)
    if not m:
        return 0
    n = int(m.group(1))
    unit = (m.group(0).lower())
    if "week" in unit or "wk" in unit:
        return n * 7
    if "month" in unit or "mo" in unit:
        return n * 30
    return n


def build_lead_time_flags(report: dict[str, Any]) -> list[LeadTimeFlag]:
    """Flag BOM lines with long lead times that may gate the schedule."""
    out: list[LeadTimeFlag] = []
    for atom, filename in _iter_atoms_with_files(report):
        if atom.get("atom_type") != "vendor_line_item":
            continue
        s = atom.get("structured") or {}
        if not isinstance(s, dict):
            continue
        lead_text = str(s.get("lead_time") or "").strip()
        if not lead_text:
            continue
        days = _parse_lead_time_days(lead_text)
        if days <= 0:
            tier = "unknown"
        elif days >= 60:
            tier = "extreme"
        elif days >= 30:
            tier = "long"
        elif days >= 14:
            tier = "medium"
        else:
            continue  # short lead times aren't schedule risk
        try:
            qty = int(float(s.get("quantity") or 0))
        except (ValueError, TypeError):
            qty = 0
        out.append(LeadTimeFlag(
            part_number=str(s.get("part_number") or ""),
            description=str(s.get("description") or "")[:200],
            quantity=qty,
            lead_time_text=lead_text,
            lead_time_days=days,
            risk_tier=tier,
            source=filename,
        ))
    out.sort(key=lambda x: (-x.lead_time_days, x.part_number))
    return out


# ────────────────────────────── Tier 1D: engagement model summary ──────────────────────────────


@dataclass(frozen=True)
class EngagementModel:
    """Detected engagement model + recurring vs one-time breakout."""
    detected_model: str  # "fixed_fee" / "tm" / "subscription" / "mixed" / "unknown"
    evidence: list[str] = field(default_factory=list)
    one_time_amount: int = 0
    recurring_monthly: int = 0
    recurring_annual: int = 0
    has_tm_cap: bool = False
    tm_cap_amount: int = 0


_TM_RE = re.compile(r"\b(time\s+and\s+materials|t\s*&\s*m|hourly\s+rate|hours\s+based|nte\b|not[\s\-]to[\s\-]exceed)\b", re.IGNORECASE)
_FF_RE = re.compile(r"\b(fixed\s+fee|fixed\s+price|firm\s+fixed\s+price|ffp|lump\s+sum|milestone\s+billing)\b", re.IGNORECASE)
_SUB_RE = re.compile(r"\b(subscription|monthly\s+recurring|annual\s+recurring|mrr|arr|recurring\s+revenue|per[\s\-]month|/month|per\s+year|annually\s+invoiced|subscription\s+fee)\b", re.IGNORECASE)
_TM_CAP_RE = re.compile(r"(?:nte|cap|not[\s\-]to[\s\-]exceed)\s*(?:of\s+)?\$?([\d,]+(?:\.\d+)?)", re.IGNORECASE)


def build_engagement_model(report: dict[str, Any]) -> EngagementModel:
    has_tm = False
    has_ff = False
    has_sub = False
    evidence: list[str] = []
    tm_cap = 0
    for atom, filename in _iter_atoms_with_files(report):
        text = atom.get("text") or ""
        if _TM_RE.search(text):
            has_tm = True
            evidence.append(f"T&M evidence in `{filename}`: \"{text[:120]}\"")
        if _FF_RE.search(text):
            has_ff = True
            evidence.append(f"Fixed-fee evidence in `{filename}`: \"{text[:120]}\"")
        if _SUB_RE.search(text):
            has_sub = True
            evidence.append(f"Subscription evidence in `{filename}`: \"{text[:120]}\"")
        m = _TM_CAP_RE.search(text)
        if m:
            tm_cap = max(tm_cap, _money_int(m.group(1)))
    flags = [has_tm, has_ff, has_sub]
    if sum(flags) >= 2:
        model = "mixed"
    elif has_tm:
        model = "tm"
    elif has_ff:
        model = "fixed_fee"
    elif has_sub:
        model = "subscription"
    else:
        model = "unknown"
    return EngagementModel(
        detected_model=model,
        evidence=evidence[:10],
        has_tm_cap=bool(tm_cap),
        tm_cap_amount=tm_cap,
    )


# ────────────────────────────── Tier 1E: license / subscription tracker ──────────────────────────────


@dataclass(frozen=True)
class LicenseItem:
    """One recurring-software / license / subscription entry."""
    part_number: str
    description: str
    quantity: int
    unit_price: int
    term_text: str  # raw "annual", "3 year", "perpetual" etc.
    renewal_hint: str  # date or relative text when detectable
    source: str = ""


_LICENSE_TOKENS = (
    "license", "licence", "subscription", "smartnet", "dna advantage",
    "dna essentials", "support tier", "warranty extension", "annual support",
    "saas", "iaas", "paas", "tenant", "seat license", "user license",
    "maintenance", "renewal", "yearly", "annual fee",
)
_TERM_RE = re.compile(
    r"\b(\d{1,2})\s*(?:year|yr|month|mo)s?\b",
    re.IGNORECASE,
)


def build_license_items(report: dict[str, Any]) -> list[LicenseItem]:
    out: list[LicenseItem] = []
    seen: set[tuple[str, str]] = set()
    for atom, filename in _iter_atoms_with_files(report):
        text = (atom.get("text") or "").lower()
        if not any(tok in text for tok in _LICENSE_TOKENS):
            continue
        s = atom.get("structured") or {}
        if not isinstance(s, dict):
            s = {}
        pn = str(s.get("part_number") or "")
        desc = str(s.get("description") or atom.get("text") or "")[:200]
        try:
            qty = int(float(s.get("quantity") or 0))
        except (ValueError, TypeError):
            qty = 0
        try:
            unit = int(float(str(s.get("unit_price_raw") or 0).replace(",", "")))
        except (TypeError, ValueError):
            unit = 0
        term_m = _TERM_RE.search(text)
        term = term_m.group(0) if term_m else ""
        key = (pn, desc[:80])
        if key in seen:
            continue
        seen.add(key)
        out.append(LicenseItem(
            part_number=pn,
            description=desc,
            quantity=qty,
            unit_price=unit,
            term_text=term,
            renewal_hint="",
            source=filename,
        ))
    return out


# ────────────────────────────── Tier 1F: multi-currency + tax ──────────────────────────────


@dataclass(frozen=True)
class CurrencyMention:
    """One non-USD currency mention with the surrounding amount."""
    currency: str  # ISO or symbol form
    amount: int
    source: str
    snippet: str


@dataclass(frozen=True)
class TaxClause:
    """One tax / VAT / GST mention."""
    rate_pct: float
    label: str  # "VAT", "GST", "sales tax", "tax-exclusive", ...
    source: str
    snippet: str


_CURRENCY_RE = re.compile(
    r"(?:(USD|EUR|GBP|CAD|AUD|JPY|CHF|SEK|NOK|DKK|CNY|RMB|INR|MXN|BRL)|([€£¥₹]))"
    r"\s*([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)
_TAX_RE = re.compile(
    r"\b(vat|gst|sales\s+tax|use\s+tax|withholding\s+tax|"
    r"value[\s\-]added\s+tax|good\s+and\s+services\s+tax)\s*"
    r"(?:of|at|@|:|=)?\s*"
    r"(\d{1,2}(?:\.\d{1,2})?)\s*%",
    re.IGNORECASE,
)
_TAX_INCLUSIVE_RE = re.compile(
    r"\b(?:tax[\s\-]inclusive|inclusive\s+of\s+tax|tax\s+included|"
    r"tax[\s\-]exclusive|exclusive\s+of\s+tax|tax\s+not\s+included|"
    r"plus\s+applicable\s+tax)\b",
    re.IGNORECASE,
)


_SYMBOL_TO_ISO = {"€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR"}


def build_currency_mentions(report: dict[str, Any]) -> list[CurrencyMention]:
    out: list[CurrencyMention] = []
    seen: set[tuple[str, int]] = set()
    for atom, filename in _iter_atoms_with_files(report):
        text = atom.get("text") or ""
        for m in _CURRENCY_RE.finditer(text):
            curr = (m.group(1) or _SYMBOL_TO_ISO.get(m.group(2) or "", "") or "").upper()
            if not curr or curr == "USD":
                continue
            amount = _money_int(m.group(3))
            if amount == 0:
                continue
            key = (curr, amount)
            if key in seen:
                continue
            seen.add(key)
            out.append(CurrencyMention(
                currency=curr,
                amount=amount,
                source=filename,
                snippet=text[max(0, m.start() - 30): m.end() + 60][:200],
            ))
    return out


def build_tax_clauses(report: dict[str, Any]) -> list[TaxClause]:
    out: list[TaxClause] = []
    seen: set[tuple[str, float, str]] = set()
    for atom, filename in _iter_atoms_with_files(report):
        text = atom.get("text") or ""
        for m in _TAX_RE.finditer(text):
            label = m.group(1).strip()
            try:
                rate = float(m.group(2))
            except ValueError:
                continue
            key = (label.lower(), rate, filename)
            if key in seen:
                continue
            seen.add(key)
            out.append(TaxClause(
                rate_pct=rate,
                label=label,
                source=filename,
                snippet=text[max(0, m.start() - 30): m.end() + 60][:200],
            ))
        for m in _TAX_INCLUSIVE_RE.finditer(text):
            label = m.group(0)
            key = (label.lower(), 0.0, filename)
            if key in seen:
                continue
            seen.add(key)
            out.append(TaxClause(
                rate_pct=0.0,
                label=label,
                source=filename,
                snippet=text[max(0, m.start() - 30): m.end() + 60][:200],
            ))
    return out


# ────────────────────────────── Tier 1G: subcontractor identification ──────────────────────────────


@dataclass(frozen=True)
class SubcontractorMention:
    """A subcontractor / distributor / vendor named in the intake."""
    name: str
    role_hint: str  # "Distributor" / "Installer" / "Vendor" / ""
    source: str
    snippet: str


_KNOWN_SUBS_DISTRIBUTORS = {
    # ── distributors ──
    "graybar": "Distributor",
    "wesco": "Distributor",
    "anixter": "Distributor",
    "scansource": "Distributor",
    "td synnex": "Distributor",
    "synnex": "Distributor",
    "tech data": "Distributor",
    "ingram micro": "Distributor",
    "arrow electronics": "Distributor",
    "avnet": "Distributor",
    "exclusive networks": "Distributor",
    "westcon": "Distributor",
    "comstor": "Distributor",
    "rexel": "Distributor",
    "consolidated electrical distributors": "Distributor",
    "advanced electronics": "Distributor",
    "powell electronics": "Distributor",
    # ── VARs / Resellers ──
    "eplus": "VAR / Reseller",
    "cdw": "VAR / Reseller",
    "shi": "VAR / Reseller",
    "softchoice": "VAR / Reseller",
    "computacenter": "VAR / Reseller",
    "softcat": "VAR / Reseller",
    "insight": "VAR / Reseller",
    "connection": "VAR / Reseller",
    "zones": "VAR / Reseller",
    "groupware technology": "VAR / Reseller",
    # ── National MSPs / Integrators ──
    "presidio": "Installer / Integrator",
    "convergeone": "Installer / Integrator",
    "world wide technology": "Installer / Integrator",
    "wwt": "Installer / Integrator",
    "logicalis": "Installer / Integrator",
    "diversified": "Installer / Integrator",
    "av-iq": "AV integrator",
    "ais": "Installer / Integrator",
    "kyndryl": "MSP / Integrator",
    "ntt data": "MSP / Integrator",
    "accenture": "MSP / Integrator",
    "deloitte": "MSP / Integrator",
    "dxc technology": "MSP / Integrator",
    "ibm services": "MSP / Integrator",
    "hcl": "MSP / Integrator",
    "tcs": "MSP / Integrator",
    "infosys": "MSP / Integrator",
    "wipro": "MSP / Integrator",
    "capgemini": "MSP / Integrator",
    "atos": "MSP / Integrator",
    "fujitsu": "MSP / Integrator",
    "unisys": "MSP / Integrator",
    "leidos": "MSP / Integrator",
    "general dynamics it": "MSP / Integrator",
    "sirius computer solutions": "MSP / Integrator",
    "ahead": "MSP / Integrator",
    "trace3": "MSP / Integrator",
    "optiv": "Security Integrator",
    "guidepoint": "Security Integrator",
    "gotham technology group": "MSP / Integrator",
    # ── Cabling / Low-voltage subs ──
    "windstream": "Carrier / ISP",
    "lumen": "Carrier / ISP",
    "att": "Carrier / ISP",
    "at&t": "Carrier / ISP",
    "verizon": "Carrier / ISP",
    "comcast business": "Carrier / ISP",
    "spectrum business": "Carrier / ISP",
    "cox business": "Carrier / ISP",
    "frontier": "Carrier / ISP",
    "level 3": "Carrier / ISP",
    "zayo": "Carrier / ISP",
    # ── Major Networking OEMs ──
    "cisco": "OEM (Networking)",
    "meraki": "OEM (Networking)",
    "juniper": "OEM (Networking)",
    "arista": "OEM (Networking)",
    "fortinet": "OEM (Security)",
    "palo alto": "OEM (Security)",
    "check point": "OEM (Security)",
    "sonicwall": "OEM (Security)",
    "watchguard": "OEM (Security)",
    "barracuda": "OEM (Security)",
    "f5": "OEM (Networking)",
    "aruba": "OEM (Networking)",
    "ruckus": "OEM (Networking)",
    "extreme networks": "OEM (Networking)",
    "ubiquiti": "OEM (Networking)",
    "mist": "OEM (Networking)",
    "cradlepoint": "OEM (Networking)",
    "peplink": "OEM (Networking)",
    # ── AV / Collaboration OEMs ──
    "crestron": "OEM (AV)",
    "biamp": "OEM (AV)",
    "qsc": "OEM (AV)",
    "extron": "OEM (AV)",
    "shure": "OEM (AV)",
    "sennheiser": "OEM (AV)",
    "logitech": "OEM (AV)",
    "poly": "OEM (AV)",
    "polycom": "OEM (AV)",
    "yealink": "OEM (AV)",
    "neat": "OEM (AV)",
    "huddly": "OEM (AV)",
    "barco": "OEM (AV)",
    "samsung": "OEM (Display)",
    "lg": "OEM (Display)",
    "nec display": "OEM (Display)",
    "sharp": "OEM (Display)",
    "planar": "OEM (Display)",
    "atlona": "OEM (AV)",
    "kramer": "OEM (AV)",
    "lightware": "OEM (AV)",
    # ── Security / Surveillance ──
    "genetec": "OEM (VMS)",
    "milestone": "OEM (VMS)",
    "avigilon": "OEM (VMS)",
    "axis": "OEM (Camera)",
    "hanwha": "OEM (Camera)",
    "bosch": "OEM (Camera)",
    "hikvision": "OEM (Camera)",
    "dahua": "OEM (Camera)",
    "verkada": "OEM (Camera)",
    "rhombus": "OEM (Camera)",
    "exacqvision": "OEM (VMS)",
    "lenel": "OEM (Access Control)",
    "honeywell": "OEM (Access Control)",
    "software house": "OEM (Access Control)",
    "ccure": "OEM (Access Control)",
    "kantech": "OEM (Access Control)",
    "openpath": "OEM (Access Control)",
    "brivo": "OEM (Access Control)",
    "kisi": "OEM (Access Control)",
    # ── Power / Environment ──
    "apc": "OEM (Power)",
    "eaton": "OEM (Power)",
    "vertiv": "OEM (Power)",
    "schneider electric": "OEM (Power)",
    "tripp lite": "OEM (Power)",
    "generac": "OEM (Generator)",
    "cummins": "OEM (Generator)",
    "kohler": "OEM (Generator)",
    "caterpillar": "OEM (Generator)",
    "siemens": "OEM (BMS)",
    "trane": "OEM (HVAC)",
    "carrier": "OEM (HVAC)",
    "york": "OEM (HVAC)",
    "daikin": "OEM (HVAC)",
    "mitsubishi": "OEM (HVAC)",
    "stulz": "OEM (Cooling)",
    "liebert": "OEM (Cooling)",
    # ── Servers / Storage / Endpoints ──
    "dell": "OEM (Server/Endpoint)",
    "hpe": "OEM (Server)",
    "hp inc": "OEM (Endpoint)",
    "lenovo": "OEM (Endpoint)",
    "supermicro": "OEM (Server)",
    "ibm": "OEM (Server)",
    "oracle": "OEM (Server)",
    "netapp": "OEM (Storage)",
    "pure storage": "OEM (Storage)",
    "nutanix": "OEM (HCI)",
    "vmware": "OEM (Virtualization)",
    "vmware aria": "OEM (Cloud)",
    "veeam": "OEM (Backup)",
    "rubrik": "OEM (Backup)",
    "cohesity": "OEM (Backup)",
    "commvault": "OEM (Backup)",
    "zerto": "OEM (Backup)",
    "datto": "OEM (Backup)",
    # ── Identity / Endpoint / Tools ──
    "microsoft": "OEM (Software / Cloud)",
    "office 365": "OEM (Software)",
    "intune": "OEM (Endpoint mgmt)",
    "okta": "OEM (IAM)",
    "entra": "OEM (IAM)",
    "duo": "OEM (MFA)",
    "azure": "OEM (Cloud)",
    "aws": "OEM (Cloud)",
    "gcp": "OEM (Cloud)",
    "amazon web services": "OEM (Cloud)",
    "google cloud": "OEM (Cloud)",
    "salesforce": "OEM (SaaS)",
    "servicenow": "OEM (SaaS)",
    "atlassian": "OEM (SaaS)",
    "splunk": "OEM (SIEM)",
    "datadog": "OEM (Observability)",
    "new relic": "OEM (Observability)",
    "crowdstrike": "OEM (EDR)",
    "sentinelone": "OEM (EDR)",
    "carbon black": "OEM (EDR)",
    "tenable": "OEM (Vuln mgmt)",
    "qualys": "OEM (Vuln mgmt)",
    "rapid7": "OEM (SIEM)",
    "wiz": "OEM (CNAPP)",
    "lacework": "OEM (CNAPP)",
}


def build_subcontractor_mentions(report: dict[str, Any]) -> list[SubcontractorMention]:
    out: list[SubcontractorMention] = []
    seen: set[tuple[str, str]] = set()
    # Word-boundary compiled patterns to avoid "shi" matching inside
    # "shipment" / "ship" / "shift" — needs explicit \b on both sides.
    compiled = [
        (name, role, re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE))
        for name, role in _KNOWN_SUBS_DISTRIBUTORS.items()
    ]
    for atom, filename in _iter_atoms_with_files(report):
        text = atom.get("text") or ""
        if not text:
            continue
        for name, role, pat in compiled:
            m = pat.search(text)
            if not m:
                continue
            key = (name, filename)
            if key in seen:
                continue
            seen.add(key)
            out.append(SubcontractorMention(
                name=name.title(),
                role_hint=role,
                source=filename,
                snippet=text[max(0, m.start() - 30): m.end() + 80][:200],
            ))
    return out


# ────────────────────────────── Tier 1H: SLA penalties + liquidated damages ──────────────────────────────


@dataclass(frozen=True)
class SlaPenalty:
    """A liquidated-damages / SLA-penalty clause."""
    kind: str  # "liquidated_damages" / "sla_credit" / "termination_right" / "generic"
    snippet: str
    source: str


_SLA_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("liquidated_damages", re.compile(r"\bliquidated\s+damages\b", re.IGNORECASE)),
    ("sla_credit", re.compile(r"\b(?:service\s+credit|sla\s+credit|service\s+level\s+credit)\b", re.IGNORECASE)),
    ("termination_right", re.compile(r"\bright\s+to\s+terminate|termination\s+for\s+(?:cause|convenience)\b", re.IGNORECASE)),
    ("uptime_sla", re.compile(r"\b(99\.\d+|9{1,3}\.?\d*)\s*%\s*(?:uptime|availability|sla)\b", re.IGNORECASE)),
    ("response_sla", re.compile(r"\b(?:response\s+time|time\s+to\s+respond|mttr|mttd)\s+(?:of|:)?\s*\d+\s*(?:minute|hour|day)s?\b", re.IGNORECASE)),
    ("late_delivery", re.compile(r"\b(?:late\s+delivery|delay\s+penalty|per\s+day\s+(?:of\s+delay|late))\b", re.IGNORECASE)),
)


def build_sla_penalties(report: dict[str, Any]) -> list[SlaPenalty]:
    out: list[SlaPenalty] = []
    seen: set[tuple[str, str]] = set()
    for atom, filename in _iter_atoms_with_files(report):
        text = atom.get("text") or ""
        for kind, pat in _SLA_PATTERNS:
            m = pat.search(text)
            if not m:
                continue
            snippet = text[max(0, m.start() - 40): m.end() + 80][:200].strip()
            key = (kind, snippet[:100])
            if key in seen:
                continue
            seen.add(key)
            out.append(SlaPenalty(kind=kind, snippet=snippet, source=filename))
    return out


# ────────────────────────────── Tier 1I: re-parse drift alert ──────────────────────────────


@dataclass(frozen=True)
class DriftAlert:
    """One alert raised when re-parsing the same project changed
    a PM-critical signal (deal value, site count, blocker count,
    risk count) more than a threshold."""
    field: str
    before: Any
    after: Any
    delta: str
    severity: str  # "info" / "warn" / "crit"


def build_drift_alerts(
    *,
    before_summary: dict[str, Any],
    after_summary: dict[str, Any],
) -> list[DriftAlert]:
    """Compare two compile summaries; return PM-actionable drift."""
    alerts: list[DriftAlert] = []

    def _check(field: str, severity: str, *, pct_threshold: float = 0.10) -> None:
        b = before_summary.get(field, 0)
        a = after_summary.get(field, 0)
        try:
            bn = float(b)
            an = float(a)
        except (TypeError, ValueError):
            return
        if bn == 0 and an == 0:
            return
        denom = max(abs(bn), abs(an))
        delta = (an - bn) / denom if denom else 0
        if abs(delta) >= pct_threshold:
            alerts.append(DriftAlert(
                field=field,
                before=b,
                after=a,
                delta=f"{delta * 100:+.1f}%",
                severity=severity,
            ))

    _check("deal_total", "crit", pct_threshold=0.05)
    _check("blocker_count", "warn", pct_threshold=0.20)
    _check("site_count", "warn", pct_threshold=0.10)
    _check("risk_count", "info", pct_threshold=0.25)
    return alerts


# ────────────────────────────── Tier 2M: resource conflicts ──────────────────────────────


@dataclass(frozen=True)
class ResourceConflict:
    """One owner with overlapping phase commitments."""
    owner: str
    phases: list[str]  # phase names
    overlap_windows: list[tuple[str, str]]  # (start, end) ISO


def build_resource_conflicts(handoff_phases: list[dict[str, Any]]) -> list[ResourceConflict]:
    """Detect owners assigned to overlapping schedule phases."""
    by_owner: dict[str, list[tuple[str, date, date]]] = defaultdict(list)
    for p in handoff_phases:
        owner = (p.get("owner") or "").strip()
        if not owner:
            continue
        try:
            s = datetime.strptime(p.get("start", ""), "%Y-%m-%d").date()
            e = datetime.strptime(p.get("end", ""), "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        by_owner[owner].append((p.get("phase", ""), s, e))
    out: list[ResourceConflict] = []
    for owner, items in by_owner.items():
        if len(items) < 2:
            continue
        items.sort(key=lambda x: x[1])
        overlaps: list[tuple[str, str]] = []
        conflicting_phases: list[str] = []
        for i in range(len(items) - 1):
            _, s1, e1 = items[i]
            _, s2, e2 = items[i + 1]
            if s2 <= e1:
                overlaps.append((s2.isoformat(), min(e1, e2).isoformat()))
                conflicting_phases.extend([items[i][0], items[i + 1][0]])
        if overlaps:
            out.append(ResourceConflict(
                owner=owner,
                phases=sorted(set(conflicting_phases)),
                overlap_windows=overlaps,
            ))
    return out


# ────────────────────────────── Tier 2L: change-order detection ──────────────────────────────


@dataclass(frozen=True)
class ChangeOrderTrigger:
    """A scope/cost change clause that will trigger a CO."""
    snippet: str
    source: str
    kind: str  # "scope_change" / "cost_change" / "schedule_change"


_CO_TRIGGER_RE = re.compile(
    r"\b(?:change\s+order|change[\s\-]request|"
    r"variation\s+request|scope\s+change|"
    r"requires?\s+written\s+approval|"
    r"substitut(?:e|ion|ions)\s+require"
    r")\b",
    re.IGNORECASE,
)
_RE_PRICING_RE = re.compile(
    r"\b(?:re-?price|re-?quote|pricing\s+(?:adjustment|revision)|"
    r"new\s+(?:quote|estimate))\b",
    re.IGNORECASE,
)


def build_change_order_triggers(report: dict[str, Any]) -> list[ChangeOrderTrigger]:
    out: list[ChangeOrderTrigger] = []
    seen: set[tuple[str, str]] = set()
    for atom, filename in _iter_atoms_with_files(report):
        text = atom.get("text") or ""
        for pat, kind in (
            (_CO_TRIGGER_RE, "scope_change"),
            (_RE_PRICING_RE, "cost_change"),
        ):
            m = pat.search(text)
            if not m:
                continue
            snippet = text[max(0, m.start() - 40): m.end() + 80][:200].strip()
            key = (kind, snippet[:80])
            if key in seen:
                continue
            seen.add(key)
            out.append(ChangeOrderTrigger(
                snippet=snippet,
                source=filename,
                kind=kind,
            ))
    return out


# ────────────────────────────── Tier 2N: risk aging ──────────────────────────────


@dataclass(frozen=True)
class RiskAging:
    """Risk + age in days since first observed (proxied by intake date)."""
    risk_id: str
    description: str
    days_open: int
    severity: str
    aging_bucket: str  # "fresh" (<7d) / "active" (<30d) / "stale" (≥30d)


def build_risk_aging(
    risk_register: list[dict[str, Any]],
    *,
    today_iso: str | None = None,
    intake_date_iso: str | None = None,
) -> list[RiskAging]:
    """Risk aging without explicit risk-creation dates: proxy via
    the project's earliest schedule start (or today minus 0)."""
    if not risk_register:
        return []
    try:
        today = (
            datetime.strptime(today_iso, "%Y-%m-%d").date()
            if today_iso else date.today()
        )
    except ValueError:
        today = date.today()
    try:
        intake_dt = (
            datetime.strptime(intake_date_iso, "%Y-%m-%d").date()
            if intake_date_iso else today
        )
    except ValueError:
        intake_dt = today
    days_open = max(0, (today - intake_dt).days)
    out: list[RiskAging] = []
    for r in risk_register:
        rid = r.get("risk_id") or ""
        desc = r.get("description") or ""
        li = (r.get("likelihood") or "").lower()
        im = (r.get("impact") or "").lower()
        sev = (
            "high" if (li, im) in {("high", "high"), ("high", "medium"), ("medium", "high")}
            else ("medium" if (li, im) in {("medium", "medium"), ("low", "high"), ("high", "low")} else "low")
        )
        bucket = "fresh" if days_open < 7 else ("active" if days_open < 30 else "stale")
        out.append(RiskAging(
            risk_id=str(rid),
            description=str(desc),
            days_open=days_open,
            severity=sev,
            aging_bucket=bucket,
        ))
    return out


# ────────────────────────────── Tier 3Q: reconciliation semantics ──────────────────────────────


_MONEY_ROLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("approval_threshold", re.compile(r"approval\s+(?:required\s+)?(?:over|above|exceeds?|>)|threshold|approval\s+matrix", re.IGNORECASE)),
    ("deal_total", re.compile(r"\b(?:total|grand\s+total|contract\s+value|total\s+(?:deal|project)\s+value|project\s+total)\b", re.IGNORECASE)),
    ("subtotal", re.compile(r"subtotal", re.IGNORECASE)),
    ("contingency", re.compile(r"\bcontingenc(?:y|ies)\b", re.IGNORECASE)),
    ("discount", re.compile(r"\bdiscount\b", re.IGNORECASE)),
    ("payment_milestone", re.compile(r"\b(?:on\s+(?:order|equipment|site)\s+acceptance|at\s+(?:order|equipment|site)\s+acceptance|after\s+hypercare|payment\s+schedule)\b", re.IGNORECASE)),
    ("unit_price", re.compile(r"\bunit\s+price|x\s+\$|each", re.IGNORECASE)),
)


def label_money_role(value: int, snippet: str) -> str:
    """Classify a money value by surrounding text into a semantic role.

    Used by the cross-document reconciliation renderer to label
    pairs like ``$1.85M vs $1.5M`` with their actual semantic
    role ("contract total" vs "CFO threshold") so the PM doesn't
    treat them as a contradiction when they're different
    concepts."""
    if not snippet:
        return "unknown"
    for role, pat in _MONEY_ROLE_PATTERNS:
        if pat.search(snippet):
            return role
    return "unknown"


# ────────────────────────────── Tier 3R: numeric risk scores ──────────────────────────────


_RISK_NUMERIC_MAP = {"low": 1, "medium": 2, "med": 2, "high": 3}


def risk_numeric_score(likelihood: str, impact: str) -> tuple[int, int, int]:
    """Return ``(l_score, i_score, lxi_score)`` for a (likelihood, impact)
    pair.  Unknown levels score 0 so the column shows '—' downstream."""
    l = _RISK_NUMERIC_MAP.get((likelihood or "").strip().lower(), 0)
    i = _RISK_NUMERIC_MAP.get((impact or "").strip().lower(), 0)
    return l, i, l * i


# ────────────────────────────── Tier 3T: action checklist by due-date week ──────────────────────────────


def group_actions_by_week(
    actions: list[dict[str, Any]],
    *,
    today_iso: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Group an action_items list into ``this_week``, ``next_week``,
    ``later``, ``no_date`` buckets."""
    try:
        today = (
            datetime.strptime(today_iso, "%Y-%m-%d").date()
            if today_iso else date.today()
        )
    except ValueError:
        today = date.today()
    buckets: dict[str, list[dict[str, Any]]] = {
        "this_week": [], "next_week": [], "later": [], "no_date": [],
    }
    for a in actions:
        due = (a.get("due") or "").strip()
        if not due:
            buckets["no_date"].append(a)
            continue
        try:
            d = datetime.strptime(due, "%Y-%m-%d").date()
        except ValueError:
            buckets["no_date"].append(a)
            continue
        delta = (d - today).days
        if delta < 7:
            buckets["this_week"].append(a)
        elif delta < 14:
            buckets["next_week"].append(a)
        else:
            buckets["later"].append(a)
    return buckets


# ────────────────────────────── Tier 3U: acceptance grouped by site ──────────────────────────────


_SITE_HINT_RE = re.compile(r"\b(ATL[\-_][A-Z]{2,5}|[A-Z]{3,6}[\-_][A-Z]{2,5})\b")


def group_acceptance_by_site(
    checks: list[dict[str, Any]],
    *,
    site_keys: list[str],
) -> dict[str, list[dict[str, Any]]]:
    """Reshape acceptance_checks into ``{site_label: [check, ...]}``.

    A check belongs to a site when its criterion text mentions
    the site code or one of the alias keys. Unmatched checks go
    under ``"project_wide"`` so they aren't lost."""
    out: dict[str, list[dict[str, Any]]] = {"project_wide": []}
    site_upper = [s.upper().replace("_", "-") for s in site_keys]
    for c in checks:
        text = (c.get("criterion") or "").upper()
        matched: list[str] = []
        for s in site_upper:
            if s and s in text:
                matched.append(s)
        if not matched:
            out["project_wide"].append(c)
        else:
            for s in matched:
                out.setdefault(s, []).append(c)
    return out


# ────────────────────────────── Tier 3V: SOW boilerplate defaults ──────────────────────────────


SOW_DEFAULTS = {
    "payment_terms": (
        "Net 30 days from invoice receipt, milestone-billed per the schedule "
        "in Section 6. Past-due invoices accrue 1.5% per month interest."
    ),
    "pricing_model": (
        "Fixed-fee delivery against the milestones in Section 6. Time-and-"
        "materials work (if any) is capped per Section 8."
    ),
    "tm_terms": (
        "T&M work, when invoked, is billed at the published rate sheet "
        "(provided separately), in 15-minute increments, with a not-to-exceed "
        "cap. Pre-approval is required for any single task exceeding 8 hours."
    ),
    "warranty": (
        "Workmanship warranty: 90 days from acceptance. Hardware passes the "
        "manufacturer warranty through to the customer; no parallel warranty "
        "is offered by the provider."
    ),
    "liability_cap": (
        "Provider liability is capped at the total fees paid under this SOW "
        "in the 12 months preceding the claim. No liability for indirect or "
        "consequential damages."
    ),
    "change_management": (
        "Any change in scope, schedule, or commercial terms is documented in "
        "a Change Order signed by both parties before work proceeds. Verbal "
        "agreements are non-binding."
    ),
    "ip_rights": (
        "Pre-existing IP remains with its owner. Work-product IP delivered "
        "under this SOW is licensed to the customer for internal business "
        "use. No transfer of pre-existing tools or methodologies."
    ),
    "confidentiality": (
        "Both parties protect each other's confidential information per the "
        "NDA / MSA. Survives termination by 3 years."
    ),
    "termination": (
        "Either party may terminate for material breach with 30 days written "
        "notice and a cure period. Customer may terminate for convenience "
        "subject to payment for work performed plus a 10% restocking fee on "
        "ordered hardware."
    ),
    "force_majeure": (
        "Neither party is liable for delays caused by acts of God, natural "
        "disasters, government action, labor strikes, or supply-chain "
        "disruption beyond reasonable control."
    ),
}


# ────────────────────────────── Tier 4Z: sales handoff completeness ──────────────────────────────


IDEAL_INTAKE_CHECKLIST: tuple[tuple[str, str], ...] = (
    ("Confirmed contract value", "money_atom_ge_100k"),
    ("At least one confirmed physical site", "publishable_site"),
    ("Project schedule with start + end dates", "schedule_phase_with_dates"),
    ("Named executive sponsor (stakeholder)", "stakeholder_executive_role"),
    ("Hardware BOM or vendor quote", "vendor_line_item"),
    ("Risk register", "risk_atom"),
    ("Acceptance criteria definition", "exit_criteria"),
    ("Payment terms and pricing model", "payment_term_or_pricing"),
    ("Out-of-scope / exclusions list", "exclusion_atom"),
    ("Compliance / MSA / NDA reference", "compliance_callout"),
)


@dataclass(frozen=True)
class IntakeGap:
    """An item missing from the ideal-intake checklist."""
    item: str
    detector_key: str
    present: bool


def build_intake_completeness(
    *,
    has_deal_total: bool,
    has_publishable_site: bool,
    has_schedule_phase: bool,
    has_executive_stakeholder: bool,
    has_vendor_line: bool,
    has_risk: bool,
    has_exit_criteria: bool,
    has_payment_term: bool,
    has_exclusion: bool,
    has_compliance_callout: bool,
) -> list[IntakeGap]:
    presence_map = {
        "money_atom_ge_100k": has_deal_total,
        "publishable_site": has_publishable_site,
        "schedule_phase_with_dates": has_schedule_phase,
        "stakeholder_executive_role": has_executive_stakeholder,
        "vendor_line_item": has_vendor_line,
        "risk_atom": has_risk,
        "exit_criteria": has_exit_criteria,
        "payment_term_or_pricing": has_payment_term,
        "exclusion_atom": has_exclusion,
        "compliance_callout": has_compliance_callout,
    }
    return [
        IntakeGap(item=item, detector_key=key, present=presence_map.get(key, False))
        for item, key in IDEAL_INTAKE_CHECKLIST
    ]


# ────────────────────────────── Tier 4AB: audit trail manifest ──────────────────────────────


def build_audit_manifest(
    *,
    case_id: str,
    compile_id: str,
    generated_at: str,
    deliverables: dict[str, str],
) -> dict[str, Any]:
    """Compute hashes of every PM-output file so the audit trail
    can prove the brief that ran has not been mutated after the
    fact. ``deliverables`` is ``{filename: file_text}``.
    """
    import hashlib
    manifest_entries: list[dict[str, str]] = []
    for name, text in sorted(deliverables.items()):
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        manifest_entries.append({
            "filename": name,
            "sha256": h,
            "size_bytes": len(text.encode("utf-8")),
        })
    return {
        "case_id": case_id,
        "compile_id": compile_id,
        "generated_at": generated_at,
        "deliverables": manifest_entries,
    }


# ────────────────────────────── Multi-currency → USD-equivalent ──────────────────────────────


@dataclass(frozen=True)
class OcrBackendStatus:
    """Snapshot of which OCR backends were reachable during compile.

    Surfaced in PM_HANDOFF so the PM can see whether image / scanned
    pages would have been OCR'd. ``available`` is the list of
    backends that fired (or could have fired) on this run;
    ``install_hints`` is a list of explicit install suggestions
    when nothing was reachable.
    """
    available: list[str] = field(default_factory=list)
    install_hints: list[str] = field(default_factory=list)


def build_ocr_backend_status() -> OcrBackendStatus:
    """Best-effort probe — returns the list of OCR backends the
    parser would have used on this compile, with install hints when
    nothing was reachable."""
    available: list[str] = []
    hints: list[str] = []
    try:
        # parser-os ships the ocr_chain in app.parsers; we import
        # opportunistically here so OrbitBrief-Core works even when
        # parser-os isn't installed in the same environment.
        from app.parsers._ocr_chain import available_backends as _avail
        available = list(_avail())
    except Exception:
        pass
    if not available:
        hints.extend([
            "Install Tesseract on the host (Windows: github.com/UB-Mannheim/tesseract/wiki; Mac: `brew install tesseract`; Linux: `apt install tesseract-ocr`) and PyMuPDF will OCR scanned PDFs automatically.",
            "Or `pip install pytesseract easyocr pillow-heif` for additional fallbacks.",
            "Or `ollama pull llava` on the configured Ollama server to enable vision-LLM OCR (set PARSER_OS_OCR_OLLAMA_BASE_URL + PARSER_OS_OCR_OLLAMA_VISION_MODEL).",
        ])
    return OcrBackendStatus(available=available, install_hints=hints)


FX_TO_USD: dict[str, float] = {
    "USD": 1.00,
    "EUR": 1.08, "GBP": 1.27, "CAD": 0.74, "AUD": 0.66, "JPY": 0.0067,
    "CHF": 1.13, "SEK": 0.094, "NOK": 0.094, "DKK": 0.145,
    "CNY": 0.139, "RMB": 0.139, "INR": 0.0120, "MXN": 0.058, "BRL": 0.20,
    "SGD": 0.74, "HKD": 0.128, "AED": 0.272, "ZAR": 0.054,
}


_FX_LIVE_CACHE: dict[str, dict[str, float]] = {}


def _fetch_live_fx_rates() -> dict[str, float]:
    """Best-effort fetch of mid-market FX rates against USD.

    Uses Frankfurter (ECB-backed, no API key, generous rate limit).
    Cached for 4 hours per-process via ``_FX_LIVE_CACHE``. Failures
    silently fall back to the static ``FX_TO_USD`` snapshot — the
    UI still works without a network connection.

    Set ``ORBITBRIEF_FX_API_URL`` to a custom endpoint (Bloomberg /
    Reuters / OpenExchange wire-up) for SOX-grade accuracy. The
    response shape must be a dict with a ``rates`` mapping of
    {currency: rate-against-base}. Set ``ORBITBRIEF_FX_DISABLE=1``
    to force the static snapshot.
    """
    import os as _os
    import time as _time
    import urllib.request as _urlreq
    import json as _json

    if _os.environ.get("ORBITBRIEF_FX_DISABLE", "").strip().lower() in {"1", "true", "yes"}:
        return {}

    cache_key = _os.environ.get("ORBITBRIEF_FX_API_URL", "frankfurter")
    now = _time.time()
    cached = _FX_LIVE_CACHE.get(cache_key)
    if cached and (now - cached.get("_fetched_at", 0)) < 4 * 3600:
        return {k: v for k, v in cached.items() if k != "_fetched_at"}

    # Frankfurter quotes "1 base = N target", so we request base=USD
    # and INVERT to match our "1 unit of currency in USD" convention.
    url = _os.environ.get("ORBITBRIEF_FX_API_URL")
    if not url:
        symbols = ",".join(c for c in FX_TO_USD if c != "USD")
        url = f"https://api.frankfurter.app/latest?from=USD&to={symbols}"
    try:
        req = _urlreq.Request(url, headers={"User-Agent": "OrbitBrief/1.0"})
        with _urlreq.urlopen(req, timeout=5) as resp:
            body = _json.loads(resp.read().decode("utf-8") or "{}")
        rates_raw = body.get("rates") or {}
        # Invert: rate = 1 / (USD-base rate to target)
        rates = {
            curr: (1.0 / float(rate)) if float(rate) > 0 else 0.0
            for curr, rate in rates_raw.items()
        }
        rates["USD"] = 1.0
        rates["_fetched_at"] = now
        _FX_LIVE_CACHE[cache_key] = rates
        return {k: v for k, v in rates.items() if k != "_fetched_at"}
    except Exception:
        return {}


def _effective_fx_rate(currency: str) -> float:
    """Return the FX rate to use — live if reachable, static otherwise."""
    live = _fetch_live_fx_rates()
    if live and currency.upper() in live:
        return live[currency.upper()]
    return FX_TO_USD.get(currency.upper(), 0.0)


def usd_equivalent(amount: int, currency: str) -> int:
    rate = _effective_fx_rate((currency or "USD"))
    if rate <= 0:
        return 0
    return int(round(amount * rate))


@dataclass(frozen=True)
class CurrencyConversion:
    """One non-USD amount converted to its USD-equivalent.

    FX rates come from the static FX_TO_USD table. For SOX / contract
    use, replace with a live FX feed keyed to the deal close date.
    """
    currency: str
    amount: int
    usd_equivalent: int
    fx_rate_used: float
    source: str
    snippet: str


def build_currency_conversions(currency_mentions: list[dict[str, Any]]) -> list[CurrencyConversion]:
    """Project ``CurrencyMention`` dicts into USD-equivalent rows
    using live FX rates when reachable, static fallback otherwise."""
    out: list[CurrencyConversion] = []
    for cm in currency_mentions:
        curr = (cm.get("currency") or "").upper()
        amount = int(cm.get("amount") or 0)
        if not curr or amount <= 0:
            continue
        rate = _effective_fx_rate(curr)
        if rate <= 0:
            continue
        out.append(CurrencyConversion(
            currency=curr,
            amount=amount,
            usd_equivalent=int(round(amount * rate)),
            fx_rate_used=rate,
            source=cm.get("source", ""),
            snippet=cm.get("snippet", ""),
        ))
    return out


# ────────────────────────────── Hardware EOL/EOS ──────────────────────────────


@dataclass(frozen=True)
class EolFlag:
    """A BOM line whose part number is on the known EOL/EOS list."""
    part_number: str
    description: str
    quantity: int
    eol_status: str
    replacement_hint: str
    source: str


_KNOWN_EOL_PARTS: dict[str, tuple[str, str]] = {
    # Cisco Catalyst
    "C9200-24P": ("EOS", "Catalyst 9300X-24P or Catalyst 9200CX-24P"),
    "C9300-24T-A": ("EOS", "Catalyst 9300X-24T"),
    "C9200L-24T-4G-A": ("extended_support_only", "Catalyst 9200CX-24T"),
    "WS-C2960X-24PD-L": ("EOL", "Catalyst 9200CX-24P"),
    "WS-C3850-24P-L": ("EOL", "Catalyst 9300-24P"),
    "WS-C3850-48P-L": ("EOL", "Catalyst 9300-48P"),
    "C8200-1N-4T": ("EOS", "C8300 platform"),
    "ISR4321/K9": ("extended_support_only", "C8200-1N-4T"),
    "ISR4331/K9": ("EOL", "C8300-1N1S-6T"),
    "ASA5505-K9": ("EOL", "Firepower 1010"),
    "ASA5510-K9": ("EOL", "Firepower 1120"),
    # Meraki
    "MR42": ("EOS", "MR46"),
    "MR52": ("EOL", "MR57"),
    "MR84": ("EOL", "MR55"),
    "MX64": ("EOS", "MX67"),
    "MX84": ("EOS", "MX85 / MX95"),
    "MS220-8P": ("EOL", "MS130-8P"),
    "MS320-24P": ("EOL", "MS390-24P"),
    # Aruba
    "JL357A": ("EOS", "Aruba CX 6300M"),
    "AP-225": ("EOL", "AP-535 / AP-635"),
    "AP-305": ("EOS", "AP-505"),
    # Crestron
    "DM-MD8X8": ("EOL", "DM-NVX 360"),
    "DM-MD16X16": ("EOL", "DM-NVX 360 fabric"),
    "DMC-HD": ("EOL", "DM-NVX-D30"),
    # Polycom/Poly
    "GROUP 310": ("EOL", "Poly G7500 / Studio X"),
    "GROUP 500": ("EOL", "Studio X70"),
    "GROUP 700": ("EOL", "Studio X70 + multi-camera"),
    # Cisco Webex
    "CS-ROOM-KIT-K9": ("EOS", "Cisco Room Kit Pro / Room Bar"),
    "CS-MX800-K9": ("EOL", "Room Bar Pro"),
    # Software lifecycle
    "SECURITY CENTER 5.10": ("extended_support_only", "Security Center 5.12"),
    "XPROTECT 2020 R3": ("EOS", "XProtect 2024 R1"),
}


def _normalize_part_number(value: str) -> str:
    return (value or "").upper().replace("‐", "-").replace(" ", "").strip()


def _query_cisco_eox(part_numbers: list[str]) -> dict[str, tuple[str, str]]:
    """Cisco EoX lookup adapter.

    Returns ``{part_number: (status, replacement_hint)}`` for the
    subset Cisco knows about. Requires the user to set:

      CISCO_EOX_OAUTH_TOKEN  — OAuth2 bearer token from
                                api.cisco.com (registered apps).

    Silently returns {} when the token is missing or the endpoint
    is unreachable so the brief still renders with the static
    ``_KNOWN_EOL_PARTS`` fallback. The static list ships with the
    most-encountered SKUs so this live path is upside, not a
    prerequisite.
    """
    import os as _os
    import urllib.request as _urlreq
    import json as _json
    token = _os.environ.get("CISCO_EOX_OAUTH_TOKEN", "").strip()
    if not token or not part_numbers:
        return {}
    out: dict[str, tuple[str, str]] = {}
    # Cisco EoX accepts up to 20 SKUs per request.
    for batch_start in range(0, len(part_numbers), 20):
        batch = part_numbers[batch_start : batch_start + 20]
        sku_str = ",".join(batch)
        url = f"https://apix.cisco.com/supporttools/eox/rest/5/EOXByProductID/1/{sku_str}"
        try:
            req = _urlreq.Request(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
            )
            with _urlreq.urlopen(req, timeout=10) as resp:
                body = _json.loads(resp.read().decode("utf-8") or "{}")
        except Exception:
            continue
        for record in body.get("EOXRecord") or []:
            pid = (record.get("EOLProductID") or "").strip()
            if not pid:
                continue
            end_of_sale = (record.get("EndOfSaleDate") or {}).get("value") or ""
            end_of_support = (record.get("LastDateOfSupport") or {}).get("value") or ""
            replacement = ""
            for mig in record.get("EOXMigrationDetails") or []:
                replacement = (mig.get("MigrationProductInfoURL") or
                               mig.get("MigrationProductId") or
                               mig.get("MigrationInformation") or "")
                if replacement:
                    break
            if end_of_support:
                status = "EOL"
            elif end_of_sale:
                status = "EOS"
            else:
                continue
            out[pid] = (status, replacement[:140] or "see Cisco EoX bulletin")
    return out


def build_eol_flags(report: dict[str, Any]) -> list[EolFlag]:
    """Match every BOM ``part_number`` against the static EOL list,
    augmented with a live Cisco EoX lookup when the OAuth token
    env var is set. The live lookup is upside — static list always
    fires so the brief is deterministic without any external deps.
    """
    out: list[EolFlag] = []
    seen: set[str] = set()
    norm_lookup: dict[str, tuple[str, str, str]] = {
        _normalize_part_number(pn): (pn, status, hint)
        for pn, (status, hint) in _KNOWN_EOL_PARTS.items()
    }
    # Collect every distinct BOM part_number once so we batch the
    # live Cisco EoX query into a single roundtrip.
    bom_part_numbers: list[str] = []
    seen_pns: set[str] = set()
    for atom, _filename in _iter_atoms_with_files(report):
        if atom.get("atom_type") != "vendor_line_item":
            continue
        s = atom.get("structured") or {}
        if not isinstance(s, dict):
            continue
        pn = (str(s.get("part_number") or "")).strip()
        if pn and pn.upper() not in seen_pns:
            seen_pns.add(pn.upper())
            bom_part_numbers.append(pn)
    live_eox = _query_cisco_eox(bom_part_numbers)
    for atom, filename in _iter_atoms_with_files(report):
        if atom.get("atom_type") != "vendor_line_item":
            continue
        s = atom.get("structured") or {}
        if not isinstance(s, dict):
            continue
        raw_pn = str(s.get("part_number") or "")
        if not raw_pn:
            continue
        norm = _normalize_part_number(raw_pn)
        match = norm_lookup.get(norm)
        if not match:
            for k, v in norm_lookup.items():
                if k and k in norm:
                    match = v
                    break
        # Live Cisco EoX override — wins over static list when present.
        live = live_eox.get(raw_pn)
        if live:
            match = (raw_pn, live[0], live[1])
        if not match:
            continue
        key = raw_pn + filename
        if key in seen:
            continue
        seen.add(key)
        try:
            qty = int(float(s.get("quantity") or 0))
        except (ValueError, TypeError):
            qty = 0
        out.append(EolFlag(
            part_number=raw_pn,
            description=str(s.get("description") or "")[:200],
            quantity=qty,
            eol_status=match[1],
            replacement_hint=match[2],
            source=filename,
        ))
    return out


# ────────────────────────────── Real critical-path with dependencies ──────────────────────────────


@dataclass(frozen=True)
class PhaseDependency:
    """One detected upstream→downstream phase dependency."""
    upstream: str
    downstream: str
    evidence: str
    source: str


_DEPENDENCY_RE = re.compile(
    r"\b("
    r"after\s+(?P<after>[A-Z][\w\s]{2,40})\s+(?:is\s+)?(?:complete|completes?|done|finished|signed|accepted)|"
    r"depends\s+on\s+(?P<deps>[A-Z][\w\s]{2,40})|"
    r"prerequisite[:\s]+(?P<prereq>[A-Z][\w\s]{2,40})|"
    r"blocked\s+by\s+(?P<block>[A-Z][\w\s]{2,40})|"
    r"requires\s+(?P<req>[A-Z][\w\s]{2,40})\s+(?:to\s+(?:complete|finish|be\s+done))"
    r")\b",
    re.IGNORECASE,
)


def build_phase_dependencies(report: dict[str, Any]) -> list[PhaseDependency]:
    out: list[PhaseDependency] = []
    for atom, filename in _iter_atoms_with_files(report):
        text = atom.get("text") or ""
        if not text:
            continue
        for m in _DEPENDENCY_RE.finditer(text):
            upstream = (
                m.group("after") or m.group("deps") or m.group("prereq")
                or m.group("block") or m.group("req") or ""
            ).strip()
            if not upstream or len(upstream) > 60:
                continue
            pre = text[max(0, m.start() - 80): m.start()]
            phase_m = re.search(r"\b([A-Z][\w]+(?:\s+[A-Z][\w]+){0,3})\b", pre[::-1])
            downstream = phase_m.group(1)[::-1].strip() if phase_m else ""
            if downstream and downstream != upstream:
                out.append(PhaseDependency(
                    upstream=upstream,
                    downstream=downstream,
                    evidence=text[max(0, m.start() - 40): m.end() + 60][:200],
                    source=filename,
                ))
    return out


def critical_path_from_dependencies(
    phases: list[dict[str, Any]],
    dependencies: list[PhaseDependency],
) -> list[str]:
    """Compute critical-path phase chain via dep-graph longest path.
    Falls back to sequential ordering when no real deps detected."""
    if not dependencies:
        return [p.get("phase", "") for p in phases if p.get("start") and p.get("end")]
    adj: dict[str, set[str]] = defaultdict(set)
    nodes: set[str] = set()
    for p in phases:
        name = (p.get("phase") or "").strip()
        if name:
            nodes.add(name)
    for d in dependencies:
        u = d.upstream.strip()
        dn = d.downstream.strip()
        if u in nodes and dn in nodes:
            adj[u].add(dn)
    memo: dict[str, list[str]] = {}
    def longest(n: str) -> list[str]:
        if n in memo:
            return memo[n]
        best: list[str] = []
        for nxt in adj.get(n, set()):
            cand = longest(nxt)
            if len(cand) > len(best):
                best = cand
        memo[n] = [n] + best
        return memo[n]
    chains = [longest(n) for n in nodes]
    return max(chains, key=len, default=[])


# ────────────────────────────── Historical bench data ──────────────────────────────


@dataclass(frozen=True)
class ComparableDeal:
    """One past-deal entry from the append-only corpus history."""
    case_id: str
    closed_at: str
    deal_value_usd: int
    domains: list[str]
    sites_count: int
    phase_count: int
    final_margin_pct: float = 0.0
    outcome: str = ""


def write_corpus_history(history_path: Any, snapshot: dict[str, Any]) -> None:
    """Append-only ledger of every brief generated. Each row carries
    the salient PM-facing metrics for ``load_comparable_deals``."""
    import json as _json
    from pathlib import Path as _Path
    p = _Path(history_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(_json.dumps(snapshot, ensure_ascii=False) + "\n")


def load_comparable_deals(
    history_path: Any,
    *,
    target_value_usd: int = 0,
    target_domains: list[str] | None = None,
    limit: int = 5,
) -> list[ComparableDeal]:
    """Return the N past deals closest to ``target_value_usd`` /
    overlapping ``target_domains``. Empty list when corpus is empty."""
    import json as _json
    import math
    from pathlib import Path as _Path
    p = _Path(history_path)
    if not p.exists():
        return []
    target_domains_set = set(target_domains or [])
    candidates: list[tuple[float, ComparableDeal]] = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            try:
                row = _json.loads(line)
            except _json.JSONDecodeError:
                continue
            try:
                deal = ComparableDeal(
                    case_id=str(row.get("case_id", "")),
                    closed_at=str(row.get("closed_at", "")),
                    deal_value_usd=int(row.get("deal_value_usd") or 0),
                    domains=list(row.get("domains") or []),
                    sites_count=int(row.get("sites_count") or 0),
                    phase_count=int(row.get("phase_count") or 0),
                    final_margin_pct=float(row.get("final_margin_pct") or 0),
                    outcome=str(row.get("outcome", "")),
                )
            except (TypeError, ValueError):
                continue
            if deal.deal_value_usd > 0 and target_value_usd > 0:
                value_dist = abs(math.log(deal.deal_value_usd) - math.log(target_value_usd))
            else:
                value_dist = 10.0
            overlap = len(target_domains_set & set(deal.domains))
            score = value_dist - 0.5 * overlap
            candidates.append((score, deal))
    candidates.sort(key=lambda x: x[0])
    return [d for _, d in candidates[:limit]]
