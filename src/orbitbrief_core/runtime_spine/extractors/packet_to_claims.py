from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable, Mapping

from .cad_packet_to_claims import extract_cad_claims_from_packet
from .narrative_claim_ontology import EvidenceRef, EvidenceRefSet, ExtractionDiagnostic, InternalClaim

_PACKET_TO_CLAIM: dict[str, str] = {
    "scope_packet": "scope_included_claim",
    "exclusion_packet": "scope_excluded_claim",
    "assumption_packet": "assumption_claim",
    "risk_packet": "risk_claim",
    "dependency_packet": "third_party_dependency_claim",
    "site_packet": "site_location_claim",
    "quantity_packet": "known_quantity_claim",
    "deliverable_packet": "deliverable_claim",
    "schedule_packet": "schedule_claim",
    "responsibility_packet": "customer_responsibility_claim",
    "open_question_packet": "open_question_claim",
    "drawing_metadata_packet": "drawing_metadata_claim",
    "site_identity_packet": "site_location_claim",
    "network_room_or_closet_packet": "site_location_claim",
    "equipment_reference_packet": "known_quantity_claim",
    "note_scope_packet": "scope_included_claim",
    "revision_change_packet": "deliverable_claim",
    "topology_hint_packet": "third_party_dependency_claim",
    "constructability_packet": "access_logistics_claim",
    "known_quantity_packet": "known_quantity_claim",
}

_CAD_PACKET_FAMILIES: frozenset[str] = frozenset(
    {
        "drawing_metadata_packet",
        "site_identity_packet",
        "network_room_or_closet_packet",
        "equipment_reference_packet",
        "note_scope_packet",
        "revision_change_packet",
        "topology_hint_packet",
        "constructability_packet",
    }
)

_CLAIM_TO_PACKET_FAMILY: dict[str, str] = {value: key for key, value in _PACKET_TO_CLAIM.items()}

_FAMILY_SIGNAL_TOKENS: dict[str, tuple[str, ...]] = {
    "scope_packet": ("scope", "include", "included", "in scope", "install", "configure", "migrate", "perform", "validate"),
    "exclusion_packet": ("exclude", "excluded", "out of scope", "not included", "will not"),
    "assumption_packet": ("assumption", "assume", "assuming", "presume"),
    "risk_packet": ("risk", "issue", "blocker", "delay", "uncertain"),
    "dependency_packet": ("dependency", "depends on", "third party", "carrier", "vendor", "landlord", "gc"),
    "site_packet": ("site", "location", "hq", "branch", "office"),
    "quantity_packet": ("qty", "quantity", "count", "number of", "devices", "aps", "switches", "units"),
    "deliverable_packet": ("deliverable", "deliverables", "output", "handoff", "runbook", "report", "as-built"),
    "schedule_packet": ("schedule", "timeline", "date", "deadline", "cutover", "week", "month"),
    "responsibility_packet": ("customer", "client", "responsibility", "owner", "provide", "by others"),
    "open_question_packet": ("?", "open question", "unknown", "tbd", "question"),
    "drawing_metadata_packet": ("sheet", "title block", "revision", "drawing", "diagram", "plan"),
    "site_identity_packet": ("site", "location", "address", "building", "floor", "campus"),
    "network_room_or_closet_packet": ("mdf", "idf", "closet", "telecom room", "network room"),
    "equipment_reference_packet": ("ap", "switch", "rack", "panel", "ups", "patch"),
    "note_scope_packet": ("note", "general notes", "install", "support", "scope"),
    "revision_change_packet": ("rev", "revision", "change"),
    "topology_hint_packet": ("uplink", "trunk", "cross-connect", "topology", "neighbor"),
    "constructability_packet": ("access", "badge", "escort", "constraint", "dependency", "readiness"),
    "known_quantity_packet": ("qty", "quantity", "count", "ft", "meters", "sqft"),
}

_FAMILY_TO_PARSER_CUES: dict[str, tuple[str, ...]] = {
    "scope_packet": ("scope_included",),
    "exclusion_packet": ("scope_excluded", "scope_by_others"),
    "assumption_packet": ("assumption",),
    "risk_packet": ("risk",),
    "dependency_packet": ("dependency",),
    "site_packet": ("site_location", "site_count"),
    "quantity_packet": ("quantity", "site_count"),
    "deliverable_packet": ("deliverable",),
    "schedule_packet": ("schedule",),
    "responsibility_packet": ("customer_responsibility", "scope_by_others"),
    "open_question_packet": ("open_question",),
    "drawing_metadata_packet": ("sheet_ref", "sheet_title", "title_block_field", "revision_entry"),
    "site_identity_packet": ("site_location", "title_block_field"),
    "network_room_or_closet_packet": ("site_location",),
    "equipment_reference_packet": ("quantity",),
    "note_scope_packet": ("scope_included", "assumption", "risk", "dependency"),
    "revision_change_packet": ("revision_entry",),
    "topology_hint_packet": ("dependency", "open_question"),
    "constructability_packet": ("risk", "dependency", "customer_responsibility"),
    "known_quantity_packet": ("quantity", "site_count"),
}

_FAMILY_CLEANUP_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "scope_packet": (
        re.compile(r"^(?:scope\s+(?:includes?|covers?|will include|to include)\s*[:\-]?\s*)", re.IGNORECASE),
        re.compile(r"^(?:in\s+scope\s*(?:is|are)?\s*[:\-]?\s*)", re.IGNORECASE),
    ),
    "exclusion_packet": (
        re.compile(r"^(?:scope\s+excludes?\s*[:\-]?\s*)", re.IGNORECASE),
        re.compile(r"^(?:out\s+of\s+scope\s*(?:is|are)?\s*[:\-]?\s*)", re.IGNORECASE),
        re.compile(r"^(?:excluded\s*[:\-]?\s*)", re.IGNORECASE),
    ),
    "assumption_packet": (
        re.compile(r"^(?:assumption(?:s)?\s*(?:is|are)?\s*[:\-]?\s*)", re.IGNORECASE),
        re.compile(r"^(?:assuming\s+)", re.IGNORECASE),
        re.compile(r"^(?:we\s+assume\s+)", re.IGNORECASE),
    ),
    "risk_packet": (
        re.compile(r"^(?:risk(?:s)?\s*(?:is|are|include)?\s*[:\-]?\s*)", re.IGNORECASE),
        re.compile(r"^(?:key\s+risk\s*[:\-]?\s*)", re.IGNORECASE),
    ),
    "dependency_packet": (
        re.compile(r"^(?:dependency(?:ies)?\s*(?:is|are)?\s*[:\-]?\s*)", re.IGNORECASE),
        re.compile(r"^(?:depends\s+on\s+)", re.IGNORECASE),
        re.compile(r"^(?:third\s+party\s+dependency\s*[:\-]?\s*)", re.IGNORECASE),
    ),
    "site_packet": (
        re.compile(r"^(?:site(?:s)?\s*(?:is|are|include)?\s*[:\-]?\s*)", re.IGNORECASE),
        re.compile(r"^(?:location(?:s)?\s*(?:is|are|include)?\s*[:\-]?\s*)", re.IGNORECASE),
    ),
    "quantity_packet": (
        re.compile(r"^(?:quantity\s*(?:is|are)?\s*[:\-]?\s*)", re.IGNORECASE),
        re.compile(r"^(?:qty\s*[:\-]?\s*)", re.IGNORECASE),
        re.compile(r"^(?:count\s*[:\-]?\s*)", re.IGNORECASE),
    ),
    "deliverable_packet": (
        re.compile(r"^(?:deliverable(?:s)?\s*(?:is|are|include)?\s*[:\-]?\s*)", re.IGNORECASE),
        re.compile(r"^(?:output\s*(?:is|are)?\s*[:\-]?\s*)", re.IGNORECASE),
        re.compile(r"^(?:handoff\s*(?:is|are)?\s*[:\-]?\s*)", re.IGNORECASE),
    ),
    "schedule_packet": (
        re.compile(r"^(?:schedule\s*(?:is|are)?\s*[:\-]?\s*)", re.IGNORECASE),
        re.compile(r"^(?:timeline\s*(?:is|are)?\s*[:\-]?\s*)", re.IGNORECASE),
        re.compile(r"^(?:deadline\s*(?:is|are)?\s*[:\-]?\s*)", re.IGNORECASE),
    ),
    "responsibility_packet": (
        re.compile(r"^(?:customer\s+responsibilit(?:y|ies)\s*(?:is|are)?\s*[:\-]?\s*)", re.IGNORECASE),
        re.compile(r"^(?:customer\s+(?:will|must|to|needs\s+to)\s+)", re.IGNORECASE),
        re.compile(r"^(?:client\s+(?:will|must|to|needs\s+to)\s+)", re.IGNORECASE),
    ),
    "open_question_packet": (
        re.compile(r"^(?:open\s+question\s*(?:is)?\s*[:\-]?\s*)", re.IGNORECASE),
        re.compile(r"^(?:question\s*(?:is)?\s*[:\-]?\s*)", re.IGNORECASE),
    ),
}


@dataclass(frozen=True, slots=True)
class PacketExtractionContext:
    role_id: str
    modality: str


@dataclass(frozen=True, slots=True)
class _SemanticSpanChoice:
    row: Mapping[str, Any]
    packet_family: str
    score: float


@dataclass(frozen=True, slots=True)
class _DirectClaimChoice:
    row: Mapping[str, Any]
    claim_family: str
    claim_body: str
    score: float


_ROW_KIND_BONUS: dict[str, float] = {
    "spreadsheet_kv": 2.4,
    "spreadsheet_fact": 2.3,
    "spreadsheet_row": 2.1,
    "table_row": 1.8,
    "bullet": 1.8,
    "paragraph": 1.2,
    "speaker_turn": 1.1,
    "list_item": 1.0,
    "heading": -2.6,
    "section_title": -2.6,
    "pdf_heading": -2.8,
}

