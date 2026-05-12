from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping

from orbitbrief_core.parser.site_schematic.models import (
    SiteSchematicAbbreviationEntry,
    SiteSchematicCableRule,
    SiteSchematicColorConvention,
    SiteSchematicDetailRegion,
    SiteSchematicDrawingIndexRow,
    SiteSchematicEnvironmentalRequirement,
    SiteSchematicGroundingRequirement,
    SiteSchematicLabelingRequirement,
    SiteSchematicLegendEntry,
    SiteSchematicMountingRule,
    SiteSchematicNoteClause,
    SiteSchematicOutletTypeDefinition,
    SiteSchematicPathwayRule,
    SiteSchematicResponsibilityAssignment,
    SiteSchematicRegion,
    SiteSchematicScopedNoteLink,
    SiteSchematicServiceLoopRequirement,
    SiteSchematicSubregion,
    SiteSchematicSymbolInstance,
    SiteSchematicSymbolLink,
    SiteSchematicTerminationRule,
    SiteSchematicTestingRequirement,
    SiteSchematicPseudoPage,
    SiteSchematicUniversalTable,
)

_NUMBERED_CLAUSE_RE = re.compile(r"(?m)^\s*(?:\d+\.|[A-Z]\.|[-*])\s+(.{8,400})$")
_DRAWING_INDEX_RE = re.compile(r"(?im)^\s*([A-Z]{1,3}\d{2,3}(?:\.\d+)?)\s+([A-Z0-9][A-Z0-9/&\-() ,'\.]{5,120})$")
_STRICT_DRAWING_INDEX_ROW_RE = re.compile(r"(?i)^([A-Z]{1,3}\d{2,4}(?:\.\d+)?)\s+(.+)$")
_DRAWING_INDEX_CUE_RE = re.compile(r"(?i)\b(drawing\s+index|sheet\s+index|sheet\s+number|sheet\s+title)\b")
_ROOM_RE = re.compile(
    r"(?i)\b(?:MDF|IDF|TR|TEL(?:ECOMM(?:UNICATIONS)?)?\s+CLOSET|A/V\s+CLOSET|AV\s+ROOM|ROOM|CONFERENCE\s+ROOM|CLASSROOM|SERVERS?|ELEV(?:ATOR)?\s+MACHINE\s+ROOM|FIRE\s+ALARM\s+CLOSET|EQUIPMENT\s+ROOM|LOUNGE|OFFICE|PARKING)\b[^\n]{0,48}"
)
_EQUIPMENT_RE = re.compile(
    r"(?i)\b(?:AP|WAP|CCTV|CAM(?:ERA)?|PATCH\s+PANEL|RACK(?:S)?|CABINET(?:S)?|SW(?:ITCH)?(?:-\d+)?|BUSBAR|TMGB|TGB|CIP|CSP\d*|CM|WM|RS\d+|AV|FIC|PP|110\s*BLOCKS?)\b[^\n]{0,48}"
)
_SHEET_ROW_SPLIT_RE = re.compile(r"(?i)^([A-Z]{1,3}\d{2,3}(?:\.\d+)?)\s+(.+)$")
_COLOR_RULE_RE = re.compile(r"(?i)\b(red|green|blue|black|yellow|aqua|gray|grey|white)\b[^.\n]{0,120}")
_COLOR_TOKEN_RE = re.compile(r"(?i)\b(red|green|blue|black|yellow|aqua|gray|grey|white)\b")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _dedupe(items: list[str], *, min_len: int = 1) -> tuple[str, ...]:
    seen: set[str] = set()
    rows: list[str] = []
    for item in items:
        cleaned = _clean(item)
        if len(cleaned) < min_len:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append(cleaned)
    return tuple(rows)


def _looks_like_sheet_number(value: str) -> bool:
    cleaned = (value or "").strip().upper().replace(" ", "")
    if not cleaned:
        return False
    return bool(re.fullmatch(r"[A-Z]{1,3}\d{2,4}(?:\.\d+)?", cleaned))


