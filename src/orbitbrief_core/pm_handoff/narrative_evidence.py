"""No-loss narrative RAG pack for executive_summary.overview.

Prefers full envelope atoms (not truncated inspection lineage), classifies
into PM facets, near-dedupes, then facet-seeds a diverse evidence pack so
scope / commercial / sites / access / BOM / risks / acceptance are not
silently dropped before the brief is written.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from orbitbrief_core.pm_handoff.fact_quality import (
    commercial_substance,
    deal_substance,
    is_hard_conversation_filler,
)

FACETS = (
    "scope",
    "commercial",
    "sites",
    "access",
    "bom",
    "risks",
    "acceptance",
    "schedule",
    "stakeholders",
)

_FACET_ATOM_TYPES: dict[str, frozenset[str]] = {
    "scope": frozenset(
        {
            "scope_item",
            "work_package",
            "service_line",
            "deliverable",
            "exclusion",
            "responsibility",
            "open_question",
        }
    ),
    "commercial": frozenset(
        {
            "money",
            "pricing",
            "commercial_term",
            "commercial_total",
            "vendor_line_item",
            "quantity",
            "deal_metadata",
        }
    ),
    "sites": frozenset({"physical_site", "address", "site_roster", "site"}),
    "access": frozenset({"access_requirement", "constraint", "safety", "badge"}),
    "bom": frozenset(
        {
            "asset_record",
            "device",
            "bom_line",
            "vendor_line_item",
            "circuit_inventory",
            "port_vlan_assignment",
        }
    ),
    "risks": frozenset({"risk", "open_question", "constraint"}),
    "acceptance": frozenset(
        {"acceptance", "cutover_validation", "exit_criteria", "checklist_item"}
    ),
    "schedule": frozenset({"schedule_phase", "date", "milestone"}),
    "stakeholders": frozenset({"stakeholder", "contact", "role"}),
}

_FACET_LEX: dict[str, re.Pattern[str]] = {
    "scope": re.compile(
        r"\b(install|survey|scope|deliver|visit|mobilize|smart[\s-]?hands|"
        r"fixed[\s-]?fee|tank|telemetry|anova|rtu|codec|display)\b",
        re.I,
    ),
    "commercial": re.compile(
        r"\b(\$\d|usd|fixed|t&m|time\s*and\s*material|net\s*30|billing|"
        r"purchase\s*order|quote|pricing|per[\s-]?location|change[\s-]?order)\b",
        re.I,
    ),
    "sites": re.compile(
        r"\b(site|location|address|office|plant|warehouse|chattanooga|"
        r"saginaw|decatur|forest\s*park)\b",
        re.I,
    ),
    "access": re.compile(
        r"\b(access\s+requir|escort|badg(?:e|ing)?|ppe|ladder|lift|scaffold|"
        r"tank\s*access|after[\s-]?hours|clearance|twic|site\s+access|"
        r"48h\s+notice|security\s+escort)\b",
        re.I,
    ),
    "bom": re.compile(
        r"\b(dpa\d+|dpw\d+|bom|sku|part\s*number|heater|power\s*supply|"
        r"mount|hdmi|sensor|modem|antenna)\b",
        re.I,
    ),
    "risks": re.compile(
        r"\b(risk|blocker|unknown|unconfirm|undecided|ambiguous|conflict|"
        r"keep.?vs.?remove|authoritative)\b",
        re.I,
    ),
    "acceptance": re.compile(
        r"\b(accept|validation|go[\s-]?live|readiness|checklist|sign[\s-]?off|"
        r"completion|photos?)\b",
        re.I,
    ),
    "schedule": re.compile(
        r"\b(schedule|visit|wave|mobilize|start|finish|week|monday|tuesday)\b",
        re.I,
    ),
    "stakeholders": re.compile(
        r"\b(customer|provider|pm\b|ops\s*director|contact|email@|@"
        r"|purtera|olin)\b",
        re.I,
    ),
}

_NARRATIVE_KEEP_TYPES = frozenset(
    {
        "physical_site",
        "address",
        "site",
        "bom_line",
        "device",
        "asset_record",
        "decision",
        "risk",
        "action_item",
        "constraint",
        "access_requirement",
        "safety",
        "badge",
        "milestone_phase",
        "schedule_phase",
        "scope_item",
        "work_package",
        "deliverable",
        "exclusion",
        "responsibility",
        "money",
        "pricing",
        "commercial_term",
        "acceptance",
        "cutover_validation",
        "exit_criteria",
        "checklist_item",
        "stakeholder",
        "contact",
        "open_question",
    }
)

_MANUAL_OR_BOILERPLATE_RE = re.compile(
    r"(?i)\b("
    r"galvanic\s+isolation|analogue\s+channels?|diagnostic\s+routine|"
    r"current\s+measurement\s+values|dw900\s+device|stated\s+rate\s+for\s+"
    r"(?:domestic|international)|50%\s+increase\s+of\s+stated|"
    r"shipment\s+and\s+delivery\s+numbers|screen\s+shots\s+of\s+issues|"
    r"prepaid\s+funds\s+have|draw\s+down\s+the\s+balance|"
    r"e-?mail\s+message\s+is\s+intended|confidential(?:ity)?\s+notice|"
    r"urldefense|proofpoint|unsubscribe"
    r")\b"
)

_FIELD_PM_SIGNAL_RE = re.compile(
    r"(?i)\b("
    r"anova|tank|telemetry|rtu|dpa\d+|dpw\d+|keep.?vs.?remove|codec|"
    r"fixed[\s-]?fee|per[\s-]?location|site\s+list|authoritative|"
    r"escort|badg(?:e|ing)|ppe|ladder|lift|mobilize|survey|"
    r"chattanooga|saginaw|decatur|forest\s*park|olin|purtera\s+will|"
    r"customer\s+will|confirm\b|blocker|nte|net\s*30"
    r")\b"
)

# Keep long atom bodies for the briefing LLM. UI may truncate later.
_PACK_TEXT_CAP = 1200


def _atom_text(atom: Mapping[str, Any]) -> str:
    return str(atom.get("text") or atom.get("raw_text") or "").strip()


def _atom_type(atom: Mapping[str, Any]) -> str:
    return str(atom.get("atom_type") or atom.get("type") or "").strip().lower()


def _norm_key(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").lower()).strip()
    t = re.sub(r"[^\w\s$./-]", "", t)
    return t[:400]


def collect_envelope_atoms(
    envelope: Mapping[str, Any] | None,
    report: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Prefer full envelope atoms; fall back to richest inspection projection."""
    atoms: list[dict[str, Any]] = []
    if isinstance(envelope, Mapping):
        for a in envelope.get("atoms") or []:
            if isinstance(a, dict) and _atom_text(a):
                atoms.append(dict(a))
    if atoms:
        return atoms

    report = report or {}
    by_id: dict[str, dict[str, Any]] = {}
    for art in report.get("artifacts") or []:
        if not isinstance(art, dict):
            continue
        for a in art.get("atoms") or []:
            if not isinstance(a, dict):
                continue
            aid = str(a.get("id") or a.get("atom_id") or "")
            text = _atom_text(a)
            if not text:
                continue
            prev = by_id.get(aid) if aid else None
            if not prev or len(text) > len(_atom_text(prev)):
                by_id[aid or f"anon:{len(by_id)}"] = dict(a)
    if by_id:
        return list(by_id.values())

    out: list[dict[str, Any]] = []
    for a in report.get("atom_lineage") or report.get("atoms") or []:
        if isinstance(a, dict) and _atom_text(a):
            out.append(dict(a))
    return out