_QUANTITY_PHRASE_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:months?|weeks?|days?|sites?|locations?|offices?|branches?|users?|seats?|devices?|units?|assets?|resources?|fte|drops?|aps?|switch(?:es)?)\b",
    flags=re.IGNORECASE,
)
_SITE_PHRASE_RE = re.compile(r"\b(?:site|hq|branch|office|campus|warehouse|datacenter|data center|region|address|onsite)\b", flags=re.IGNORECASE)
_SCHEDULE_PHRASE_RE = re.compile(
    r"\b(?:asap|planned service commencement|commencement|service commencement|initial term|transition period|service window|support coverage window|weekday operating schedule|weekday support coverage|timeline|deadline|cutover|milestone|onboarding|monthly|months?|weeks?|days?|years?|term|billing frequency)\b|\b\d{4}-\d{2}-\d{2}\b|\b\d+\s*(?:months?|weeks?|days?|years?)\b",
    flags=re.IGNORECASE,
)
_SCHEDULE_TRUE_COMMITMENT_RE = re.compile(
    r"\b(?:planned service commencement|service commencement|commence|commencement|initial transition period|transition period|cutover|go[-\s]*live|milestone|deadline|by \w+ \d{1,2}|on or before|within \d+\s+(?:days?|weeks?))\b|\b\d{4}-\d{2}-\d{2}\b",
    flags=re.IGNORECASE,
)
_SCHEDULE_ENGAGEMENT_TERM_RE = re.compile(
    r"\b(?:initial term|term:|for the duration of the engagement|duration|12 months|one \(1\) year|one year|two years|three years|\d+\s*(?:months?|years?))\b",
    flags=re.IGNORECASE,
)
_SCHEDULE_COVERAGE_WINDOW_RE = re.compile(
    r"\b(?:service window|support coverage window|weekday operating schedule|weekday support coverage|scheduled weekday support coverage|scheduled support coverage periods|primary support coverage|coverage window|business hours)\b",
    flags=re.IGNORECASE,
)
_SCHEDULE_OPERATIONAL_CONSTRAINT_RE = re.compile(
    r"\b(?:response target|reasonable[-\s]*efforts basis|subject to resource availability|outside the standard support schedule|outside that schedule|emergency requests|contingent upon ticket visibility|contingent upon|resource availability|constraints?)\b",
    flags=re.IGNORECASE,
)
_SCHEDULE_COMMERCIAL_RE = re.compile(
    r"\b(?:monthly billing|billed monthly|billing frequency|invoice(?:d)? monthly|monthly in arrears|payment obligations|monthly invoices?)\b",
    flags=re.IGNORECASE,
)
_LOW_SIGNAL_SECTION_TOKENS = (
    "acceptance criteria",
    "change process",
    "termination",
    "pricing",
    "payment terms",
    "sales contacts",
    "customer contacts",
    "introduction",
)
_RESPONSIBILITY_ACTION_RE = re.compile(
    r"\b(?:provide|designate|review|approve|communicate|grant|furnish|make available|coordinate|prioritize|submit|maintain|timely access|shall|must|will|needs to|required to)\b",
    flags=re.IGNORECASE,
)
_ASSUMPTION_SIGNAL_RE = re.compile(
    r"\b(?:assumption|assumptions|assuming|based on|will remain|is based on|confirmed during|to be confirmed during|unless)\b",
    flags=re.IGNORECASE,
)
_ASSUMPTION_STRONG_OPEN_RE = re.compile(
    r"^(?:assumption(?:s)?\b|we assume\b|assuming\b|this engagement is based on\b|pricing and staffing under this sow are based on\b)",
    flags=re.IGNORECASE,
)
_DELIVERABLE_SIGNAL_RE = re.compile(
    r"\b(?:deliverable|deliverables|runbook|handoff|report|service notes|knowledge transfer|knowledge base|worksheet|log|certificate|matrix|support coverage|assigned resource)\b",
    flags=re.IGNORECASE,
)
_SCOPE_SIGNAL_RE = re.compile(
    r"\b(?:scope|in scope|included|include|perform|provide|deliver|support|troubleshoot|onboarding|end-user support|incident intake|conference room support|printer support|endpoint management)\b",
    flags=re.IGNORECASE,
)
_GENERIC_SCOPE_HEADING_RE = re.compile(
    r"^(?:in[-\s]*scope\s+services\s+include|out[-\s]*of[-\s]*scope\s+services\s+include|scope\s+of\s+work|project\s+overview)\s*:?$",
    flags=re.IGNORECASE,
)
_QUANTITY_PHRASE_FLEX_RE = re.compile(
    r"\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)(?:\s*\(\s*\d+\s*\))?\s*(?:customer\s+)?(?:months?|weeks?|days?|sites?|locations?|offices?|branches?|users?|seats?|devices?|units?|assets?|resources?|fte|drops?|aps?|switch(?:es)?|engineers?|technicians?|resources?)\b",
    flags=re.IGNORECASE,
)


_GENERIC_SITE_CONTEXT_RE = re.compile(
    r"\b(?:customer locations?|supported locations?|remaining locations?|other customer locations?|other locations?|service location|work location|broader [^.;]+ environment)\b",
    flags=re.IGNORECASE,
)
_SITE_LABEL_CAPTURE_RE = re.compile(
    r"\b(?:site(?: name)?|location|office|branch|hq)\s*[:\-]\s*([^|;]+)",
    flags=re.IGNORECASE,
)
_SITE_ENTITY_CAPTURE_RE = re.compile(
    r"\b([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*(?:,\s*(?:[A-Z]{2}|[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*))?\s+(?:HQ|headquarters|office|branch|campus|warehouse|datacenter|data center))\b"
)
_SITE_PREPOSITION_CAPTURE_RE = re.compile(
    r"\b(?:in|from|at|across)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*(?:,\s*(?:[A-Z]{2}|[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*))?)\b"
)
_CONTACT_ROLE_TOKENS = (
    "director",
    "manager",
    "coordinator",
    "lead",
    "administrator",
    "architect",
    "engineer",
    "operations",
    "owner",
    "procurement",
    "technology",
    "support",
)
_CONTACT_HEADER_TOKENS = frozenset({
    "full name",
    "job title",
    "email address",
    "email",
    "phone",
    "phone number",
    "name",
    "title",
    "date",
    "signature",
    "agreed by",
    "services by",
})
_COMPANY_SUFFIX_TOKENS = {"llc", "inc", "corp", "corporation", "company", "group", "partners", "ltd", "llp", "pllc"}

_DIRECT_CLAIM_FAMILIES: frozenset[str] = frozenset(
    {
        "customer_identity",
        "project_summary",
        "site_count_claim",
        "commercial_structure_claim",
        "contact_claim",
    }
)

_NUMBER_WORDS: dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
}


def _as_tuple_of_str(value: Any) -> tuple[str, ...]:
    if isinstance(value, tuple):
        return tuple(str(item) for item in value if str(item))
    if isinstance(value, list):
        return tuple(str(item) for item in value if str(item))
    return ()


def _derive_status(packet_confidence: float, uncertainty_markers: tuple[str, ...]) -> tuple[str, bool, bool]:
    has_uncertainty = bool(uncertainty_markers)
    if packet_confidence >= 0.75 and not has_uncertainty:
        return ("asserted", False, False)
    if packet_confidence >= 0.55 and not has_uncertainty:
        return ("possible", False, False)
    if packet_confidence >= 0.4:
        return ("ambiguous", True, False)
    return ("needs_review", True, True)


def _packet_metadata(packet: Mapping[str, Any]) -> Mapping[str, Any]:
    metadata = packet.get("metadata", {})
    return metadata if isinstance(metadata, Mapping) else {}


