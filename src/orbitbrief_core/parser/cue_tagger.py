from __future__ import annotations

from dataclasses import replace

from orbitbrief_core.parser.shared.types import CueKind, DocumentParse

_CUE_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("included work", "in scope", "scope", "main ask", "support", "replace", "collect", "validate", "provide onsite support", "provide remote support"), "scope_included"),
    (("out of scope", "exclude", "excluded", "not included", "by others"), "scope_excluded"),
    (("by others", "low-voltage partner", "third-party vendor"), "scope_by_others"),
    (("assumption", "assuming", "unless", "will remain", "will be reused", "based on"), "assumption"),
    (("risk", "possible issue", "blocker", "delay", "compress available install windows", "older models", "escort required"), "risk"),
    (("dependenc", "depends on", "approval", "access approvals", "third party", "vendor", "carrier", "landlord"), "dependency"),
    (("deliverable", "deliverables", "runbook", "report", "checklist", "worksheet", "log", "summary", "certificate", "matrix", "sop", "punch list"), "deliverable"),
    (("acceptance", "completion criteria", "done looks like", "validated at each site", "installed or formally documented"), "acceptance"),
    (("customer responsibilities", "need from customer", "customer side", "customer furnishes", "provide", "badge access", "escort", "site contacts", "maintenance windows", "release approvals"), "customer_responsibility"),
    (("site count", "sites", "locations", "clinic", "branch", "hq", "idf", "mdf"), "site_location"),
    (("site count", "locations"), "site_count"),
    (("qty", "quantity", "quantities", "devices", "users", "printers", "aps", "switches", "idfs", "conference rooms"), "quantity"),
    (("schedule", "timeline", "date", "deadline", "wave", "window", "after-hours", "go-live", "maintenance windows"), "schedule"),
    (("open item", "open items", "open question", "still need to confirm", "confirm whether", "confirm final", "clarify", "tbd", "unknown"), "open_question"),
)

_PACKET_HINTS_BY_CUE: dict[str, tuple[str, ...]] = {
    "scope_included": ("scope_packet",),
    "scope_excluded": ("exclusion_packet",),
    "scope_by_others": ("responsibility_packet", "exclusion_packet"),
    "assumption": ("assumption_packet",),
    "risk": ("risk_packet",),
    "dependency": ("dependency_packet",),
    "deliverable": ("deliverable_packet",),
    "customer_responsibility": ("responsibility_packet",),
    "site_location": ("site_packet",),
    "site_count": ("site_packet", "quantity_packet"),
    "quantity": ("quantity_packet",),
    "schedule": ("schedule_packet",),
    "open_question": ("open_question_packet",),
}


def _cue_enums_from_text(text: str) -> tuple[CueKind, ...]:
    out: list[CueKind] = []
    lower = text.lower()
    if any(token in lower for token in ("maybe", "might", "could", "possibly", "seems", "around ")):
        out.append(CueKind.HEDGE)
    if any(token in lower for token in ("will", "commit", "agreed", "shall", "must", "need to")):
        out.append(CueKind.COMMITMENT)
    if "?" in text or any(token in lower for token in ("uncertain", "unknown", "confirm", "clarify", "tbd")):
        out.append(CueKind.UNCERTAINTY)
    if any(token in lower for token in ("not ", "no ", "without", "exclude", "out of scope")):
        out.append(CueKind.NEGATION)
    if any(ch.isdigit() for ch in text):
        out.append(CueKind.QUANTITY)
    if any(token in lower for token in ("week", "month", "date", "schedule", "timeline", "wave", "window", "after-hours", "go-live")):
        out.append(CueKind.SCHEDULE)
    return tuple(dict.fromkeys(out))


def apply_cue_tags(document_parse: DocumentParse) -> tuple[DocumentParse, tuple[str, ...]]:
    diagnostics: list[str] = []
    spans = []
    for span in document_parse.evidence_spans:
        parser_cues: list[str] = []
        packet_families: list[str] = []
        combined_text = f"{span.normalized_text} {' '.join(span.section_path)}".lower()
        for tokens, cue_name in _CUE_HINTS:
            if any(token in combined_text for token in tokens):
                parser_cues.append(cue_name)
                packet_families.extend(_PACKET_HINTS_BY_CUE.get(cue_name, ()))
        cue_enums = _cue_enums_from_text(span.text)
        if parser_cues or cue_enums:
            diagnostics.append(f"cue_tagged:{span.span_id}")
        meta = dict(span.metadata)
        if parser_cues:
            meta["parser_cues"] = sorted(set(parser_cues))
        if packet_families:
            existing = meta.get("packet_families", ())
            if isinstance(existing, (list, tuple)):
                packet_families.extend(str(item) for item in existing if str(item))
            meta["packet_families"] = sorted(set(packet_families))
        spans.append(replace(span, cue_kinds=cue_enums, metadata=meta))

    return replace(document_parse, evidence_spans=tuple(spans)), tuple(diagnostics)