def classify_narrative_facets(atom: Mapping[str, Any]) -> set[str]:
    atype = _atom_type(atom)
    text = _atom_text(atom)
    facets: set[str] = set()
    type_hits: set[str] = set()
    for facet, types in _FACET_ATOM_TYPES.items():
        if atype in types:
            facets.add(facet)
            type_hits.add(facet)
    for facet, pat in _FACET_LEX.items():
        if pat.search(text):
            facets.add(facet)
    for key in atom.get("entity_keys") or ():
        if not isinstance(key, str):
            continue
        if key.startswith("site:"):
            facets.add("sites")
        elif key.startswith("device:") or key.startswith("sku:"):
            facets.add("bom")
        elif key.startswith("money:"):
            facets.add("commercial")
        elif key.startswith("stakeholder:"):
            facets.add("stakeholders")
    if not facets and text:
        facets.add("scope")
    if isinstance(atom, dict) and type_hits:
        atom["_type_facets"] = sorted(type_hits)
    return facets


def _facet_priority(atom: Mapping[str, Any], facet: str) -> int:
    type_facets = set(atom.get("_type_facets") or ())
    if not type_facets:
        atype = _atom_type(atom)
        type_facets = {f for f, types in _FACET_ATOM_TYPES.items() if atype in types}
    if facet in type_facets:
        return 2
    facets = set(atom.get("_narrative_facets") or classify_narrative_facets(atom))
    if facet in facets:
        return 1
    return 0