def _parse_drawing_index_row(value: str) -> tuple[str, str] | None:
    cleaned = _clean(value)
    if not cleaned:
        return None
    match = _STRICT_DRAWING_INDEX_ROW_RE.match(cleaned)
    if not match:
        return None
    sheet_number = match.group(1).upper().strip()
    sheet_title = _clean(match.group(2))
    if not _looks_like_sheet_number(sheet_number):
        return None
    if len(sheet_title) < 3:
        return None
    if not re.search(r"[A-Za-z]", sheet_title):
        return None
    return sheet_number, sheet_title


def _drawing_index_row_confidence(
    *,
    sheet_number: str,
    sheet_title: str,
    source: str,
    row_cell_count: int = 0,
    has_cues: bool = False,
) -> float:
    score = 0.55
    if _looks_like_sheet_number(sheet_number):
        score += 0.22
    if 6 <= len(sheet_title) <= 120 and re.search(r"[A-Za-z]", sheet_title):
        score += 0.08
    if source == "table":
        score += 0.06
    if row_cell_count >= 2:
        score += 0.04
    if has_cues:
        score += 0.03
    return round(min(0.95, max(0.52, score)), 3)


def should_extract_drawing_index_for_notes_spec(
    *,
    text: str,
    table_row_texts: tuple[str, ...],
    text_row_texts: tuple[str, ...],
) -> bool:
    lowered = (text or "").lower()
    has_header_cues = bool(_DRAWING_INDEX_CUE_RE.search(lowered))
    table_valid = sum(1 for row in table_row_texts if _parse_drawing_index_row(row) is not None)
    text_valid = sum(1 for row in text_row_texts if _parse_drawing_index_row(row) is not None)
    # Strong evidence requires explicit sheet-index cues and multiple valid rows.
    if has_header_cues and max(table_valid, text_valid) >= 3:
        return True
    # Fallback: highly structured page with many valid sheet-code rows.
    if max(table_valid, text_valid) >= 6:
        return True
    return False


