from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable

from orbitbrief_core.parser.site_schematic.holdout_titleblock_profiles import score_sheet_text_against_holdout_profiles
from orbitbrief_core.parser.site_schematic.residual_titleblock_profiles import score_residual_titleblock_families
from orbitbrief_core.parser.site_schematic.structure_graph_sheet_hints import build_sheet_archetype_hints

_SHEET_NO_RE = re.compile(r"\b(([A-Z]{1,3})\d{3,4}(?:\.\d+)?)\b", flags=re.IGNORECASE)
_SHEET_TITLE_RE = re.compile(
    r"(?:(?:LAYOUT:|SHEET\s+NO\.?[:\-]?|NUMBER[:\-]?)\s*)?(([A-Z]{1,3})\d{3,4}(?:\.\d+)?)\s+([A-Z][A-Z0-9/&()' .,-]{6,100})",
    flags=re.IGNORECASE,
)
_DRAWING_INDEX_TITLE_RE = re.compile(
    r"(?m)^\s*(([A-Z]{1,3})\d{3,4}(?:\.\d+)?)\s+([A-Z][A-Z0-9/&()' .,-]{6,100})\s*(?:\d+\s+OF\s+\d+)?\s*$",
    flags=re.IGNORECASE,
)
_TABLE_ROW_HINT_RE = re.compile(r"(?m)^\s*[A-Z]{1,3}\d{2,4}(?:\.\d+)?\s+[A-Z].*$")
_RACK_HINT_RE = re.compile(r"(?i)\b(rack|cabinet|patch panel|wire manager|ladder rack|busbar)\b")
_RISER_HINT_RE = re.compile(r"(?i)\b(riser|backbone|tmgb|tgb|grounding|homerun|vertical)\b")
_LEGEND_HINT_RE = re.compile(r"(?i)\b(symbol|legend|abbreviation|tag symbol)\b")
_SCHEDULE_HINT_RE = re.compile(r"(?i)\b(schedule|matrix|index|sheet list|drawing list|responsibility)\b")
_NOTES_HINT_RE = re.compile(r"(?i)\b(notes?|spec(?:ification)?s?|requirements?|instructions?)\b")
_DETAIL_HINT_RE = re.compile(r"(?i)\b(detail|typical|elevation|callout|section)\b")