def is_manual_or_boilerplate(text: str) -> bool:
    return bool(_MANUAL_OR_BOILERPLATE_RE.search(text or ""))


_OFF_DEAL_CONTACT_RE = re.compile(
    r"(?i)\b(platform\s+science|salesforce\.com|linkedin\.com)\b"
)

# "Megan Blevins | Global Strategic Account Executive" — title-only, no duty.
_THIN_STAKEHOLDER_RE = re.compile(
    r"(?i)^[A-Z][a-z]+(?:\s+[A-Z][a-z.'-]+){0,3}\s*[|—\-]\s*"
    r"(?:global\s+)?(?:strategic\s+)?(?:account\s+)?(?:executive|manager|director|"
    r"engineer|coordinator|specialist|ae\b|pm\b|sa\b).*$"
)

_OCR_SHRED_RE = re.compile(
    r"(?i)(?:"
    r"\bcol_\d+\b|"
    r"\bdescrip(?:tion)?\b\s*:?\s*(?:descrip|ption)\b|"
    r"\bbilling\s+increment\b|"
    r"\bmated:\s*\(usd\)|"
    r"\bted\s*fees?\s*sd\b|"
    r"\|\s*ted\s*fees|"
    r"^\(?\s*\)\s*\$|"
    r"\bsurcharge_\d+\b|"
    r"^[A-Z]{2,}_[A-Z0-9]{1,}\s+\d+\.?$|"
    r"^[A-Z0-9]{8,}\s+\d+\.?$"
    r")"
)


def sanitize_narrative_text(text: str) -> str:
    """Repair common OCR / table-extract junk before briefing consumes the atom."""
    t = (text or "").strip()
    if not t:
        return ""
    # Prefer a clean commercial sentence when we can recover amount + line.
    m = re.search(
        r"(?i)(\d+\s+sites?[:\s]+survey(?:\s*&\s*\d+\s+tank\s+installs?)?)"
        r".{0,80}?\$([\d,]+(?:\.\d+)?)",
        t,
    )
    if m and (
        re.search(r"(?i)billing\s+increment|ted\s*fees|tank\s+install|survey", t)
        or "$" in t
    ):
        line = re.sub(r"\s+", " ", m.group(1)).strip(" :|-")
        return f"Fixed commercial line: {line} - ${m.group(2)}."

    # Soft-drop quote-validity / currency chrome (no amount).
    if re.search(
        r"(?i)^(?:this quote is valid for|fees are in usd)\b",
        t,
    ):
        return ""
    # Address pipe artifacts: "1215 S. Jefferson |, Saginaw, MI 48601"
    t = re.sub(r"\s*\|\s*,", ",", t)
    t = re.sub(r"\s*\|\s*", " — ", t)
    t = re.sub(r"(?i)billing\s+increment:\s*", "", t)
    t = re.sub(
        r"(?i)\s*(?:fixed\s*)?(?:—\s*)?ted\s*fees?\s*sd\)?:?\s*(?:\(\s*\))?\s*",
        " ",
        t,
    )
    t = re.sub(r"\(\s*\)\s*", " ", t)
    t = re.sub(r"\s*[—\-]{2,}\s*", " — ", t)
    t = re.sub(r"\s{2,}", " ", t).strip(" |:—-")
    return t.strip()