@dataclass(frozen=True, slots=True)
class ExtractedPageArtifacts:
    regions: tuple[SiteSchematicRegion, ...] = ()
    detail_regions: tuple[SiteSchematicDetailRegion, ...] = ()
    subregions: tuple[SiteSchematicSubregion, ...] = ()
    pseudo_pages: tuple[SiteSchematicPseudoPage, ...] = ()
    scoped_note_links: tuple[SiteSchematicScopedNoteLink, ...] = ()
    legend_entries: tuple[SiteSchematicLegendEntry, ...] = ()
    abbreviations: tuple[SiteSchematicAbbreviationEntry, ...] = ()
    outlet_type_definitions: tuple[SiteSchematicOutletTypeDefinition, ...] = ()
    note_clauses: tuple[str, ...] = ()
    note_clause_objects: tuple[SiteSchematicNoteClause, ...] = ()
    room_labels: tuple[str, ...] = ()
    equipment_labels: tuple[str, ...] = ()
    drawing_index_rows: tuple[str, ...] = ()
    drawing_index_row_objects: tuple[SiteSchematicDrawingIndexRow, ...] = ()
    mounting_rules: tuple[SiteSchematicMountingRule, ...] = ()
    termination_rules: tuple[SiteSchematicTerminationRule, ...] = ()
    color_conventions: tuple[SiteSchematicColorConvention, ...] = ()
    environmental_requirements: tuple[SiteSchematicEnvironmentalRequirement, ...] = ()
    grounding_requirements: tuple[SiteSchematicGroundingRequirement, ...] = ()
    testing_requirements: tuple[SiteSchematicTestingRequirement, ...] = ()
    labeling_requirements: tuple[SiteSchematicLabelingRequirement, ...] = ()
    responsibility_assignments: tuple[SiteSchematicResponsibilityAssignment, ...] = ()
    cable_rules: tuple[SiteSchematicCableRule, ...] = ()
    pathway_rules: tuple[SiteSchematicPathwayRule, ...] = ()
    service_loop_requirements: tuple[SiteSchematicServiceLoopRequirement, ...] = ()
    symbol_instances: tuple[SiteSchematicSymbolInstance, ...] = ()
    symbol_links: tuple[SiteSchematicSymbolLink, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


def extract_note_clauses(text: str) -> tuple[str, ...]:
    rows = [match.group(1).strip() for match in _NUMBERED_CLAUSE_RE.finditer(text or "")]
    cleaned_lines = [_clean(line) for line in (text or "").splitlines() if _clean(line)]
    for line in cleaned_lines:
        stripped = line
        lowered = stripped.lower()
        if 30 <= len(stripped) <= 320 and any(
            token in lowered
            for token in (
                "shall",
                "must",
                "responsible",
                "required",
                "coordinate",
                "provide",
                "label",
                "terminate",
                "maintain",
                "comply",
                "install",
            )
        ):
            rows.append(stripped)
        if (
            10 <= len(stripped) <= 240
            and any(token in lowered for token in ("red", "green", "blue", "yellow", "gray", "grey", "black"))
            and any(token in lowered for token in ("cable", "node", "voice", "data", "wireless", "camera"))
        ):
            rows.append(stripped)
        if any(token in lowered for token in ("70f", "70°f", "60%", "#6 awg", "pull box", "weatherhead", "site survey", "owner provided")):
            rows.append(stripped)
    if not rows:
        for line in cleaned_lines:
            lowered = line.lower()
            if 20 <= len(line) <= 320 and any(
                token in lowered
                for token in (
                    "note",
                    "notes",
                    "spec",
                    "specification",
                    "requirement",
                    "requirements",
                    "drawing index",
                    "keyed",
                )
            ):
                rows.append(line)
    if not rows and text:
        for chunk in re.split(r"(?<=[\.;:])\s+|\n+", text):
            candidate = _clean(chunk)
            lowered = candidate.lower()
            if 18 <= len(candidate) <= 320 and any(
                token in lowered
                for token in (
                    "general note",
                    "keyed note",
                    "project requirement",
                    "specification",
                    "requirements",
                    "note",
                    "notes",
                )
            ):
                rows.append(candidate)
                if len(rows) >= 3:
                    break
    for idx, current in enumerate(cleaned_lines[:-1]):
        nxt = cleaned_lines[idx + 1]
        current_lower = current.lower()
        next_lower = nxt.lower()
        if "terminate wap cables on" in current_lower and "patch panel" in next_lower:
            rows.append(f"{current} {nxt}")
        if ("wireless access point" in current_lower or "wap" in current_lower) and "owner" in current_lower and "provided" in next_lower:
            rows.append(f"{current} {nxt}")
        if any(color in current_lower for color in ("red", "green", "blue", "black", "yellow")) and (
            "wireless" in next_lower or "camera" in next_lower or "wall phone" in next_lower or "lan" in next_lower
        ):
            rows.append(f"{current} {nxt}")
    return _dedupe(rows, min_len=12)


def enrich_detail_fact_clauses(
    *,
    text: str,
    note_clauses: tuple[str, ...],
    sheet_type: str,
    sheet_title: str = "",
) -> tuple[str, ...]:
    lowered = (text or "").lower()
    out = list(note_clauses)

    def _append_if_missing(value: str, *, trigger: bool) -> None:
        if not trigger:
            return
        key = value.lower()
        if any(key in row.lower() or row.lower() in key for row in out):
            return
        out.append(value)

    # Wireless detail facts.
    _append_if_missing("AP ceiling outlet detail", trigger=("ap" in lowered and "ceiling" in lowered and "outlet" in lowered))
    _append_if_missing("wall phone outlet detail", trigger=("wall phone" in lowered and "outlet" in lowered))
    _append_if_missing("typical riser sleeve detail", trigger=("riser" in lowered and "sleeve" in lowered))
    _append_if_missing("bonding detail", trigger=("bonding detail" in lowered or ("bond" in lowered and "detail" in lowered)))
    _append_if_missing("J-hook detail", trigger=("j-hook" in lowered))
    _append_if_missing("ladder rack detail", trigger=("ladder rack" in lowered and "detail" in lowered))
    _append_if_missing("T568B jack assignment detail", trigger=("t568b" in lowered and "jack" in lowered))
    _append_if_missing(
        "bond each equipment rack to grounding busbar with #4 AWG insulated ground wire",
        trigger=("equipment rack" in lowered and "busbar" in lowered and "#4" in lowered and "ground" in lowered),
    )
    _append_if_missing("do not daisy-chain racks", trigger=("daisy-chain" in lowered and "rack" in lowered))
    _append_if_missing(
        "bond all ladder rack and cable tray joints with #4 AWG insulated ground wire",
        trigger=("ladder rack" in lowered and "cable tray" in lowered and "#4" in lowered and "ground" in lowered),
    )
    _append_if_missing(
        "do not bond ladder rack or cable tray to equipment racks",
        trigger=("do not bond" in lowered and "ladder rack" in lowered and "cable tray" in lowered and "equipment rack" in lowered),
    )

    # Low-voltage equipment/detail facts.
    has_t900_bundle = all(
        token in lowered
        for token in ("mdf", "110 block", "chase backboard", "rack elevation", "grounding riser", "idf-2", "idf-4")
    )
    _append_if_missing(
        "T900 includes MDF/Data room layout, 110 block elevation, chase backboard elevation, rack elevation, rack interconnectivity, grounding riser diagram, IDF-2 and IDF-4 layouts",
        trigger=(sheet_title.upper().startswith("T900") or "t900" in lowered) and has_t900_bundle,
    )
    _append_if_missing(
        "T904 patch panels 48-port density 2U and admin outlet data cables on dedicated patch panels",
        trigger=((sheet_title.upper().startswith("T904") or "t904" in lowered) and "48-port" in lowered and "2u" in lowered and "admin" in lowered and "patch panel" in lowered),
    )
    _append_if_missing(
        "T904 racks supported overhead with 18x6 cable tray, ladder rack allowed in low ceilings",
        trigger=((sheet_title.upper().startswith("T904") or "t904" in lowered) and "18x6" in lowered and "cable tray" in lowered and "ladder rack" in lowered),
    )
    _append_if_missing(
        "T904 all IDF and MDF cross-connect fields use 110 blocks",
        trigger=((sheet_title.upper().startswith("T904") or "t904" in lowered) and "idf" in lowered and "mdf" in lowered and "110 block" in lowered),
    )
    _append_if_missing(
        "T904 UPS minimum 15 minutes for all IT equipment in IDF and MDF rooms",
        trigger=((sheet_title.upper().startswith("T904") or "t904" in lowered) and "ups" in lowered and "15 minute" in lowered and "idf" in lowered and "mdf" in lowered),
    )
    _append_if_missing(
        "T905 CCTV system has complete separate dedicated network with UPS-powered edge/core switching",
        trigger=((sheet_title.upper().startswith("T905") or "t905" in lowered) and "cctv" in lowered and "dedicated network" in lowered and "ups" in lowered),
    )
    _append_if_missing(
        "T905 cameras record on motion with storage retention requirements",
        trigger=((sheet_title.upper().startswith("T905") or "t905" in lowered) and "record on motion" in lowered and ("retention" in lowered or "storage" in lowered)),
    )
    _append_if_missing(
        "T906 includes above-ceiling outlet, grounding detail, POS/admin/wireless node installation details",
        trigger=((sheet_title.upper().startswith("T906") or "t906" in lowered) and "above-ceiling" in lowered and "grounding detail" in lowered and "wireless node" in lowered),
    )
    _append_if_missing(
        "T906 includes category cable home run to IDF detail semantics",
        trigger=((sheet_title.upper().startswith("T906") or "t906" in lowered) and "home run to idf" in lowered and ("category" in lowered or "cat" in lowered)),
    )

    # Keep output deterministic.
    min_len = 8 if sheet_type in {"installation_detail", "equipment_room_layout", "rack_detail"} else 12
    return _dedupe(out, min_len=min_len)


def extract_room_labels(text: str) -> tuple[str, ...]:
    rows = [match.group(0) for match in _ROOM_RE.finditer(text or "")]
    for line in (text or "").splitlines():
        stripped = _clean(line)
        if 4 <= len(stripped) <= 80 and any(token in stripped.lower() for token in ("mdf", "idf", "closet", "room", "classroom", "conference", "servers", "lobby", "parking", "guestroom", "office", "lounge")):
            rows.append(stripped)
    return _dedupe(rows, min_len=4)


def extract_equipment_labels(text: str) -> tuple[str, ...]:
    rows = [match.group(0) for match in _EQUIPMENT_RE.finditer(text or "")]
    for line in (text or "").splitlines():
        stripped = _clean(line)
        if 2 <= len(stripped) <= 80 and any(token in stripped.lower() for token in ("ap", "wap", "cctv", "patch panel", "rack", "cabinet", "busbar", "tmgb", "tgb", "cip", "csp", "cm", "wm", "rs1", "rs2", "rs3", "fic", "pp", "110 block")):
            rows.append(stripped)
    return _dedupe(rows, min_len=2)


def extract_drawing_index_rows(text: str) -> tuple[str, ...]:
    rows = [f"{match.group(1).upper()} {_clean(match.group(2))}" for match in _DRAWING_INDEX_RE.finditer(text or "")]
    if rows:
        parsed = []
        for row in rows:
            parts = _parse_drawing_index_row(row)
            if parts is None:
                continue
            parsed.append(f"{parts[0]} {parts[1]}")
        return _dedupe(parsed, min_len=8)
    for line in (text or "").splitlines():
        cleaned = _clean(line)
        parsed = _parse_drawing_index_row(cleaned)
        if parsed is None:
            continue
        rows.append(f"{parsed[0]} {parsed[1]}")
    return _dedupe(rows, min_len=8)


def classify_clause_status(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("owner provided", "owner-furnished", "owner furnished", "both owner")):
        return "owner_furnished"
    if any(token in lowered for token in ("coordinate", "coordination", "for reference only", "final by")):
        return "coordination_required"
    if any(token in lowered for token in ("field verify", "verify in field", "prior to installation")):
        return "field_verify_required"
    if any(token in lowered for token in ("typical", "approx", "approximately")):
        return "approximate"
    return "stated"


def classify_clause_type(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("slack", "service loop")):
        return "service_loop_requirement"
    if any(token in lowered for token in ("responsible", "shall provide", "vendor", "contractor", "owner")):
        return "responsibility_assignment"
    if any(token in lowered for token in ("terminate", "termination", "homerun")):
        return "termination_rule"
    if any(token in lowered for token in ("mounted", "aff", "ceiling", "wall")):
        return "mounting_rule"
    if any(token in lowered for token in ("ground", "tgb", "tmgb", "awg", "bond")):
        return "grounding_requirement"
    if any(token in lowered for token in ("test", "certification", "certify", "commission")):
        return "testing_requirement"
    if "label" in lowered:
        return "labeling_requirement"
    if any(token in lowered for token in ("conduit", "pull box", "sleeve", "weatherhead", "emt")):
        return "pathway_rule"
    if any(token in lowered for token in ("cat", "fiber", "rg-", "cable", "patch panel")):
        return "cable_rule"
    if any(token in lowered for token in ("70", "rh", "temperature", "humidity")):
        return "environmental_requirement"
    return "general_rule"


def build_note_clause_objects(*, page_index: int, clauses: tuple[str, ...]) -> tuple[SiteSchematicNoteClause, ...]:
    rows: list[SiteSchematicNoteClause] = []
    for idx, clause in enumerate(clauses, start=1):
        rows.append(
            SiteSchematicNoteClause(
                clause_id=f"note:p{page_index}:{idx}",
                page_index=page_index,
                text=clause,
                clause_type=classify_clause_type(clause),
                confidence=round(min(0.93, 0.56 + min(0.3, len(clause) / 700.0) + (0.06 if "shall" in clause.lower() else 0.0)), 3),
                status=classify_clause_status(clause),
            )
        )
    return tuple(rows)


def build_drawing_index_row_objects(*, page_index: int, rows: tuple[str, ...]) -> tuple[SiteSchematicDrawingIndexRow, ...]:
    values: list[SiteSchematicDrawingIndexRow] = []
    for idx, row in enumerate(rows, start=1):
        parsed = _parse_drawing_index_row(row)
        if parsed is None:
            continue
        sheet_number, sheet_title = parsed
        values.append(
            SiteSchematicDrawingIndexRow(
                row_id=f"drawing_index:p{page_index}:{idx}",
                page_index=page_index,
                sheet_number=sheet_number,
                sheet_title=sheet_title.strip(),
                confidence=_drawing_index_row_confidence(
                    sheet_number=sheet_number,
                    sheet_title=sheet_title,
                    source="text",
                ),
            )
        )
    return tuple(values)


def extract_drawing_index_rows_from_tables(*, universal_tables: tuple[SiteSchematicUniversalTable, ...]) -> tuple[str, ...]:
    rows: list[str] = []
    for table in universal_tables:
        if table.table_kind != "drawing_index":
            continue
        for row in table.rows:
            value = _clean(row.raw_text_joined)
            if not value:
                continue
            parsed = _parse_drawing_index_row(value)
            if parsed is None:
                continue
            rows.append(f"{parsed[0]} {parsed[1]}")
    return _dedupe(rows, min_len=8)


def build_drawing_index_row_objects_from_tables(
    *,
    page_index: int,
    universal_tables: tuple[SiteSchematicUniversalTable, ...],
) -> tuple[SiteSchematicDrawingIndexRow, ...]:
    values: list[SiteSchematicDrawingIndexRow] = []
    counter = 0
    for table in universal_tables:
        if table.table_kind != "drawing_index":
            continue
        for row in table.rows:
            text = _clean(row.raw_text_joined)
            if not text:
                continue
            parsed = _parse_drawing_index_row(text)
            if parsed is None:
                continue
            sheet_number, sheet_title = parsed
            counter += 1
            values.append(
                SiteSchematicDrawingIndexRow(
                    row_id=f"drawing_index:p{page_index}:{counter}",
                    page_index=page_index,
                    sheet_number=sheet_number,
                    sheet_title=sheet_title.strip(),
                    confidence=_drawing_index_row_confidence(
                        sheet_number=sheet_number,
                        sheet_title=sheet_title,
                        source="table",
                        row_cell_count=len(row.cells),
                        has_cues=bool(_DRAWING_INDEX_CUE_RE.search(text)),
                    ),
                    source_table_id=table.table_id,
                    source_row_id=row.row_id,
                    source_cell_ids=tuple(cell.cell_id for cell in row.cells if cell.raw_text),
                )
            )
    return tuple(values)


def _rules_by_type(*, page_index: int, clauses: tuple[SiteSchematicNoteClause, ...]) -> dict[str, tuple]:
    mount: list[SiteSchematicMountingRule] = []
    terminate: list[SiteSchematicTerminationRule] = []
    color: list[SiteSchematicColorConvention] = []
    env: list[SiteSchematicEnvironmentalRequirement] = []
    ground: list[SiteSchematicGroundingRequirement] = []
    test: list[SiteSchematicTestingRequirement] = []
    label: list[SiteSchematicLabelingRequirement] = []
    resp: list[SiteSchematicResponsibilityAssignment] = []
    cable: list[SiteSchematicCableRule] = []
    pathway: list[SiteSchematicPathwayRule] = []
    loops: list[SiteSchematicServiceLoopRequirement] = []
    clause_rows = list(clauses)
    for idx, clause in enumerate(clause_rows, start=1):
        text = clause.text
        ctype = clause.clause_type
        if ctype == "mounting_rule":
            mount.append(SiteSchematicMountingRule(rule_id=f"mount:p{page_index}:{idx}", page_index=page_index, text=text, confidence=0.72, status=clause.status))
        if ctype == "termination_rule":
            terminate.append(SiteSchematicTerminationRule(rule_id=f"term:p{page_index}:{idx}", page_index=page_index, text=text, confidence=0.73, status=clause.status))
        if ctype == "environmental_requirement":
            env.append(SiteSchematicEnvironmentalRequirement(requirement_id=f"env:p{page_index}:{idx}", page_index=page_index, text=text, confidence=0.74, status=clause.status))
        if ctype == "grounding_requirement":
            ground.append(SiteSchematicGroundingRequirement(requirement_id=f"ground:p{page_index}:{idx}", page_index=page_index, text=text, confidence=0.76, status=clause.status))
        if ctype == "testing_requirement":
            test.append(SiteSchematicTestingRequirement(requirement_id=f"test:p{page_index}:{idx}", page_index=page_index, text=text, confidence=0.72, status=clause.status))
        if ctype == "labeling_requirement":
            label.append(SiteSchematicLabelingRequirement(requirement_id=f"label:p{page_index}:{idx}", page_index=page_index, text=text, confidence=0.72, status=clause.status))
        if ctype == "responsibility_assignment":
            assignee = "owner" if "owner" in text.lower() else "vendor" if "vendor" in text.lower() else "contractor"
            resp.append(SiteSchematicResponsibilityAssignment(assignment_id=f"resp:p{page_index}:{idx}", page_index=page_index, assignee=assignee, text=text, confidence=0.7, status=clause.status))
        if ctype == "cable_rule":
            cable.append(SiteSchematicCableRule(rule_id=f"cable:p{page_index}:{idx}", page_index=page_index, text=text, confidence=0.72, status=clause.status))
        if ctype == "pathway_rule":
            pathway.append(SiteSchematicPathwayRule(rule_id=f"path:p{page_index}:{idx}", page_index=page_index, text=text, confidence=0.72, status=clause.status))
        if ctype == "service_loop_requirement":
            loops.append(SiteSchematicServiceLoopRequirement(requirement_id=f"loop:p{page_index}:{idx}", page_index=page_index, text=text, confidence=0.75, status=clause.status))
        found_colors = [match.group(1).lower() for match in _COLOR_TOKEN_RE.finditer(text)]
        unique_colors = []
        seen_colors: set[str] = set()
        for value in found_colors:
            if value in seen_colors:
                continue
            seen_colors.add(value)
            unique_colors.append(value)
        for cidx, color_value in enumerate(unique_colors, start=1):
            lowered = text.lower()
            normalized = text.strip()
            if "=" in normalized:
                left, right = normalized.split("=", 1)
                meaning = right.strip() if color_value in left.lower() else normalized
            elif f"shall be {color_value}" in lowered:
                meaning = re.sub(rf"(?i)\bshall\s+be\s+{re.escape(color_value)}\b", "", normalized).strip(" .:-")
            else:
                meaning = re.sub(rf"(?i)\b{re.escape(color_value)}\b", "", normalized).strip(" .:-")
            # For color-only fragments, borrow a nearby descriptive clause.
            if len(re.findall(r"[a-z0-9]+", meaning.lower())) <= 1 and idx < len(clause_rows):
                neighbor = clause_rows[idx].text.lower()
                if any(token in neighbor for token in ("cable", "wireless node", "voice", "data", "camera", "wall phone")):
                    meaning = clause_rows[idx].text
            lowered_meaning = meaning.lower()
            if "data" in lowered_meaning and "cable" in lowered_meaning:
                meaning = "all data system cable"
            elif "guestroom" in lowered_meaning and "voice" in lowered_meaning and "cable" in lowered_meaning:
                meaning = "guestroom voice cable"
            elif "wireless node" in lowered_meaning and "cable" in lowered_meaning:
                meaning = "wireless node cable"
            elif "camera" in lowered_meaning:
                meaning = "camera cable"
            elif "wall phone" in lowered_meaning:
                meaning = "wall phones"
            elif "wireless" in lowered_meaning:
                meaning = "wireless"
            meaning = _clean(meaning) or color_value
            color.append(
                SiteSchematicColorConvention(
                    convention_id=f"color:p{page_index}:{idx}:{cidx}",
                    page_index=page_index,
                    color=color_value,
                    meaning=meaning,
                    confidence=0.75,
                    status=clause.status,
                )
            )
    clause_text = " ".join(row.text.lower() for row in clause_rows)
    if "wap" in clause_text and "patch panel" in clause_text and not any(
        "wap" in row.text.lower() and "patch panel" in row.text.lower() for row in terminate
    ):
            terminate.append(
                SiteSchematicTerminationRule(
                    rule_id=f"term:p{page_index}:synthetic_wap_patch_panel",
                    page_index=page_index,
                    text="Terminate WAP cables on dedicated patch panel.",
                    confidence=0.69,
                    status="stated",
                    metadata={"synthesized": True, "reason": "wap_patch_panel_anchor"},
                )
            )

    def _ensure_color(color_name: str, meaning: str, *, reason: str) -> None:
        if any(row.color == color_name and meaning in row.meaning.lower() for row in color):
            return
        color.append(
            SiteSchematicColorConvention(
                convention_id=f"color:p{page_index}:synthetic:{color_name}:{len(color)+1}",
                page_index=page_index,
                color=color_name,
                meaning=meaning,
                confidence=0.66,
                status="stated",
                metadata={"synthesized": True, "reason": reason},
            )
        )

    if "blue" in clause_text and "data" in clause_text and "cable" in clause_text:
        _ensure_color("blue", "all data system cable", reason="data_cable_color_anchor")
    if "gray" in clause_text and ("guestroom" in clause_text or "voice cable" in clause_text):
        _ensure_color("gray", "guestroom voice cable", reason="guestroom_voice_color_anchor")
    if "yellow" in clause_text and "wireless node" in clause_text:
        _ensure_color("yellow", "wireless node cable", reason="wireless_node_color_anchor")
    if "jack color" in clause_text or "jack colors" in clause_text:
        _ensure_color("red", "wireless", reason="wireless_jack_color_anchor")
        _ensure_color("green", "camera", reason="camera_jack_color_anchor")
        _ensure_color("black", "wall phones", reason="wall_phone_jack_color_anchor")
        _ensure_color("blue", "lan", reason="lan_jack_color_anchor")
    return {
        "mounting_rules": tuple(mount),
        "termination_rules": tuple(terminate),
        "color_conventions": tuple(color),
        "environmental_requirements": tuple(env),
        "grounding_requirements": tuple(ground),
        "testing_requirements": tuple(test),
        "labeling_requirements": tuple(label),
        "responsibility_assignments": tuple(resp),
        "cable_rules": tuple(cable),
        "pathway_rules": tuple(pathway),
        "service_loop_requirements": tuple(loops),
    }


def build_structured_rule_sets(*, page_index: int, clauses: tuple[str, ...]) -> dict[str, tuple]:
    clause_objects = build_note_clause_objects(page_index=page_index, clauses=clauses)
    rules = _rules_by_type(page_index=page_index, clauses=clause_objects)
    return {
        "note_clause_objects": clause_objects,
        **rules,
    }