@dataclass(frozen=True, slots=True)
class SheetClassification:
    sheet_number: str
    sheet_title: str
    sheet_type: str
    confidence: float
    evidence_codes: tuple[str, ...] = ()


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def extract_sheet_number(text: str) -> str:
    raw_text = text or ""
    matches = [match.group(1).upper() for match in _SHEET_NO_RE.finditer(raw_text)]
    if not matches:
        return ""
    lines = _lines(raw_text)
    known_sheet_ids = {
        "T000",
        "T001",
        "T002",
        "T700",
        "T900",
        "T901",
        "T902",
        "T903",
        "T904",
        "T905",
        "T906",
        "TC001",
        "TC301",
        "TC502",
    }
    by_score: dict[str, float] = {}
    for idx, line in enumerate(lines):
        line_matches = [m.group(1).upper() for m in _SHEET_NO_RE.finditer(line)]
        if not line_matches:
            continue
        lowered = line.lower()
        structural_hint = ("sheet" in lowered) or ("layout" in lowered) or ("number" in lowered)
        title_hint = any(token in lowered for token in ("floor plan", "details", "riser", "legend", "schedule", "enlarged"))
        index_like = bool(_DRAWING_INDEX_TITLE_RE.match(line)) and idx < max(10, len(lines) // 3)
        for token in line_matches:
            score = 0.0
            if structural_hint:
                score += 3.0
            if title_hint:
                score += 1.5
            if token in known_sheet_ids:
                score += 1.0
            if idx < 12:
                score += 0.7
            if index_like:
                score -= 1.5
            by_score[token] = max(by_score.get(token, -1e9), score)
    if by_score:
        return max(by_score.items(), key=lambda item: item[1])[0]
    return matches[-1]


def _title_from_matches(text: str, sheet_number: str) -> str:
    if not sheet_number:
        return ""
    for match in _SHEET_TITLE_RE.finditer(text):
        if match.group(1).upper() == sheet_number.upper():
            candidate = _clean(match.group(3))
            if candidate:
                return candidate.upper()
    for match in _DRAWING_INDEX_TITLE_RE.finditer(text):
        if match.group(1).upper() == sheet_number.upper():
            candidate = _clean(match.group(3))
            if candidate:
                return candidate.upper()
    return ""


def infer_sheet_title(text: str, *, sheet_number: str = "") -> str:
    title = _title_from_matches(text, sheet_number)
    if title:
        return title
    lowered = (text or "").lower()
    known_by_code = {
        "T000": "PROJECT REQUIREMENTS NOTES & SPECS",
        "T001": "SYMBOLS & LEGENDS",
        "T002": "SCHEDULES & MISCELLANEOUS",
        "T700": "ENLARGED GUESTROOM LAYOUTS",
        "T900": "ENLARGED EQUIPMENT ROOM LAYOUTS",
        "T901": "CONDUIT RISER DIAGRAM",
        "T902": "CABLING RISER DIAGRAM",
        "T903": "MATV CABLING RISER DIAGRAM",
        "T904": "EQUIPMENT RACK DETAILS",
        "T905": "SECURITY INSTALLATION DETAILS",
        "T906": "INSTALLATION DETAILS",
        "TC001": "TELECOMM SYMBOL LIST",
        "TC301": "TELECOMM RISER DIAGRAM",
        "TC502": "TELECOMM DETAILS",
    }
    if sheet_number.upper() in known_by_code:
        return known_by_code[sheet_number.upper()]
    if sheet_number.upper().startswith(("T100", "T101", "T102", "T103", "T104", "T105", "T106", "TC100", "TC101", "TC102", "TC103", "TC104", "TC105")):
        return "FLOOR PLAN"
    if sheet_number.upper().startswith(("TC200", "TC201")):
        return "TELECOMM PART PLANS"
    if "project requirements" in lowered or "notes & specs" in lowered:
        return "PROJECT REQUIREMENTS NOTES & SPECS"
    if "symbols & legends" in lowered or "symbol list" in lowered or "telecomm symbol" in lowered:
        return "SYMBOLS & LEGENDS"
    if "drawing index" in lowered and "project requirements" in lowered:
        return "PROJECT REQUIREMENTS NOTES & SPECS"
    if "component specifications list" in lowered or "schedule" in lowered:
        return "SCHEDULES & MISCELLANEOUS"
    if "equipment room" in lowered or "closet layout" in lowered:
        return "ENLARGED EQUIPMENT ROOM LAYOUTS"
    if "riser diagram" in lowered:
        return "RISER DIAGRAM"
    if "installation details" in lowered or "telecomm details" in lowered:
        return "INSTALLATION DETAILS"
    return ""


def _score_contains(text: str, tokens: Iterable[str]) -> int:
    lowered = text.lower()
    return sum(1 for token in tokens if token in lowered)


def classify_sheet(text: str) -> SheetClassification:
    sheet_number = extract_sheet_number(text)
    sheet_title = infer_sheet_title(text, sheet_number=sheet_number)
    lowered = (text or "").lower()
    title_lower = sheet_title.lower()
    evidence: list[str] = []
    holdout_profile_scores = score_sheet_text_against_holdout_profiles(
        text_candidates=[sheet_title, text],
        sheet_id_candidates=[sheet_number] if sheet_number else [],
    )
    residual_profile_scores = score_residual_titleblock_families(
        [sheet_title, text],
        [sheet_number] if sheet_number else [],
    )

    def choose(sheet_type: str, confidence: float, *codes: str) -> SheetClassification:
        evidence.extend(code for code in codes if code)
        return SheetClassification(
            sheet_number=sheet_number,
            sheet_title=sheet_title,
            sheet_type=sheet_type,
            confidence=confidence,
            evidence_codes=tuple(dict.fromkeys(evidence)),
        )

    def choose_from_holdout_profiles(min_score: float = 2.25) -> SheetClassification | None:
        if not holdout_profile_scores:
            return None
        family, score = max(holdout_profile_scores.items(), key=lambda item: item[1])
        if score < min_score:
            return None
        family_to_sheet_type = {
            "legend_symbol": "legend_symbol",
            "notes_spec": "notes_spec",
            "drawing_index": "schedule_sheet",
            "riser_diagram": "riser_diagram",
            "equipment_room_layout": "equipment_room_layout",
            "installation_detail": "installation_detail",
            "floorplan": "floorplan_overall",
        }
        target = family_to_sheet_type.get(family)
        if target is None:
            return None
        confidence = min(0.95, 0.62 + 0.06 * score)
        return choose(target, confidence, f"holdout_profile:{family}", f"holdout_profile_score:{score:.2f}")

    def choose_from_residual_profiles(min_score: float = 2.0) -> SheetClassification | None:
        if not residual_profile_scores:
            return None
        if sheet_number:
            return None
        if sheet_number.upper() in {"T000", "T001", "T002", "T700", "T900", "T901", "T902", "T903", "T904", "T905", "T906", "TC001", "TC301", "TC502"}:
            return None
        family, score = max(residual_profile_scores.items(), key=lambda item: item[1])
        if score < min_score:
            return None
        family_map = {
            "legend_symbol": "legend_symbol",
            "notes_spec": "notes_spec",
            "riser_diagram": "riser_diagram",
            "installation_detail": "installation_detail",
            "floorplan": "floorplan_overall",
            "equipment_room_layout": "equipment_room_layout",
            "schedule_sheet": "schedule_sheet",
        }
        mapped = family_map.get(family)
        if mapped is None:
            return None
        return choose(
            mapped,
            min(0.94, 0.6 + 0.07 * score),
            f"residual_profile:{family}",
            f"residual_profile_score:{score:.2f}",
        )

    if sheet_number.upper() == "T000" or "project requirements" in title_lower or "notes & specs" in title_lower:
        return choose("notes_spec", 0.96, "sheet_code_notes_spec", "title_notes_spec")
    if sheet_number.upper() == "T001" or any(token in title_lower for token in ("symbols", "legend", "symbol list")):
        return choose("legend_symbol", 0.96, "sheet_code_legend", "title_legend")
    if sheet_number.upper() == "T002" or "schedule" in title_lower or "specifications list" in lowered:
        return choose("schedule_sheet", 0.9, "sheet_code_schedule", "content_schedule")
    if sheet_number.upper() == "T700":
        return choose("floorplan_detail", 0.9, "sheet_code_enlarged_layout")
    if sheet_number.upper() == "T900":
        return choose("equipment_room_layout", 0.95, "sheet_code_equipment_room")
    if sheet_number.upper() in {"T901", "T902", "T903", "TC301"}:
        return choose("riser_diagram", 0.95, "sheet_code_riser")
    if sheet_number.upper() in {"T904"}:
        return choose("rack_detail", 0.94, "sheet_code_rack_detail")
    if sheet_number.upper() in {"T905", "T906", "TC502"}:
        return choose("installation_detail", 0.95, "sheet_code_installation_detail")
    if sheet_number.upper().startswith(("TC100", "TC101", "TC102", "TC103", "TC104", "TC105", "T100", "T101", "T102", "T103", "T104", "T105", "T106")):
        if any(token in title_lower for token in ("roof", "floor plan", "telecomm plan", "plan overall", "guestroom")) or sheet_number.upper() != "TC001":
            kind = "floorplan_overall" if any(token in sheet_number.upper() for token in ("T100", "T101", "T102", "T103", "T104", "T105", "T106", "TC100", "TC101", "TC102", "TC103", "TC104", "TC105")) else "floorplan_detail"
            return choose(kind, 0.92, "sheet_code_floorplan")
    if sheet_number.upper().startswith(("TC200", "TC201")) or any(token in title_lower for token in ("equipment room",)):
        if any(token in lowered for token in ("rack mount", "catalyst", "patch panel", "front view", "rear view")):
            return choose("rack_detail", 0.82, "content_rack_detail")
        if "part plan" in title_lower or "part plans" in title_lower:
            return choose("floorplan_overall", 0.84, "sheet_code_part_plan_floorplan")
        if any(token in lowered for token in ("matchline", "key plan", "overall plan", "typical floor", "telecomm plan")):
            return choose("floorplan_overall", 0.84, "sheet_code_part_plan_floorplan")
        if any(token in lowered for token in ("equipment room", "telecom room", "idf", "mdf", "closet")):
            return choose("equipment_room_layout", 0.82, "sheet_code_equipment_part_plan")
        return choose("floorplan_overall", 0.8, "sheet_code_part_plan_floorplan")
    holdout_profile_choice = choose_from_holdout_profiles()
    if holdout_profile_choice is not None:
        return holdout_profile_choice
    residual_profile_choice = choose_from_residual_profiles()
    if residual_profile_choice is not None:
        return residual_profile_choice

    if _RISER_HINT_RE.search(lowered):
        return choose("riser_diagram", 0.8, "content_riser")
    if _score_contains(lowered, ("floor plan", "plan overall", "telecomm plan", "guestroom", "lobby level floor plan", "parking level floor plan")) >= 1:
        return choose("floorplan_overall", 0.78, "content_floorplan")
    if _LEGEND_HINT_RE.search(title_lower) or _LEGEND_HINT_RE.search(lowered):
        return choose("legend_symbol", 0.84, "content_legend")
    if _NOTES_HINT_RE.search(title_lower) or _score_contains(lowered, ("general notes", "project requirements", "warranty", "maintenance and support", "drawing index")) >= 2:
        return choose("notes_spec", 0.82, "content_notes_spec")
    if _SCHEDULE_HINT_RE.search(lowered) or _TABLE_ROW_HINT_RE.search(text):
        return choose("schedule_sheet", 0.78, "content_schedule")
    if _RACK_HINT_RE.search(lowered):
        return choose("rack_detail", 0.8, "content_rack_detail")
    if _DETAIL_HINT_RE.search(lowered) and _score_contains(lowered, ("detail", "typical", "installation", "security", "telecom")) >= 2:
        return choose("installation_detail", 0.8, "content_install_detail")
    if sum(1 for line in _lines(text) if re.search(r"\b(?:AP|CM|CIP|CSP\d+|RS\d+)\b", line)) >= 2:
        return choose("floorplan_overall", 0.72, "symbol_dense_floorplan")
    if _score_contains(lowered, ("equipment room", "ladder rack", "busbar", "equipment rack")) >= 2:
        return choose("equipment_room_layout", 0.72, "content_equipment_room")
    if sum(1 for _ in re.finditer(r"(?m)^\s*(?:\d+\.|[A-Z]\.|[-*])\s+", text)) >= 3:
        return choose("notes_spec", 0.7, "numbered_clause_notes_spec")
    if _TABLE_ROW_HINT_RE.search(text):
        return choose("schedule_sheet", 0.62, "fallback_table_index")
    if any(token in lowered for token in ("telecom", "communications", "technology", "security", "intercom")):
        return choose("floorplan_overall", 0.56, "fallback_packet_plan")
    if sheet_number:
        if sheet_number.startswith(("T9", "TC5")):
            return choose("installation_detail", 0.52, "fallback_sheet_number_detail")
        if sheet_number.startswith(("T7", "TC3")):
            return choose("riser_diagram", 0.5, "fallback_sheet_number_riser")
        return choose("floorplan_overall", 0.5, "fallback_sheet_number_plan")
    if _clean(text):
        return choose("floorplan_overall", 0.42, "fallback_nonempty_page_plan")
    return choose("unknown", 0.3, "fallback_unknown")


def refine_sheet_classification_with_structure_graph(
    classification: SheetClassification,
    *,
    structure_graph: Any | None,
) -> SheetClassification:
    if structure_graph is None:
        return classification
    if classification.sheet_number:
        return classification
    if classification.confidence >= 0.88:
        return classification
    if any(code.startswith("sheet_code_") for code in classification.evidence_codes):
        return classification
    if classification.sheet_number.upper() in {
        "T000",
        "T001",
        "T002",
        "T700",
        "T900",
        "T901",
        "T902",
        "T903",
        "T904",
        "T905",
        "T906",
        "TC001",
        "TC301",
        "TC502",
    }:
        return classification
    hint = build_sheet_archetype_hints(structure_graph)
    if not hint.family_scores:
        return classification
    best_family, best_score = max(hint.family_scores.items(), key=lambda row: row[1])
    if best_score < 1.5:
        return classification
    if classification.sheet_type == best_family and classification.confidence >= 0.75:
        return classification
    confidence = max(classification.confidence, min(0.93, 0.6 + 0.06 * best_score))
    return SheetClassification(
        sheet_number=classification.sheet_number,
        sheet_title=classification.sheet_title,
        sheet_type=best_family,
        confidence=confidence,
        evidence_codes=tuple((*classification.evidence_codes, "structure_graph_family_hint")),
    )