def is_ocr_shred(text: str) -> bool:
    t = text or ""
    if _OCR_SHRED_RE.search(t):
        # Keep if we already sanitized to a clean commercial line.
        if t.lower().startswith("fixed commercial line:") and "$" in t:
            return False
        return True
    # High ratio of short ALLCAPS tokens / broken table cells
    tokens = re.findall(r"[A-Za-z]{2,}", t)
    if len(tokens) >= 4:
        caps = sum(1 for w in tokens if w.isupper() and len(w) <= 6)
        if caps / len(tokens) >= 0.45 and "$" not in t:
            return True
    return False


def is_thin_stakeholder_line(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if _THIN_STAKEHOLDER_RE.match(t):
        return True
    if "|" in t or "—" in t:
        if len(t) < 90 and not re.search(
            r"(?i)\b(will|confirm|email|@|phone|site|tank|anova|olin|purtera)\b",
            t,
        ):
            return True
    return False


def is_raw_address_only(text: str) -> bool:
    """Street-only rows already covered by publishable site names."""
    t = sanitize_narrative_text(text)
    if not t or len(t) > 120:
        return False
    has_street = bool(
        re.search(
            r"(?i)\b(\d{2,5}\s+[A-Za-z].*\b(?:st|street|ave|avenue|rd|road|blvd|dr|drive|way|ln|lane)\b)",
            t,
        )
    )
    has_zip = bool(re.search(r"\b\d{5}(?:-\d{4})?\b", t))
    has_work = bool(
        re.search(
            r"(?i)\b(install|survey|tank|anova|visit|access|confirm|scope|fee)\b",
            t,
        )
    )
    return bool((has_street or has_zip) and not has_work)


_EMAIL_INTRO_RE = re.compile(
    r"(?i)^(?:hi|hey|hello)\s+\w+\b|"
    r"got a great intro|"
    r"\$\d[\d.,]*\s+billion\s+manufacturing"
)


def is_narrative_relevant(atom: Mapping[str, Any]) -> bool:
    """Keep deal-operative atoms; drop manuals/boilerplate without killing facets."""
    raw = _atom_text(atom)
    text = sanitize_narrative_text(raw)
    if len(text) < 12:
        return False
    if is_ocr_shred(raw) and not text.lower().startswith("fixed commercial line:"):
        return False
    if is_ocr_shred(text) and not text.lower().startswith("fixed commercial line:"):
        return False
    if is_hard_conversation_filler(atom, text):
        return False
    if is_manual_or_boilerplate(text):
        return False
    if is_thin_stakeholder_line(text):
        return False
    if is_raw_address_only(text):
        return False
    if _EMAIL_INTRO_RE.search(text) and not re.search(
        r"(?i)\b(install|survey|tank|anova|site|sow|quote\s+line)\b",
        text,
    ):
        return False
    if re.search(r"(?i)^applicable\s+tax/?vat\b", text) and "$" not in text:
        return False
    # Contacts from adjacent vendors with no field-PM signal.
    if _OFF_DEAL_CONTACT_RE.search(text) and not _FIELD_PM_SIGNAL_RE.search(text):
        return False
    # Generic MSA billing chrome without a concrete commercial line.
    if re.search(r"(?i)bill(?:s|ing)?\s+the\s+customer\s+monthly\s+in\s+arrears", text):
        if not re.search(r"\$\d|tank|survey|fixed|nte|per[\s-]?location", text, re.I):
            return False
    # Estimated fees chrome with no amount.
    if re.search(
        r"(?i)^the estimated fees for services outlined below are fixed fee\.?$",
        text,
    ):
        return False
    atype = _atom_type(atom)
    if atype in _NARRATIVE_KEEP_TYPES:
        return True
    if commercial_substance(text) or _FIELD_PM_SIGNAL_RE.search(text):
        return True
    if deal_substance(text) and len(text) <= 420:
        return True
    # Untyped money lines still matter.
    if re.search(r"\$[\d,]+", text) and re.search(
        r"(?i)\b(tank|survey|sites?|revenue|total|fee|quote)\b",
        text,
    ):
        return True
    return False


def filter_narrative_atoms(atoms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Relevance filter for no-loss RAG — never neural-drop structured facets."""
    out: list[dict[str, Any]] = []
    for atom in atoms:
        if not is_narrative_relevant(atom):
            continue
        row = dict(atom)
        cleaned = sanitize_narrative_text(_atom_text(row))
        if cleaned:
            row["text"] = cleaned
        out.append(row)
    return out


def _quality(atom: Mapping[str, Any]) -> float:
    conf = float(atom.get("confidence") or 0.0)
    bonus = 0.0
    text = _atom_text(atom)
    if str(atom.get("verified") or "") == "verified":
        bonus += 0.15
    if (atom.get("downstream") or {}).get("bundled"):
        bonus += 0.05
    auth = str(atom.get("authority") or "").lower()
    if auth in {"sow", "contract", "quote", "deal_kit"}:
        bonus += 0.12
    if _atom_type(atom) in _NARRATIVE_KEEP_TYPES:
        bonus += 0.08
    if _FIELD_PM_SIGNAL_RE.search(text):
        bonus += 0.12
    if commercial_substance(text):
        bonus += 0.08
    if "$" in text and _FIELD_PM_SIGNAL_RE.search(text):
        bonus += 0.1
    if text.strip().endswith("?") or text.lower().startswith("confirm"):
        bonus += 0.06
    # Prefer concrete site / duty lines over generic MSA clauses.
    if re.search(r"(?i)\b(purtera will|customer will|two visits|tank install)", text):
        bonus += 0.1
    if text.lower().startswith("fixed commercial line:"):
        bonus += 0.25
    if _EMAIL_INTRO_RE.search(text):
        bonus -= 0.4
    if re.search(r"(?i)^applicable\s+tax/?vat\b", text):
        bonus -= 0.3
    n = len(text)
    if 40 <= n <= 420:
        bonus += 0.08
    elif n > 800:
        bonus -= 0.12
    if is_manual_or_boilerplate(text):
        bonus -= 0.5
    return conf + bonus


def dedupe_narrative_atoms(atoms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Exact-normalized dedupe; keep highest quality, union facets."""
    best: dict[str, dict[str, Any]] = {}
    facet_map: dict[str, set[str]] = {}
    for atom in atoms:
        text = _atom_text(atom)
        key = _norm_key(text)
        if len(key) < 12:
            continue
        facets = classify_narrative_facets(atom)
        prev = best.get(key)
        if prev is None or _quality(atom) >= _quality(prev):
            best[key] = atom
            facet_map[key] = facet_map.get(key, set()) | facets
        else:
            facet_map[key] = facet_map.get(key, set()) | facets
    out: list[dict[str, Any]] = []
    for key, atom in best.items():
        row = dict(atom)
        row["_narrative_facets"] = sorted(facet_map.get(key) or [])
        out.append(row)
    return out


def _overlap_ratio(a: str, b: str) -> float:
    ta = set(_norm_key(a).split())
    tb = set(_norm_key(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(1, len(ta | tb))


def _pack_row(atom: Mapping[str, Any]) -> dict[str, Any]:
    text = sanitize_narrative_text(_atom_text(atom))
    if len(text) > _PACK_TEXT_CAP:
        text = text[: _PACK_TEXT_CAP - 3].rstrip() + "..."
    return {
        "atom_id": str(atom.get("id") or atom.get("atom_id") or ""),
        "atom_type": _atom_type(atom),
        "facets": list(
            atom.get("_narrative_facets") or sorted(classify_narrative_facets(atom))
        ),
        "text": text,
        "confidence": float(atom.get("confidence") or 0.0),
        "artifact_id": str(atom.get("artifact_id") or ""),
        "verified": str(atom.get("verified") or ""),
    }


def select_narrative_rag_pack(
    atoms: list[dict[str, Any]],
    *,
    cap: int = 24,
) -> list[dict[str, Any]]:
    """Facet-seed then fill by quality so no major PM facet is wiped out."""
    if not atoms:
        return []
    by_facet: dict[str, list[dict[str, Any]]] = {f: [] for f in FACETS}
    for atom in atoms:
        facets = atom.get("_narrative_facets") or list(classify_narrative_facets(atom))
        for f in facets:
            if f in by_facet:
                by_facet[f].append(atom)
    for f in by_facet:
        by_facet[f].sort(
            key=lambda a, facet=f: (_facet_priority(a, facet), _quality(a)),
            reverse=True,
        )

    selected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_keys: set[str] = set()

    def _take(atom: dict[str, Any]) -> bool:
        aid = str(atom.get("id") or atom.get("atom_id") or "")
        key = _norm_key(_atom_text(atom))
        if aid and aid in seen_ids:
            return False
        if key in seen_keys:
            return False
        if aid:
            seen_ids.add(aid)
        seen_keys.add(key)
        selected.append(atom)
        return True

    _second_seed = frozenset({"scope", "commercial", "access", "risks", "bom"})
    for facet in FACETS:
        taken_for_facet = 0
        want = 2 if facet in _second_seed else 1
        for atom in by_facet.get(facet) or []:
            if _take(atom):
                taken_for_facet += 1
            if taken_for_facet >= want:
                break
        if len(selected) >= cap:
            break

    pool = sorted(atoms, key=_quality, reverse=True)
    for atom in pool:
        if len(selected) >= cap:
            break
        text = _atom_text(atom)
        if any(_overlap_ratio(text, _atom_text(s)) > 0.72 for s in selected):
            continue
        _take(atom)

    return [_pack_row(a) for a in selected[:cap]]


def build_narrative_rag_pack(
    *,
    envelope: Mapping[str, Any] | None,
    report: Mapping[str, Any] | None = None,
    cap: int = 24,
) -> list[dict[str, Any]]:
    """End-to-end: collect → relevance filter → dedupe → facet-cover select."""
    raw = collect_envelope_atoms(envelope, report)
    as_dicts = [
        dict(a) if isinstance(a, Mapping) else a
        for a in raw
        if isinstance(a, Mapping)
    ]
    kept = filter_narrative_atoms(as_dicts)
    deduped = dedupe_narrative_atoms(kept)
    return select_narrative_rag_pack(deduped, cap=cap)


def facet_coverage_summary(pack: list[Mapping[str, Any]]) -> dict[str, int]:
    counts = {f: 0 for f in FACETS}
    for row in pack:
        for f in row.get("facets") or []:
            if f in counts:
                counts[f] += 1
    return counts


__all__ = [
    "FACETS",
    "build_narrative_rag_pack",
    "classify_narrative_facets",
    "collect_envelope_atoms",
    "dedupe_narrative_atoms",
    "facet_coverage_summary",
    "filter_narrative_atoms",
    "is_manual_or_boilerplate",
    "is_narrative_relevant",
    "is_ocr_shred",
    "is_raw_address_only",
    "is_thin_stakeholder_line",
    "sanitize_narrative_text",
    "select_narrative_rag_pack",
]