def _span_rows(packet: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    values = packet.get("evidence_rows")
    if isinstance(values, list):
        return tuple(row for row in values if isinstance(row, Mapping))
    metadata = _packet_metadata(packet)
    values = metadata.get("evidence_rows")
    if isinstance(values, list):
        return tuple(row for row in values if isinstance(row, Mapping))
    return ()


def _packet_has_family_conflict(packet: Mapping[str, Any]) -> bool:
    metadata = _packet_metadata(packet)
    uncertainty = _as_tuple_of_str(metadata.get("uncertainty_markers", ()))
    if "family_conflict" in uncertainty:
        return True
    diagnostic = metadata.get("packet_diagnostic", {})
    if isinstance(diagnostic, Mapping):
        family = diagnostic.get("family", {})
        if isinstance(family, Mapping):
            competing = _as_tuple_of_str(family.get("competing_family_hints", ()))
            return bool(competing)
    return False


def _anchor_hint_family(packet: Mapping[str, Any]) -> str | None:
    metadata = _packet_metadata(packet)
    diagnostic = metadata.get("packet_diagnostic", {})
    if not isinstance(diagnostic, Mapping):
        return None
    anchor = diagnostic.get("anchor", {})
    if not isinstance(anchor, Mapping):
        return None
    hints = _as_tuple_of_str(anchor.get("family_hints", ()))
    for hint in hints:
        if hint in _PACKET_TO_CLAIM:
            return hint
    return None


def _score_row_for_family(row: Mapping[str, Any], packet_family: str, primary_span_id: str | None) -> float:
    score = 0.0
    span_id = str(row.get("span_id", "")).strip()
    text = str(row.get("text") or row.get("normalized_text") or "").strip()
    lower = text.lower()
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    row_kind = str(metadata.get("kind") or row.get("kind") or "").strip().lower()
    section_tokens = _section_tokens(row)
    parser_cues = {str(item).lower() for item in _as_tuple_of_str(row.get("parser_cues", ())) }
    packet_families = {str(item) for item in _as_tuple_of_str(row.get("packet_families", ())) }
    if primary_span_id and span_id == primary_span_id:
        score += 1.0
    if packet_family in packet_families:
        score += 2.6
    family_cues = set(_FAMILY_TO_PARSER_CUES.get(packet_family, ()))
    if parser_cues & family_cues:
        score += 3.0
    if any(token in lower for token in _FAMILY_SIGNAL_TOKENS.get(packet_family, ())):
        score += 1.8
    if text.endswith("?") and packet_family == "open_question_packet":
        score += 1.5
    if row_kind:
        score += _ROW_KIND_BONUS.get(row_kind, 0.0)
    if row_kind in {"heading", "section_title", "pdf_heading"} and len(text) <= 80:
        score -= 0.8
    if section_tokens and any(any(low in token for low in _LOW_SIGNAL_SECTION_TOKENS) for token in section_tokens):
        score -= 4.0
    primary_section_family = _section_primary_family(section_tokens)
    if primary_section_family == packet_family:
        score += 2.2
    elif primary_section_family is not None:
        score -= 2.2
    claim_body_overrides = metadata.get("claim_body_overrides", {}) if isinstance(metadata, Mapping) else {}
    override_text = ""
    if isinstance(claim_body_overrides, Mapping):
        override_text = str(claim_body_overrides.get(packet_family, "")).strip()
        if override_text:
            score += 3.2
    if packet_family == "quantity_packet":
        if override_text:
            score += 1.0
        elif _QUANTITY_PHRASE_RE.search(text):
            score += 1.8
        else:
            score -= 3.0
    if packet_family == "site_packet":
        specific_site = _extract_canonical_site_location(override_text or text)
        if specific_site:
            score += 2.6
        elif _extract_site_count(text):
            score -= 4.8
        elif override_text:
            score -= 0.8
        elif _SITE_PHRASE_RE.search(text):
            score -= 2.6
        else:
            score -= 1.8
    if packet_family == "schedule_packet":
        if override_text:
            score += 0.9
        elif _SCHEDULE_PHRASE_RE.search(text):
            score += 1.2
        else:
            score -= 1.2
    authority = row.get("authority_score")
    if isinstance(authority, (int, float)):
        score += min(0.5, float(authority) * 0.35)
    return score


def _section_tokens(row: Mapping[str, Any]) -> tuple[str, ...]:
    values = row.get("section_path", ())
    if isinstance(values, (list, tuple)):
        return tuple(str(item).strip().lower() for item in values if str(item).strip() and str(item).strip().lower() != "root")
    return ()


def _section_primary_family(section_tokens: tuple[str, ...]) -> str | None:
    joined = " | ".join(section_tokens)
    if "deliverable" in joined:
        return "deliverable_packet"
    if "out of scope" in joined:
        return "exclusion_packet"
    if "assumption" in joined:
        return "assumption_packet"
    if "customer responsibilities" in joined:
        return "responsibility_packet"
    if "timeline" in joined or "milestone" in joined or joined.endswith("schedule"):
        return "schedule_packet"
    if "scope of work" in joined or "project overview" in joined or "purtera responsibilities" in joined:
        return "scope_packet"
    return None


def _row_metadata(row: Mapping[str, Any]) -> Mapping[str, Any]:
    metadata = row.get("metadata")
    return metadata if isinstance(metadata, Mapping) else {}


def _row_kind(row: Mapping[str, Any]) -> str:
    metadata = _row_metadata(row)
    return str(metadata.get("kind") or row.get("kind") or "").strip().lower()


def _row_label_value(row: Mapping[str, Any]) -> tuple[str, str]:
    metadata = _row_metadata(row)
    label = str(metadata.get("label") or "").strip()
    value = str(metadata.get("value") or "").strip()
    return label, value


def _row_values(row: Mapping[str, Any]) -> Mapping[str, str]:
    metadata = _row_metadata(row)
    values = metadata.get("row_values")
    if isinstance(values, Mapping):
        return {str(key): str(value).strip() for key, value in values.items() if str(key).strip() and str(value).strip()}
    return {}


def _normalize_label(text: str) -> str:
    return " ".join(str(text or "").strip().lower().replace("/", " ").replace("_", " ").split())


def _target_claim_hints(packet: Mapping[str, Any]) -> tuple[str, ...]:
    raw = packet.get("target_claim_family_names", ())
    hints: list[str] = [str(item).strip() for item in _as_tuple_of_str(raw) if str(item).strip() in _DIRECT_CLAIM_FAMILIES]
    for row in _span_rows(packet):
        metadata = _row_metadata(row)
        extra = metadata.get("target_claim_family_hints", ())
        for item in _as_tuple_of_str(extra):
            if item in _DIRECT_CLAIM_FAMILIES and item not in hints:
                hints.append(item)
    return tuple(hints)


def _clean_company_name(text: str) -> str:
    cleaned = _collapse_text(text)
    cleaned = re.sub(r'\s*\(\s*(?:the\s+)?"?customer"?\s*\)\s*', " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*\(\s*(?:the\s+)?"?(?:vendor|provider|purtera)"?\s*\)\s*', " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^\s*(?:customer|end user|client)\s*:\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip(" 	-–—,.;:")
    return _collapse_text(cleaned)


def _looks_like_company_name(text: str) -> bool:
    clean = _clean_company_name(text)
    if not clean:
        return False
    if len(clean) > 120:
        return False
    lower = clean.lower()
    stop_phrases = (
        " shall ",
        " may ",
        " must ",
        " should ",
        " will ",
        " during ",
        " through ",
        " approval",
        " path",
        " requirements",
        " requirement",
        " platform",
        " platforms",
        " application",
        " applications",
        " support ",
        " resource",
        " onboarding",
        " transition",
        " pricing",
        " scoping",
        " discovery",
        " escalation",
        " designated",
        " customer-specific",
    )
    if any(phrase in f" {lower} " for phrase in stop_phrases):
        return False
    tokens = re.findall(r"[A-Za-z0-9&'.-]+", clean)
    if len(tokens) < 2:
        return False
    designators = {"llc", "inc", "corp", "corporation", "ltd", "lp", "llp", "pllc", "co", "company", "group", "partners"}
    uppercase_like = sum(1 for token in tokens if token[:1].isupper() or token.lower() in designators or "&" in token)
    if uppercase_like < 2:
        return False
    lowercase_ratio = sum(1 for token in tokens if token.islower()) / max(1, len(tokens))
    if lowercase_ratio > 0.5 and not any(token.lower() in designators or "&" in token for token in tokens):
        return False
    return True


def _extract_company_name(text: str) -> str:
    clean = str(text or "").strip()
    if not clean:
        return ""
    candidates: list[str] = []
    label_match = re.search(r"^\s*(?:customer|end user|client)\s*:\s*(.+)$", clean, flags=re.IGNORECASE)
    if label_match:
        candidates.append(_clean_company_name(label_match.group(1)))
    between_match = re.search(
        r"between\s+(.+?)\s+and\s+(?:purtera|vendor|provider)",
        clean,
        flags=re.IGNORECASE,
    )
    if between_match:
        candidates.append(_clean_company_name(between_match.group(1)))
    for_match = re.search(r"for\s+(.+?)\s+to\s+perform", clean, flags=re.IGNORECASE)
    if for_match:
        candidates.append(_clean_company_name(for_match.group(1)))
    for candidate in candidates:
        if _looks_like_company_name(candidate):
            return candidate
    return ""

def _word_number(text: str) -> str:
    token = _normalize_label(text)
    if token in _NUMBER_WORDS:
        return str(_NUMBER_WORDS[token])
    return ""


def _extract_site_count(text: str) -> str:
    clean = _collapse_text(text)
    if not clean:
        return ""
    explicit = re.search(r"\b(\d{1,4})\b\s*(?:customer\s+)?(?:sites?|locations?|offices?|branches?)\b", clean, flags=re.IGNORECASE)
    if explicit:
        return explicit.group(1)
    paren = re.search(r"\b([a-z]+)\s*\((\d{1,4})\)\s*(?:customer\s+)?(?:sites?|locations?|offices?|branches?)\b", clean, flags=re.IGNORECASE)
    if paren:
        return paren.group(2)
    label_match = re.search(r"(?:site count|qty of sites|number of sites|total sites)\s*[:\-]\s*(\d{1,4})", clean, flags=re.IGNORECASE)
    if label_match:
        return label_match.group(1)
    word_match = re.search(r"\b([a-z]+)-location\b", clean, flags=re.IGNORECASE)
    if word_match:
        return _word_number(word_match.group(1))
    word_match = re.search(r"\b([a-z]+)\s+(?:customer\s+)?(?:sites?|locations?|offices?|branches?)\b", clean, flags=re.IGNORECASE)
    if word_match:
        return _word_number(word_match.group(1))
    return ""


def _extract_quantity_phrase(text: str) -> str:
    clean = _collapse_text(text)
    if not clean:
        return ""
    label_match = re.search(
        r"(?:project duration(?: \(months\))?|duration|term|qty of sites|number of sites|site count|unit sell quantity)\s*[:\-]\s*(.+)$",
        clean,
        flags=re.IGNORECASE,
    )
    if label_match:
        clean = _collapse_text(label_match.group(1))
    match = _QUANTITY_PHRASE_FLEX_RE.search(clean)
    if match:
        quantity = _collapse_text(match.group(0)).rstrip(".;")
        quantity = re.sub(r"\bcustomer\s+", "", quantity, flags=re.IGNORECASE)
        return quantity
    site_count = _extract_site_count(clean)
    if site_count:
        if any(token in clean.lower() for token in ("site", "location", "office", "branch")):
            return f"{site_count} sites"
        return site_count
    return ""


def _extract_pricing_phrase(text: str) -> str:
    clean = _collapse_text(text)
    if not clean:
        return ""
    label_match = re.search(r"(?:billing type|pricing model|commercial structure)\s*[:\-]\s*(.+)$", clean, flags=re.IGNORECASE)
    if label_match:
        clean = _collapse_text(label_match.group(1)).rstrip(".;")
    lower = clean.lower()
    if "fixed fee" in lower and "month" in lower:
        return "Fixed Fee - Monthly Billing"
    if "time and materials" in lower or re.search(r"t&m", lower):
        return "Time and Materials"
    if "monthly in arrears" in lower or "billed monthly" in lower or "monthly billing" in lower:
        return "Monthly Billing"
    phrase_match = re.search(
        r"(?:fixed fee|time and materials|t&m|monthly billing|billed monthly|monthly in arrears)",
        clean,
        flags=re.IGNORECASE,
    )
    if phrase_match:
        return _collapse_text(phrase_match.group(0)).rstrip(".;")
    return ""

def _condense_project_summary(text: str) -> str:
    clean = _collapse_text(text)
    if not clean:
        return ""
    pieces = re.split(r"(?<=[.!?])\s+", clean)
    summary = " ".join(piece.strip() for piece in pieces[:2] if piece.strip())
    summary = summary[:420].rstrip()
    return summary.rstrip(";")


def _summary_from_row_values(values: Mapping[str, str]) -> str:
    normalized = {_normalize_label(key): str(value).strip() for key, value in values.items() if str(value).strip()}
    job = normalized.get("job description") or normalized.get("scope") or normalized.get("description")
    site = normalized.get("site") or normalized.get("site name") or normalized.get("location")
    billing = normalized.get("billing type") or normalized.get("billing")
    quantity = normalized.get("unit sell quantity") or normalized.get("quantity") or normalized.get("qty")
    rate_type = normalized.get("labor rate type") or normalized.get("labor rate type (if applicable)") or normalized.get("rate type")
    if not job:
        return ""
    cleaned_job = re.sub(r"\s*-\s*labor\b", "", job, flags=re.IGNORECASE).strip()
    parts = [cleaned_job]
    if site:
        parts.append(f"at {site}")
    if quantity:
        unit_text = quantity
        if rate_type:
            lowered = rate_type.lower()
            if "month" in lowered:
                unit_text = f"{quantity} months"
            elif "week" in lowered:
                unit_text = f"{quantity} weeks"
        parts.append(f"for {unit_text}")
    if billing:
        parts.append(f"under {billing}")
    return _collapse_text(" ".join(parts))


def _normalized_row_values(values: Mapping[str, str]) -> Mapping[str, str]:
    return {_normalize_label(key): str(value).strip() for key, value in values.items() if str(value).strip()}


def _contains_internal_fallback_markers(text: str) -> bool:
    lower = _collapse_text(text).lower()
    if not lower:
        return False
    return any(token in lower for token in ("anchor=", "supports=", "span:", "packet:", "claim:"))


def _normalize_site_candidate(text: str) -> str:
    candidate = _collapse_text(text)
    candidate = re.sub(r"^(?:the|a|an)\s+", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(
        r",\s*(?:[A-Z]{2}|[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)\b(?=\s+(?:HQ|headquarters|office|branch|campus|warehouse|datacenter|data center)\b)",
        "",
        candidate,
    )
    return _collapse_text(candidate).strip(" -–—,.;:")


def _looks_like_contact_header_text(text: str, normalized_values: Mapping[str, str] | None = None) -> bool:
    clean = _collapse_text(text)
    if not clean:
        return False
    lower = clean.lower()
    if any(token in lower for token in ("signature:", "agreed by", "services by")):
        return True
    if "name:" in lower and "date:" in lower and "@" not in clean:
        return True
    tokens = {_normalize_label(part.strip(" :")) for part in re.split(r"[|\n]", clean) if part.strip()}
    tokens.discard("")
    if tokens and tokens.issubset(_CONTACT_HEADER_TOKENS):
        return True
    if normalized_values:
        keys = {_normalize_label(key) for key in normalized_values}
        vals = {_normalize_label(value) for value in normalized_values.values()}
        if keys and keys.issubset(_CONTACT_HEADER_TOKENS) and vals and vals.issubset(_CONTACT_HEADER_TOKENS):
            return True
    return False


def _looks_like_personish_name(text: str) -> bool:
    clean = _collapse_text(text)
    if not clean:
        return False
    tokens = [token for token in re.findall(r"[A-Za-z][A-Za-z'.-]+", clean) if token]
    if len(tokens) < 2 or len(tokens) > 5:
        return False
    if any(token.lower() in _COMPANY_SUFFIX_TOKENS for token in tokens):
        return False
    titled = sum(1 for token in tokens if token[:1].isupper())
    return titled >= 2


def _looks_like_specific_site_candidate(text: str) -> bool:
    clean = _normalize_site_candidate(text)
    if not clean:
        return False
    lower = clean.lower()
    if _contains_internal_fallback_markers(clean):
        return False
    if any(token in lower for token in (
        "customer locations",
        "supported locations",
        "remaining locations",
        "other customer locations",
        "other locations",
        "service location",
        "work location",
        "broader environment",
    )):
        return False
    if re.fullmatch(r"\d+\s*(?:sites?|locations?)", lower):
        return False
    if len(clean.split()) > 8:
        return False
    if not any(ch.isalpha() for ch in clean):
        return False
    return any(ch.isupper() for ch in clean)


def _extract_canonical_site_location(text: str) -> str:
    clean = _collapse_text(text)
    if not clean or _contains_internal_fallback_markers(clean):
        return ""
    label_match = _SITE_LABEL_CAPTURE_RE.search(clean)
    if label_match:
        candidate = _normalize_site_candidate(label_match.group(1).strip(" -–—,.;:"))
        if _looks_like_specific_site_candidate(candidate):
            return candidate
    for pattern in (_SITE_ENTITY_CAPTURE_RE, _SITE_PREPOSITION_CAPTURE_RE):
        for match in pattern.finditer(clean):
            candidate = _normalize_site_candidate(match.group(1).strip(" -–—,.;:"))
            if _looks_like_specific_site_candidate(candidate):
                return candidate
    if _GENERIC_SITE_CONTEXT_RE.search(clean):
        return ""
    return ""


def _extract_contact_blob(text: str) -> str:
    clean = _collapse_text(text)
    if not clean or _looks_like_contact_header_text(clean):
        return ""
    lower = clean.lower()
    if "@" in clean or "|" in clean or "contact" in lower:
        return clean.rstrip(".;")
    parts = [part.strip() for part in re.split(r"\s+-\s+|\s+\|\s+", clean) if part.strip()]
    if parts and _looks_like_personish_name(parts[0]) and (len(parts) >= 2 or any(token in lower for token in _CONTACT_ROLE_TOKENS)):
        return clean.rstrip(".;")
    if _looks_like_personish_name(clean) and any(token in lower for token in _CONTACT_ROLE_TOKENS):
        return clean.rstrip(".;")
    return ""


def _claim_value_for_row(row: Mapping[str, Any], claim_family: str) -> str:
    text = str(row.get("text") or row.get("normalized_text") or "").strip()
    label, value = _row_label_value(row)
    values = _row_values(row)
    section_tokens = _section_tokens(row)

    if claim_family == "customer_identity":
        if label and value and any(token in _normalize_label(label) for token in ("customer", "end user", "client")):
            resolved = _extract_company_name(f"{label}: {value}")
            if resolved and _looks_like_company_name(resolved):
                return resolved
            return ""
        if values:
            for key, candidate in values.items():
                if any(token in _normalize_label(key) for token in ("customer", "end user", "client")):
                    resolved = _extract_company_name(f"{key}: {candidate}")
                    if resolved and _looks_like_company_name(resolved):
                        return resolved
            return ""
        resolved = _extract_company_name(text)
        if resolved and _looks_like_company_name(resolved):
            return resolved
        return ""

    if claim_family == "project_summary":
        lower_text = _collapse_text(text).lower()
        if any(token in lower_text for token in ("entered into by and between", "governing agreement", "earlier terminated in accordance", "sow version")):
            return ""
        if values:
            summary = _summary_from_row_values(values)
            if summary:
                return summary
        if label and value and "project summary" in _normalize_label(label):
            return _condense_project_summary(value)
        if any(token in " | ".join(section_tokens) for token in ("project overview", "executive summary")):
            return _condense_project_summary(text)
        if len(text) >= 90 and not _row_is_heading(row):
            return _condense_project_summary(text)
        return ""

    if claim_family == "site_count_claim":
        if label and value and any(token in _normalize_label(label) for token in ("site count", "qty of sites", "number of sites", "total sites", "locations")):
            return _extract_site_count(f"{label}: {value}")
        if values:
            for key, candidate in values.items():
                if any(token in _normalize_label(key) for token in ("site count", "qty of sites", "number of sites", "total sites", "locations")):
                    resolved = _extract_site_count(f"{key}: {candidate}")
                    if resolved:
                        return resolved
        return _extract_site_count(text)

    if claim_family == "commercial_structure_claim":
        if label and value and any(token in _normalize_label(label) for token in ("billing type", "billing", "pricing model", "commercial structure")):
            return _extract_pricing_phrase(f"{label}: {value}")
        if values:
            for key, candidate in values.items():
                if any(token in _normalize_label(key) for token in ("billing type", "billing", "pricing model", "commercial structure")):
                    resolved = _extract_pricing_phrase(f"{key}: {candidate}")
                    if resolved:
                        return resolved
        return _extract_pricing_phrase(text)

    if claim_family == "contact_claim":
        normalized_values = _normalized_row_values(values)
        if _looks_like_contact_header_text(text, normalized_values):
            return ""
        if label and value:
            candidate = _extract_contact_blob(f"{label}: {value}")
            if candidate:
                return candidate
        if normalized_values:
            name = normalized_values.get("full name") or normalized_values.get("name") or normalized_values.get("contact") or normalized_values.get("primary contact")
            email = normalized_values.get("email") or normalized_values.get("email address")
            title = normalized_values.get("title") or normalized_values.get("job title")
            phone = normalized_values.get("phone") or normalized_values.get("phone number")
            parts = [part for part in (name, title, email, phone) if part]
            if parts:
                candidate = _extract_contact_blob(" - ".join(parts))
                if candidate:
                    return candidate
        candidate = _extract_contact_blob(text)
        if candidate:
            return candidate
        return ""

    return ""


def _score_direct_claim_row(row: Mapping[str, Any], claim_family: str) -> float:
    score = 0.0
    label, value = _row_label_value(row)
    values = _row_values(row)
    text = str(row.get("text") or row.get("normalized_text") or "").strip()
    lower = text.lower()
    kind = _row_kind(row)
    section_tokens = _section_tokens(row)
    metadata = _row_metadata(row)
    hints = {str(item).strip() for item in _as_tuple_of_str(metadata.get("target_claim_family_hints", ())) }

    if claim_family in hints:
        score += 2.8
    if kind in {"spreadsheet_kv", "spreadsheet_fact"}:
        score += 1.4
    elif kind == "spreadsheet_row":
        score += 1.2
    elif kind == "paragraph":
        score += 0.8
    elif kind == "table_row":
        score += 0.6
    if claim_family == "customer_identity":
        label_norm = _normalize_label(label)
        resolved_company = _claim_value_for_row(row, claim_family)
        if any(token in label_norm for token in ("customer", "end user", "client")) and resolved_company:
            score += 3.0
        if "between" in lower and "customer" in lower and resolved_company:
            score += 2.4
        if resolved_company:
            score += 2.4
        if resolved_company and ("," in resolved_company or "&" in resolved_company):
            score += 0.8
    elif claim_family == "project_summary":
        if any(token in lower for token in ("entered into by and between", "governing agreement", "earlier terminated in accordance", "sow version")):
            score -= 6.0
        if any(token in " | ".join(section_tokens) for token in ("project overview", "executive summary")):
            score += 3.2
        if any(token in " | ".join(section_tokens) for token in ("project overview",)):
            score += 1.6
        if len(text) >= 100 and not _row_is_heading(row):
            score += 1.6
        if values and any(_normalize_label(key) in {"job description", "scope", "description"} for key in values):
            score += 2.0
    elif claim_family == "site_count_claim":
        if _extract_site_count(text):
            score += 3.0
        if label and any(token in _normalize_label(label) for token in ("site count", "qty of sites", "number of sites", "total sites", "locations")):
            score += 2.5
    elif claim_family == "commercial_structure_claim":
        if _extract_pricing_phrase(text):
            score += 3.0
        if label and any(token in _normalize_label(label) for token in ("billing type", "billing", "pricing model", "commercial structure")):
            score += 1.8
        if any(token in " | ".join(section_tokens) for token in ("pricing", "payment", "commercial")):
            score += 0.9
    elif claim_family == "contact_claim":
        normalized_values = _normalized_row_values(values)
        if _looks_like_contact_header_text(text, normalized_values):
            score -= 5.0
        contact_scope = str(metadata.get("contact_scope") or "").strip().lower()
        if contact_scope == "customer":
            score += 3.2
        elif contact_scope in {"vendor", "sales", "purtera"}:
            score -= 4.8
        if "@" in text:
            score += 2.2
        if label and any(token in _normalize_label(label) for token in ("contact", "email", "phone", "title", "name")):
            score += 1.8
        if normalized_values:
            if any(key in normalized_values for key in ("full name", "name", "contact", "primary contact")):
                score += 1.5
            if any(key in normalized_values for key in ("email", "email address")):
                score += 1.4
            if any(key in normalized_values for key in ("title", "job title")):
                score += 0.9
            if any(key in normalized_values for key in ("phone", "phone number")):
                score += 0.5
        candidate_contact = _claim_value_for_row(row, claim_family)
        if candidate_contact and _looks_like_personish_name(candidate_contact.split(" - ", 1)[0]):
            score += 0.9
    authority = row.get("authority_score")
    if isinstance(authority, (int, float)):
        score += min(0.4, float(authority) * 0.25)
    if _row_is_low_signal_section(row) and claim_family not in {"commercial_structure_claim", "contact_claim"}:
        score -= 2.2
    return score


def _select_direct_claim_choice(packet: Mapping[str, Any], claim_family: str) -> _DirectClaimChoice | None:
    best: _DirectClaimChoice | None = None
    for row in _span_rows(packet):
        claim_body = _claim_value_for_row(row, claim_family)
        if not claim_body:
            continue
        score = _score_direct_claim_row(row, claim_family)
        if claim_family == "project_summary" and len(claim_body) < 24:
            score -= 1.0
        if claim_family == "contact_claim" and "@" not in claim_body and len(claim_body.split()) < 2:
            score -= 1.2
        candidate = _DirectClaimChoice(row=row, claim_family=claim_family, claim_body=claim_body, score=score)
        if best is None or candidate.score > best.score:
            best = candidate
    threshold = 2.6
    if claim_family == "project_summary":
        threshold = 4.0
    return best if best is not None and best.score >= threshold else None


def _select_semantic_span(packet: Mapping[str, Any], packet_family: str) -> _SemanticSpanChoice | None:
    rows = _span_rows(packet)
    if not rows:
        return None
    primary_span_id = str(packet.get("primary_span_id") or "").strip() or None
    scored = [
        _SemanticSpanChoice(
            row=row,
            packet_family=packet_family,
            score=_score_row_for_family(row, packet_family, primary_span_id),
        )
        for row in rows
    ]
    scored.sort(
        key=lambda item: (
            -item.score,
            0 if str(item.row.get("span_id", "")) == (primary_span_id or "") else 1,
            str(item.row.get("span_id", "")),
        )
    )
    if not scored:
        return None
    winner = scored[0]
    if _row_is_heading(winner.row):
        for candidate in scored[1:]:
            if candidate.score <= 0.0:
                continue
            if _row_has_claim_override(candidate.row, packet_family):
                winner = candidate
                break
            if not _row_is_heading(candidate.row) and candidate.score >= max(0.2, winner.score - 1.6):
                winner = candidate
                break
    if winner.score <= 0.0:
        return None
    return winner


def _row_is_heading(row: Mapping[str, Any]) -> bool:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    kind = str(metadata.get("kind") or row.get("kind") or "").strip().lower()
    return kind in {"heading", "section_title", "pdf_heading"}


def _row_has_claim_override(row: Mapping[str, Any], packet_family: str) -> bool:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    overrides = metadata.get("claim_body_overrides", {}) if isinstance(metadata, Mapping) else {}
    if not isinstance(overrides, Mapping):
        return False
    return bool(str(overrides.get(packet_family, "")).strip())


def _row_is_low_signal_section(row: Mapping[str, Any]) -> bool:
    section_tokens = _section_tokens(row)
    return any(any(low in token for low in _LOW_SIGNAL_SECTION_TOKENS) for token in section_tokens)


def _minimum_semantic_score(packet_family: str) -> float:
    if packet_family == "quantity_packet":
        return 4.0
    if packet_family == "site_packet":
        return 7.5
    if packet_family == "schedule_packet":
        return 2.8
    if packet_family in {"assumption_packet", "responsibility_packet", "deliverable_packet", "dependency_packet"}:
        return 2.0
    return 1.0


def _row_has_explicit_family_signal(row: Mapping[str, Any], packet_family: str) -> bool:
    text = _collapse_text(str(row.get("text") or row.get("normalized_text") or ""))
    lower = text.lower()
    if _row_has_claim_override(row, packet_family):
        return True
    if packet_family == "quantity_packet":
        return bool(_extract_quantity_phrase(text))
    if packet_family == "site_packet":
        return bool(_extract_canonical_site_location(text))
    if packet_family == "schedule_packet":
        return bool(_SCHEDULE_PHRASE_RE.search(text))
    if packet_family == "assumption_packet":
        return bool(_ASSUMPTION_SIGNAL_RE.search(text))
    if packet_family == "deliverable_packet":
        return bool(_DELIVERABLE_SIGNAL_RE.search(text) or _row_kind(row) in {"bullet", "list_item", "spreadsheet_fact", "spreadsheet_kv"})
    if packet_family == "responsibility_packet":
        section_text = " | ".join(_section_tokens(row))
        if "customer responsibilities" in section_text and _RESPONSIBILITY_ACTION_RE.search(text):
            return True
        if re.search(r"^(?:customer|client)\b", lower) and _RESPONSIBILITY_ACTION_RE.search(text):
            return True
        if re.search(r"\bdesignate\b", lower) and re.search(r"\bcustomer\b", lower):
            return True
        if re.search(r"\bprovide\b", lower) and re.search(r"\btimely access|workspace|permissions|connectivity|documentation\b", lower):
            return True
        return False
    if packet_family == "scope_packet":
        return bool(_SCOPE_SIGNAL_RE.search(text))
    if packet_family == "risk_packet":
        return any(token in lower for token in _FAMILY_SIGNAL_TOKENS.get(packet_family, ()))
    if packet_family == "dependency_packet":
        return any(token in lower for token in _FAMILY_SIGNAL_TOKENS.get(packet_family, ()))
    if packet_family == "open_question_packet":
        return text.endswith("?") or "open question" in lower or "tbd" in lower
    return False


def _schedule_semantic_class(text: str, row: Mapping[str, Any]) -> str:
    lower = _collapse_text(text).lower()
    if not lower:
        return "unspecified_schedule"
    section_text = " | ".join(_section_tokens(row)).lower()
    if _SCHEDULE_COMMERCIAL_RE.search(lower):
        return "commercial_billing_cadence"
    if _SCHEDULE_OPERATIONAL_CONSTRAINT_RE.search(lower) or "constraints" in section_text:
        return "operational_constraint"
    if _SCHEDULE_COVERAGE_WINDOW_RE.search(lower):
        return "coverage_window"
    if _SCHEDULE_TRUE_COMMITMENT_RE.search(lower):
        return "true_schedule_commitment"
    if _SCHEDULE_ENGAGEMENT_TERM_RE.search(lower):
        return "engagement_term"
    return "unspecified_schedule"


def _target_family_hint_allowed(
    packet: Mapping[str, Any],
    *,
    assigned_family: str,
    target_packet_family: str,
    semantic_choice: _SemanticSpanChoice | None,
) -> bool:
    if semantic_choice is None:
        return False
    row = semantic_choice.row
    text = str(row.get("text") or row.get("normalized_text") or "")
    explicit_signal = _row_has_explicit_family_signal(row, target_packet_family)
    section_primary = _section_primary_family(_section_tokens(row))
    strong_assumption_open = bool(_ASSUMPTION_STRONG_OPEN_RE.search(_collapse_text(text)))

    if target_packet_family == "assumption_packet":
        return section_primary == "assumption_packet" or strong_assumption_open

    if target_packet_family == "scope_packet":
        if assigned_family in {"schedule_packet", "responsibility_packet", "risk_packet", "dependency_packet", "assumption_packet", "exclusion_packet"}:
            return False
        if section_primary in {"schedule_packet", "assumption_packet", "responsibility_packet"} and not explicit_signal:
            return False
        schedule_class = _schedule_semantic_class(text, row)
        if schedule_class in {"true_schedule_commitment", "engagement_term", "coverage_window", "operational_constraint", "commercial_billing_cadence"}:
            return False

    if target_packet_family == "schedule_packet":
        schedule_class = _schedule_semantic_class(text, row)
        if schedule_class in {"operational_constraint", "commercial_billing_cadence"}:
            return False

    return True


def _guardrail_diagnostic(
    packet: Mapping[str, Any],
    *,
    packet_family: str,
    semantic_choice: _SemanticSpanChoice | None,
    source_reason: str = "assigned_packet_family",
) -> ExtractionDiagnostic | None:
    if semantic_choice is None:
        return None
    row = semantic_choice.row
    text = _collapse_text(str(row.get("text") or row.get("normalized_text") or ""))
    section_primary = _section_primary_family(_section_tokens(row))
    explicit_signal = _row_has_explicit_family_signal(row, packet_family)
    schedule_class = _schedule_semantic_class(text, row) if packet_family == "schedule_packet" else None
    packet_id = str(packet.get("packet_id") or "")

    def _diag(code: str, message: str) -> ExtractionDiagnostic:
        return ExtractionDiagnostic(
            code=code,
            message=message,
            packet_id=packet_id,
            metadata={
                "packet_family": packet_family,
                "semantic_source_span_id": str(row.get("span_id", "")).strip(),
                "section_path": list(_section_tokens(row)),
            },
        )

    if packet_family == "responsibility_packet":
        section_text = " | ".join(_section_tokens(row))
        if "purtera responsibilities" in section_text or text.lower().startswith("purtera "):
            return _diag(
                "responsibility_subject_mismatch",
                "Customer responsibility claims were suppressed because the source span described vendor responsibilities instead.",
            )
        if not explicit_signal:
            return _diag(
                "responsibility_signal_too_weak",
                "Customer responsibility claims require an explicit customer action or a dedicated responsibility section.",
            )
    if packet_family == "assumption_packet" and section_primary != "assumption_packet" and not explicit_signal:
        return _diag(
            "assumption_signal_too_weak",
            "Assumption claims were suppressed because the source text did not contain explicit assumption language.",
        )
    if packet_family == "assumption_packet" and source_reason == "target_claim_family_hint" and section_primary != "assumption_packet" and not _ASSUMPTION_STRONG_OPEN_RE.search(text):
        return _diag(
            "assumption_cross_family_suppressed",
            "Assumption claims were suppressed because they were inferred from a conflicting packet family rather than explicit assumption evidence.",
        )
    if packet_family == "assumption_packet":
        lower = text.lower()
        if lower.startswith("this project services statement of work") or lower.startswith("this sow is entered into"):
            return _diag(
                "assumption_signal_too_weak",
                "Assumption claims were suppressed because the source span was introductory contract boilerplate rather than an operational assumption.",
            )
        if lower.startswith("the customer shall not direct") or "payment obligations" in lower:
            return _diag(
                "assumption_signal_too_weak",
                "Assumption claims were suppressed because the source span described commercial or behavioral guardrails rather than an operational assumption.",
            )
    if packet_family == "deliverable_packet":
        if section_primary != "deliverable_packet" and not explicit_signal:
            return _diag(
                "deliverable_signal_too_weak",
                "Deliverable claims were suppressed because the source span did not look like a concrete deliverable.",
            )
    if packet_family == "scope_packet":
        section_text = " | ".join(_section_tokens(row)).lower()
        schedule_class = _schedule_semantic_class(text, row)
        if re.search(r"\bthird[-\s]*party dependenc|fall outside the defined scope|escalation path\b", text, flags=re.IGNORECASE):
            return _diag(
                "scope_signal_too_weak",
                "Scope claims were suppressed because the source span described escalation or dependency handling rather than included work.",
            )
        if source_reason == "target_claim_family_hint" and schedule_class in {"true_schedule_commitment", "engagement_term", "coverage_window", "operational_constraint", "commercial_billing_cadence"}:
            return _diag(
                "scope_cross_family_suppressed",
                "Scope claims were suppressed because the source span was schedule-like evidence from a conflicting packet cluster.",
            )
        if _GENERIC_SCOPE_HEADING_RE.match(text):
            return _diag(
                "scope_signal_too_weak",
                "Scope claims were suppressed because the source span was a generic section heading without concrete scope content.",
            )
        if section_primary == "exclusion_packet" or re.search(r"\bout[-\s]*of[-\s]*scope\b", text, flags=re.IGNORECASE):
            return _diag(
                "scope_signal_too_weak",
                "Scope claims were suppressed because the source span described excluded work rather than included scope.",
            )
        if section_primary == "responsibility_packet":
            return _diag(
                "scope_signal_too_weak",
                "Scope claims were suppressed because the source span belonged to a customer-responsibility section.",
            )
        if section_primary == "assumption_packet" and (
            _ASSUMPTION_SIGNAL_RE.search(text)
            or text.lower().startswith((
                "this engagement is based on",
                "pricing and staffing under this sow",
                "customer shall be invoiced",
                "delays caused by",
                "requests for recurring after-hours",
                "the customer shall not direct",
            ))
        ):
            return _diag(
                "scope_signal_too_weak",
                "Scope claims were suppressed because the source span reflected assumptions or commercial guardrails rather than included work.",
            )
        if "project overview" in section_text and (len(text) > 240 or "purpose of this engagement" in text.lower()):
            return _diag(
                "scope_signal_too_weak",
                "Scope claims were suppressed because the source span was a long narrative summary that is better handled as project summary context.",
            )
        if section_primary in {"assumption_packet", "schedule_packet", "responsibility_packet", "deliverable_packet"} and not explicit_signal:
            return _diag(
                "scope_signal_too_weak",
                "Scope claims were suppressed because the source span belonged to a conflicting narrative section without strong scope language.",
            )
    if packet_family == "quantity_packet" and not explicit_signal:
        return _diag(
            "quantity_signal_too_weak",
            "Quantity claims were suppressed because the source span did not resolve to a structured quantity phrase.",
        )
    if packet_family == "schedule_packet":
        lower = text.lower()
        section_text = " | ".join(_section_tokens(row)).lower()
        if any(token in lower for token in ("revision history", "quoted by", "sow version")):
            return _diag(
                "schedule_signal_too_weak",
                "Schedule claims were suppressed because the source span looked like document metadata rather than schedule content.",
            )
        if (
            "constraints" in section_text or section_primary == "assumption_packet"
        ) and not explicit_signal:
            return _diag(
                "schedule_signal_too_weak",
                "Schedule claims were suppressed because the source span came from assumptions or constraints without a concrete schedule anchor.",
            )
        if any(
            token in lower
            for token in (
                "payment obligations",
                "support environment, user population, site profile",
                "reasonable-efforts basis",
                "subject to resource availability",
                "separate coverage model",
                "not based on ticket count",
                "fee adjustment",
                "outside scope unless approved",
                "change order",
            )
        ) and not any(
            token in lower
            for token in (
                "planned service commencement",
                "initial term",
                "transition period",
                "service window",
                "support coverage window",
                "weekday operating schedule",
                "12 months",
                "one (1) year",
            )
        ):
            return _diag(
                "schedule_semantic_suppressed",
                "Schedule claims were suppressed because the source span described operational constraints rather than a concrete schedule commitment.",
            )
        if schedule_class in {"operational_constraint", "commercial_billing_cadence"}:
            return _diag(
                "schedule_semantic_suppressed",
                "Schedule claims were suppressed because the source span described operational or billing cadence language rather than a project schedule commitment.",
            )
    return None


def _strip_leading_patterns(text: str, packet_family: str) -> str:
    cleaned = text.strip()
    for pattern in _FAMILY_CLEANUP_PATTERNS.get(packet_family, ()):
        cleaned = pattern.sub("", cleaned).strip()
    cleaned = re.sub(r"^(?:is|are|to)\s+", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned


def _collapse_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip("-•* \t")
    text = re.sub(r"\s+([,.;:?!])", r"\1", text)
    return text


def _family_specific_cleanup(text: str, packet_family: str) -> str:
    cleaned = _collapse_text(_strip_leading_patterns(text, packet_family))
    if packet_family == "quantity_packet":
        quantity_phrase = _extract_quantity_phrase(cleaned)
        if quantity_phrase:
            cleaned = quantity_phrase
    if packet_family == "site_packet":
        cleaned = _extract_canonical_site_location(cleaned)
    if packet_family == "open_question_packet":
        cleaned = cleaned.rstrip(".")
        if cleaned and not cleaned.endswith("?"):
            cleaned += "?"
    else:
        cleaned = cleaned.rstrip(";:,. ")
    return cleaned.strip()


def _build_claim_body(packet_family: str, packet: Mapping[str, Any], semantic_choice: _SemanticSpanChoice | None) -> str:
    if semantic_choice is not None:
        row_metadata = semantic_choice.row.get("metadata") if isinstance(semantic_choice.row.get("metadata"), Mapping) else {}
        claim_body_overrides = row_metadata.get("claim_body_overrides", {}) if isinstance(row_metadata, Mapping) else {}
        if isinstance(claim_body_overrides, Mapping):
            override_text = str(claim_body_overrides.get(packet_family, "")).strip()
            cleaned_override = _family_specific_cleanup(override_text, packet_family) if override_text else ""
            if cleaned_override:
                return cleaned_override
        text = str(semantic_choice.row.get("text") or semantic_choice.row.get("normalized_text") or "").strip()
        cleaned = _family_specific_cleanup(text, packet_family)
        if cleaned:
            return cleaned
    for row in _span_rows(packet):
        if _row_is_heading(row):
            continue
        metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
        claim_body_overrides = metadata.get("claim_body_overrides", {}) if isinstance(metadata, Mapping) else {}
        if not isinstance(claim_body_overrides, Mapping):
            continue
        override_text = str(claim_body_overrides.get(packet_family, "")).strip()
        cleaned_override = _family_specific_cleanup(override_text, packet_family) if override_text else ""
        if cleaned_override:
            return cleaned_override
    metadata = _packet_metadata(packet)
    anchor_text = str(metadata.get("anchor_text", "")).strip()
    if anchor_text:
        cleaned = _family_specific_cleanup(anchor_text, packet_family)
        if cleaned:
            return cleaned
    for row in _span_rows(packet):
        if _row_is_heading(row):
            continue
        text = str(row.get("text") or row.get("normalized_text") or "").strip()
        cleaned = _family_specific_cleanup(text, packet_family)
        if cleaned:
            return cleaned
    diagnostic = metadata.get("packet_diagnostic", {}) if isinstance(metadata, Mapping) else {}
    included_count = len(diagnostic.get("included", [])) if isinstance(diagnostic, Mapping) else len(_as_tuple_of_str(packet.get("span_ids", ())))
    family = packet_family.replace("_packet", "")
    return f"{family}:anchor={packet.get('primary_span_id', '')} supports={included_count}"


def _claim_id(packet_id: str, claim_family: str, semantic_choice: _SemanticSpanChoice | None, *, suffix: str | None = None) -> str:
    parts = ["claim", packet_id, claim_family]
    if semantic_choice is not None:
        source_span_id = str(semantic_choice.row.get("span_id", "")).strip()
        if source_span_id:
            parts.append(source_span_id)
    if suffix:
        parts.append(suffix)
    return ":".join(parts)


def _build_evidence(packet: Mapping[str, Any], semantic_choice: _SemanticSpanChoice | None) -> EvidenceRefSet | None:
    span_ids = _as_tuple_of_str(packet.get("span_ids", ()))
    packet_id = str(packet.get("packet_id", "packet:unknown"))
    source_span_id = None
    if semantic_choice is not None:
        source_span_id = str(semantic_choice.row.get("span_id", "")).strip() or None
    primary_span_id = source_span_id or str(packet.get("primary_span_id") or "").strip() or None
    if primary_span_id and primary_span_id not in span_ids:
        span_ids = (primary_span_id, *span_ids)
    if not primary_span_id and span_ids:
        primary_span_id = span_ids[0]
    if not primary_span_id or not span_ids:
        return None
    support_span_ids = tuple(span for span in span_ids if span != primary_span_id)
    refs = [EvidenceRef(span_id=primary_span_id, role="anchor")]
    refs.extend(EvidenceRef(span_id=span_id, role="support") for span_id in support_span_ids)
    return EvidenceRefSet(
        packet_id=packet_id,
        primary_span_id=primary_span_id,
        supporting_span_ids=support_span_ids,
        all_span_ids=span_ids,
        refs=tuple(refs),
    )


def _build_claim(
    packet: Mapping[str, Any],
    *,
    packet_family: str,
    context: PacketExtractionContext,
    suffix: str | None = None,
    source_reason: str = "assigned_packet_family",
) -> tuple[InternalClaim | None, ExtractionDiagnostic | None]:
    claim_family = _PACKET_TO_CLAIM.get(packet_family)
    packet_id = str(packet.get("packet_id", "packet:unknown"))
    if claim_family is None:
        return (
            None,
            ExtractionDiagnostic(
                code="unsupported_packet_family",
                message="Packet family is not extractable for narrative claims.",
                packet_id=packet_id,
                metadata={"packet_family": packet_family},
            ),
        )

    semantic_choice = _select_semantic_span(packet, packet_family)
    if semantic_choice is not None and semantic_choice.score < _minimum_semantic_score(packet_family):
        return (
            None,
            ExtractionDiagnostic(
                code="semantic_signal_too_weak",
                message="Packet evidence was too weak for this claim family after bounded scoring.",
                packet_id=packet_id,
                metadata={
                    "packet_family": packet_family,
                    "semantic_source_span_id": str(semantic_choice.row.get("span_id", "")).strip(),
                    "semantic_score": semantic_choice.score,
                },
            ),
        )
    if semantic_choice is not None and _row_is_low_signal_section(semantic_choice.row) and not _row_has_claim_override(semantic_choice.row, packet_family):
        return (
            None,
            ExtractionDiagnostic(
                code="low_signal_section_suppressed",
                message="Claim was suppressed because the winning evidence span came from a low-signal legal or commercial section.",
                packet_id=packet_id,
                metadata={
                    "packet_family": packet_family,
                    "semantic_source_span_id": str(semantic_choice.row.get("span_id", "")).strip(),
                    "section_path": list(_section_tokens(semantic_choice.row)),
                },
            ),
        )
    guardrail = _guardrail_diagnostic(packet, packet_family=packet_family, semantic_choice=semantic_choice, source_reason=source_reason)
    if guardrail is not None:
        return (None, guardrail)
    evidence = _build_evidence(packet, semantic_choice)
    if evidence is None:
        return (
            None,
            ExtractionDiagnostic(
                code="packet_missing_evidence",
                message="Packet lacks evidence span ids and cannot emit a claim.",
                packet_id=packet_id,
                metadata={"packet_family": packet_family},
            ),
        )

    packet_confidence = float(packet.get("confidence", 0.0) or 0.0)
    metadata = _packet_metadata(packet)
    uncertainty_markers = _as_tuple_of_str(metadata.get("uncertainty_markers", ()))
    status, verification_needed, stronger_source_needed = _derive_status(packet_confidence, uncertainty_markers)
    claim_body = _build_claim_body(packet_family, packet, semantic_choice)
    schedule_class = None
    completion_criteria_projection_allowed = False
    if packet_family == "schedule_packet" and semantic_choice is not None:
        schedule_class = _schedule_semantic_class(str(semantic_choice.row.get("text") or semantic_choice.row.get("normalized_text") or ""), semantic_choice.row)
        completion_criteria_projection_allowed = schedule_class == "true_schedule_commitment"
    if packet_family == "site_packet":
        if _contains_internal_fallback_markers(claim_body):
            return (
                None,
                ExtractionDiagnostic(
                    code="site_location_not_specific",
                    message="Packet mentioned locations but did not resolve to a canonical site/location value.",
                    packet_id=packet_id,
                    metadata={
                        "packet_family": packet_family,
                        "semantic_source_span_id": str(semantic_choice.row.get("span_id", "")).strip() if semantic_choice is not None else "",
                    },
                ),
            )
        canonical_site = _extract_canonical_site_location(claim_body)
        if not canonical_site:
            return (
                None,
                ExtractionDiagnostic(
                    code="site_location_not_specific",
                    message="Packet mentioned locations but did not resolve to a canonical site/location value.",
                    packet_id=packet_id,
                    metadata={
                        "packet_family": packet_family,
                        "semantic_source_span_id": str(semantic_choice.row.get("span_id", "")).strip() if semantic_choice is not None else "",
                    },
                ),
            )
        claim_body = canonical_site
    claim = InternalClaim(
        claim_id=_claim_id(packet_id, claim_family, semantic_choice, suffix=suffix),
        claim_family=claim_family,
        packet_id=packet_id,
        packet_family=packet_family,
        claim_body=claim_body,
        confidence=max(0.0, min(1.0, packet_confidence)),
        status=status,
        verification_needed=verification_needed,
        stronger_source_needed=stronger_source_needed,
        evidence=evidence,
        metadata={
            "role_id": context.role_id,
            "modality": context.modality,
            "uncertainty_markers": list(uncertainty_markers),
            "source_reason": source_reason,
            "semantic_source_span_id": evidence.primary_span_id,
            "semantic_source_text": str(semantic_choice.row.get("text", "")).strip() if semantic_choice is not None else "",
            "assigned_packet_family": str(metadata.get("packet_family", "")).strip(),
            "anchor_hint_packet_family": _anchor_hint_family(packet),
            **({"schedule_semantic_class": schedule_class} if schedule_class else {}),
            **(
                {"completion_criteria_projection_allowed": completion_criteria_projection_allowed}
                if packet_family == "schedule_packet"
                else {}
            ),
        },
    )
    diagnostic: ExtractionDiagnostic | None = None
    if source_reason != "assigned_packet_family":
        diagnostic = ExtractionDiagnostic(
            code="semantic_family_override",
            message="Packet claim family was corrected using semantic evidence.",
            packet_id=packet_id,
            metadata={
                "assigned_packet_family": str(metadata.get("packet_family", "")).strip(),
                "selected_packet_family": packet_family,
                "source_reason": source_reason,
                "semantic_source_span_id": evidence.primary_span_id,
            },
        )
    return (claim, diagnostic)


def _build_direct_claim(
    packet: Mapping[str, Any],
    *,
    claim_family: str,
    context: PacketExtractionContext,
    suffix: str | None = None,
    source_reason: str = "direct_claim_hint",
) -> tuple[InternalClaim | None, ExtractionDiagnostic | None]:
    packet_id = str(packet.get("packet_id", "packet:unknown"))
    choice = _select_direct_claim_choice(packet, claim_family)
    if choice is None:
        return (
            None,
            ExtractionDiagnostic(
                code="direct_claim_signal_too_weak",
                message="Packet evidence did not support a direct semantic claim strongly enough.",
                packet_id=packet_id,
                metadata={"claim_family": claim_family},
            ),
        )
    row_metadata = choice.row.get("metadata") if isinstance(choice.row.get("metadata"), Mapping) else {}
    normalized_values = _normalized_row_values(_row_values(choice.row))
    if claim_family == "contact_claim":
        if _looks_like_contact_header_text(str(choice.row.get("text") or choice.claim_body or ""), normalized_values):
            return (
                None,
                ExtractionDiagnostic(
                    code="contact_header_suppressed",
                    message="Direct contact claim was suppressed because the source row looked like a contact-table header or signature block.",
                    packet_id=packet_id,
                    metadata={"claim_family": claim_family},
                ),
            )
        contact_scope = str(row_metadata.get("contact_scope") or "").strip().lower()
        if contact_scope and contact_scope not in {"customer", "client"}:
            return (
                None,
                ExtractionDiagnostic(
                    code="non_customer_contact_suppressed",
                    message="Direct contact claim was suppressed because the source row was not tagged as a customer contact.",
                    packet_id=packet_id,
                    metadata={"claim_family": claim_family, "contact_scope": contact_scope},
                ),
            )
    semantic_choice = _SemanticSpanChoice(
        row=choice.row,
        packet_family=str(_packet_metadata(packet).get("packet_family", "semantic_hint") or "semantic_hint"),
        score=choice.score,
    )
    evidence = _build_evidence(packet, semantic_choice)
    if evidence is None:
        return (
            None,
            ExtractionDiagnostic(
                code="packet_missing_evidence",
                message="Packet lacks evidence span ids and cannot emit a direct semantic claim.",
                packet_id=packet_id,
                metadata={"claim_family": claim_family},
            ),
        )
    packet_confidence = float(packet.get("confidence", 0.0) or 0.0)
    metadata = _packet_metadata(packet)
    uncertainty_markers = _as_tuple_of_str(metadata.get("uncertainty_markers", ()))
    status, verification_needed, stronger_source_needed = _derive_status(packet_confidence, uncertainty_markers)
    claim = InternalClaim(
        claim_id=_claim_id(packet_id, claim_family, semantic_choice, suffix=suffix),
        claim_family=claim_family,
        packet_id=packet_id,
        packet_family=str(metadata.get("packet_family", "semantic_hint") or "semantic_hint"),
        claim_body=choice.claim_body,
        confidence=max(0.0, min(1.0, packet_confidence)),
        status=status,
        verification_needed=verification_needed,
        stronger_source_needed=stronger_source_needed,
        evidence=evidence,
        metadata={
            "role_id": context.role_id,
            "modality": context.modality,
            "uncertainty_markers": list(uncertainty_markers),
            "source_reason": source_reason,
            "semantic_source_span_id": evidence.primary_span_id,
            "semantic_source_text": str(choice.row.get("text", "")).strip(),
            "assigned_packet_family": str(metadata.get("packet_family", "")).strip(),
            "anchor_hint_packet_family": _anchor_hint_family(packet),
        },
    )
    return (
        claim,
        ExtractionDiagnostic(
            code="direct_claim_extracted",
            message="Packet emitted a direct semantic claim beyond its primary packet family.",
            packet_id=packet_id,
            metadata={
                "claim_family": claim_family,
                "source_reason": source_reason,
                "semantic_source_span_id": evidence.primary_span_id,
            },
        ),
    )


def _resolved_direct_claim_families(packet: Mapping[str, Any]) -> tuple[str, ...]:
    names: list[str] = list(_target_claim_hints(packet))
    for claim_family in _DIRECT_CLAIM_FAMILIES:
        if claim_family in names:
            continue
        if _select_direct_claim_choice(packet, claim_family) is not None:
            names.append(claim_family)
    return tuple(names)


def extract_scope_from_packet(packet: Mapping[str, Any], context: PacketExtractionContext) -> tuple[InternalClaim | None, ExtractionDiagnostic | None]:
    return _build_claim(packet, packet_family="scope_packet", context=context)


def extract_exclusion_from_packet(packet: Mapping[str, Any], context: PacketExtractionContext) -> tuple[InternalClaim | None, ExtractionDiagnostic | None]:
    return _build_claim(packet, packet_family="exclusion_packet", context=context)


def extract_assumption_from_packet(packet: Mapping[str, Any], context: PacketExtractionContext) -> tuple[InternalClaim | None, ExtractionDiagnostic | None]:
    return _build_claim(packet, packet_family="assumption_packet", context=context)


def extract_risk_from_packet(packet: Mapping[str, Any], context: PacketExtractionContext) -> tuple[InternalClaim | None, ExtractionDiagnostic | None]:
    return _build_claim(packet, packet_family="risk_packet", context=context)


def extract_dependency_from_packet(packet: Mapping[str, Any], context: PacketExtractionContext) -> tuple[InternalClaim | None, ExtractionDiagnostic | None]:
    return _build_claim(packet, packet_family="dependency_packet", context=context)


def extract_deliverable_from_packet(packet: Mapping[str, Any], context: PacketExtractionContext) -> tuple[InternalClaim | None, ExtractionDiagnostic | None]:
    return _build_claim(packet, packet_family="deliverable_packet", context=context)


def extract_schedule_from_packet(packet: Mapping[str, Any], context: PacketExtractionContext) -> tuple[InternalClaim | None, ExtractionDiagnostic | None]:
    return _build_claim(packet, packet_family="schedule_packet", context=context)


def extract_responsibility_from_packet(packet: Mapping[str, Any], context: PacketExtractionContext) -> tuple[InternalClaim | None, ExtractionDiagnostic | None]:
    return _build_claim(packet, packet_family="responsibility_packet", context=context)


def extract_quantity_from_packet(packet: Mapping[str, Any], context: PacketExtractionContext) -> tuple[InternalClaim | None, ExtractionDiagnostic | None]:
    return _build_claim(packet, packet_family="quantity_packet", context=context)


def extract_site_from_packet(packet: Mapping[str, Any], context: PacketExtractionContext) -> tuple[InternalClaim | None, ExtractionDiagnostic | None]:
    return _build_claim(packet, packet_family="site_packet", context=context)


def extract_open_question_from_packet(packet: Mapping[str, Any], context: PacketExtractionContext) -> tuple[InternalClaim | None, ExtractionDiagnostic | None]:
    return _build_claim(packet, packet_family="open_question_packet", context=context)


_FAMILY_DISPATCH: dict[str, Callable[[Mapping[str, Any], PacketExtractionContext], tuple[InternalClaim | None, ExtractionDiagnostic | None]]] = {
    "scope_packet": extract_scope_from_packet,
    "exclusion_packet": extract_exclusion_from_packet,
    "assumption_packet": extract_assumption_from_packet,
    "risk_packet": extract_risk_from_packet,
    "dependency_packet": extract_dependency_from_packet,
    "deliverable_packet": extract_deliverable_from_packet,
    "schedule_packet": extract_schedule_from_packet,
    "responsibility_packet": extract_responsibility_from_packet,
    "quantity_packet": extract_quantity_from_packet,
    "site_packet": extract_site_from_packet,
    "open_question_packet": extract_open_question_from_packet,
}


def _resolved_packet_families(packet: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    metadata = _packet_metadata(packet)
    assigned = str(metadata.get("packet_family", "")).strip()
    if not assigned:
        return ()
    resolved: list[tuple[str, str]] = []
    conflict = _packet_has_family_conflict(packet)
    anchor_hint = _anchor_hint_family(packet)
    primary_family = assigned
    source_reason = "assigned_packet_family"
    if conflict and anchor_hint and anchor_hint != assigned and anchor_hint in _PACKET_TO_CLAIM:
        primary_family = anchor_hint
        source_reason = "anchor_family_hint_override"
    resolved.append((primary_family, source_reason))
    if conflict and primary_family != assigned and assigned in _PACKET_TO_CLAIM:
        semantic_choice = _select_semantic_span(packet, assigned)
        if semantic_choice is not None and semantic_choice.score >= 2.0:
            resolved.append((assigned, "companion_family_from_packet_cluster"))

    target_claim_families = _as_tuple_of_str(packet.get("target_claim_family_names", ()))
    for target_claim_family in target_claim_families:
        target_packet_family = _CLAIM_TO_PACKET_FAMILY.get(target_claim_family)
        if not target_packet_family or any(existing_family == target_packet_family for existing_family, _ in resolved):
            continue
        semantic_choice = _select_semantic_span(packet, target_packet_family)
        if not _target_family_hint_allowed(packet, assigned_family=assigned, target_packet_family=target_packet_family, semantic_choice=semantic_choice):
            continue
        min_score = 1.2
        if target_packet_family in {"quantity_packet", "site_packet"}:
            min_score = 4.0
        elif target_packet_family == "schedule_packet":
            min_score = 2.4
        if semantic_choice is not None and semantic_choice.score >= min_score:
            resolved.append((target_packet_family, "target_claim_family_hint"))
        if len(resolved) >= 4:
            break
    return tuple(resolved)


def extract_claims_from_packet(packet: Mapping[str, Any], context: PacketExtractionContext) -> tuple[tuple[InternalClaim, ...], tuple[ExtractionDiagnostic, ...]]:
    metadata = _packet_metadata(packet)
    if not isinstance(metadata, Mapping):
        return (
            (),
            (
                ExtractionDiagnostic(
                    code="packet_metadata_invalid",
                    message="Packet metadata payload is not a mapping.",
                    packet_id=str(packet.get("packet_id") or ""),
                ),
            ),
        )
    packet_family = str(metadata.get("packet_family", "")).strip()
    if packet_family in _CAD_PACKET_FAMILIES:
        return extract_cad_claims_from_packet(packet, context)
    resolved_families = _resolved_packet_families(packet)
    if not resolved_families:
        return (
            (),
            (
                ExtractionDiagnostic(
                    code="packet_family_not_supported",
                    message="Packet family is not supported by narrative extractor.",
                    packet_id=str(packet.get("packet_id") or ""),
                    metadata={"packet_family": str(metadata.get("packet_family", "")).strip()},
                ),
            ),
        )

    claims: list[InternalClaim] = []
    diagnostics: list[ExtractionDiagnostic] = []
    for idx, (packet_family, source_reason) in enumerate(resolved_families):
        extractor = _FAMILY_DISPATCH.get(packet_family)
        if extractor is None:
            diagnostics.append(
                ExtractionDiagnostic(
                    code="packet_family_not_supported",
                    message="Packet family is not supported by narrative extractor.",
                    packet_id=str(packet.get("packet_id") or ""),
                    metadata={"packet_family": packet_family},
                )
            )
            continue
        claim, diagnostic = _build_claim(
            packet,
            packet_family=packet_family,
            context=context,
            suffix=None if idx == 0 else f"variant_{idx}",
            source_reason=source_reason,
        )
        if claim is not None:
            claims.append(claim)
        if diagnostic is not None:
            diagnostics.append(diagnostic)

    emitted_claim_families = {claim.claim_family for claim in claims}
    direct_claim_families = _resolved_direct_claim_families(packet)
    for direct_idx, claim_family in enumerate(direct_claim_families):
        if claim_family in emitted_claim_families:
            continue
        claim, diagnostic = _build_direct_claim(
            packet,
            claim_family=claim_family,
            context=context,
            suffix=f"direct_{direct_idx}",
            source_reason="target_claim_family_hint" if claim_family in _target_claim_hints(packet) else "semantic_lift",
        )
        if claim is not None:
            claims.append(claim)
            emitted_claim_families.add(claim.claim_family)
        if diagnostic is not None:
            diagnostics.append(diagnostic)
    return tuple(claims), tuple(diagnostics)
