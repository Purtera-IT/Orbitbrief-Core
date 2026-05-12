from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Iterable

from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.site_schematic import build_site_schematic_bundle_from_router_input
from orbitbrief_core.parser.site_schematic.models import SiteSchematicBundle

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
FIXTURE_PDF_DIR = FIXTURE_DIR / "pdfs"
WIRELESS_FIXTURE = FIXTURE_DIR / "wireless_route_golden.json"
LOW_VOLTAGE_FIXTURE = FIXTURE_DIR / "low_voltage_route_golden.json"
WIRELESS_PDF_FIXTURE = FIXTURE_PDF_DIR / "100643PLANSD-4.pdf"
LOW_VOLTAGE_PDF_FIXTURE = FIXTURE_PDF_DIR / "2026-01-19 CONSOLIDATED SET - SOUTHERN POST - T (1) (1) (1).pdf"

_STOPWORDS = {
    "a",
    "an",
    "and",
    "all",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
    "unless",
    "otherwise",
    "only",
    "prior",
    "each",
    "every",
    "per",
    "via",
}


@dataclass(frozen=True, slots=True)
class CorpusEntry:
    kind: str
    text: str
    normalized: str
    tokens: frozenset[str]


@dataclass(frozen=True, slots=True)
class FactMatch:
    expected: str
    matched: str | None
    score: float

    @property
    def passed(self) -> bool:
        return self.score >= 0.55


@dataclass(frozen=True, slots=True)
class GoldScorecard:
    route_id: str
    page_count_match: bool
    typed_pages_match: bool
    sheet_type_counts_match: bool
    region_presence_match: bool
    minimum_output_keys_match: bool
    legality_status_match: bool
    graph_expectations_match: bool
    critical_sections: dict[str, float]
    exact_anchor_checks: dict[str, bool]
    unmatched_examples: dict[str, tuple[str, ...]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_id": self.route_id,
            "page_count_match": self.page_count_match,
            "typed_pages_match": self.typed_pages_match,
            "sheet_type_counts_match": self.sheet_type_counts_match,
            "region_presence_match": self.region_presence_match,
            "minimum_output_keys_match": self.minimum_output_keys_match,
            "legality_status_match": self.legality_status_match,
            "graph_expectations_match": self.graph_expectations_match,
            "critical_sections": dict(self.critical_sections),
            "exact_anchor_checks": dict(self.exact_anchor_checks),
            "unmatched_examples": {key: list(value) for key, value in self.unmatched_examples.items()},
        }


def _clean(text: str) -> str:
    text = (text or "").replace("°", "").replace("”", '"').replace("“", '"').replace("’", "'")
    text = text.replace("1 1_4", "1 1/4").replace("1_4", "1/4")
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> frozenset[str]:
    normalized = _clean(text).lower()
    normalized = normalized.replace("cat-6", "cat6").replace("cat 6", "cat6")
    normalized = normalized.replace("wi-fi", "wifi")
    normalized = normalized.replace("1/4", "1_4")
    raw_tokens = re.findall(r"[a-z0-9#']+", normalized)
    filtered = [token for token in raw_tokens if token not in _STOPWORDS and len(token) > 1]
    return frozenset(filtered)


def _norm(text: str) -> str:
    return " ".join(sorted(_tokens(text)))



def resolve_fixture_pdf(route: str) -> Path:
    route_key = str(route).strip().lower()
    if route_key in {"wireless", "wireless_ap_heavy_telecom_packet"}:
        candidates = (WIRELESS_PDF_FIXTURE, Path("/mnt/data/100643PLANSD-4.pdf"))
    elif route_key in {"low_voltage", "low_voltage_hospitality_packet"}:
        candidates = (LOW_VOLTAGE_PDF_FIXTURE, Path("/mnt/data/2026-01-19 CONSOLIDATED SET - SOUTHERN POST - T (1) (1) (1).pdf"))
    else:
        raise ValueError(f"Unknown route: {route}")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def load_gold_fixture(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_pdf_bundle(path: Path) -> SiteSchematicBundle:
    return build_site_schematic_bundle_from_router_input(
        RouterInput(doc_id=path.stem, filename=path.name, mime_type="application/pdf", metadata={"path": str(path)}),
        source_modality="site_schematic_pdf",
    )


def build_bundle_corpus(bundle: SiteSchematicBundle) -> tuple[CorpusEntry, ...]:
    rows: list[CorpusEntry] = []

    def add(kind: str, text: str) -> None:
        cleaned = _clean(text)
        if not cleaned:
            return
        rows.append(CorpusEntry(kind=kind, text=cleaned, normalized=_norm(cleaned), tokens=_tokens(cleaned)))

    for page in bundle.pages:
        add("page", f"{page.sheet_number} {page.sheet_title} {page.sheet_type} {' '.join(page.zones)}")
    for region in bundle.regions:
        add("region", f"{region.kind} {region.text}")
    for row in bundle.legend_entries:
        add("legend", f"{row.label} {row.description} {row.symbol_token} {row.primitive_kind}")
    for row in bundle.abbreviations:
        add("abbreviation", f"{row.token} {row.meaning}")
    for row in bundle.outlet_type_definitions:
        add(
            "outlet_definition",
            " ".join(
                part
                for part in (
                    row.label,
                    row.cable_type,
                    row.work_area_termination,
                    row.closet_termination,
                    row.mounting,
                    row.power_requirement,
                    row.remarks,
                )
                if part
            ),
        )
    for collection_name in (
        "note_clauses_structured",
        "mounting_rules",
        "termination_rules",
        "environmental_requirements",
        "grounding_requirements",
        "testing_requirements",
        "labeling_requirements",
        "responsibility_assignments",
        "cable_rules",
        "pathway_rules",
        "service_loop_requirements",
        "topology_segments",
    ):
        for row in getattr(bundle, collection_name):
            add(collection_name, getattr(row, "text", ""))
    for row in bundle.color_conventions:
        add("color", f"{row.color} {row.meaning}")
    for row in bundle.drawing_index_rows:
        add("drawing_index", f"{row.sheet_number} {row.sheet_title}")
    for row in bundle.rooms:
        add("room", row.label)
    for row in bundle.closets:
        add("closet", row.label)
    for row in bundle.racks:
        add("rack", row.label)
    for row in bundle.riser_edges:
        add("riser", f"{row.source_label} {row.target_label} {row.medium}")
    for row in bundle.symbol_instances:
        add("symbol", f"{row.token} {row.primitive_kind} {row.text}")
    for row in bundle.symbol_links:
        add("symbol_link", f"{row.symbol_token} {row.legend_label} {' '.join(row.related_note_clauses)} {row.room_label} {row.status}")
    return tuple(rows)


def best_fact_match(expected: str, corpus: Iterable[CorpusEntry]) -> FactMatch:
    expected_tokens = _tokens(expected)
    expected_norm = _clean(expected).lower()
    best_text: str | None = None
    best_score = 0.0
    for entry in corpus:
        if expected_norm and expected_norm in entry.text.lower():
            return FactMatch(expected=expected, matched=entry.text, score=1.0)
        if not expected_tokens:
            continue
        overlap = expected_tokens & entry.tokens
        if not overlap:
            continue
        coverage = len(overlap) / max(1, len(expected_tokens))
        if len(overlap) >= 3:
            coverage += 0.08
        if entry.kind in {"symbol", "symbol_link", "legend", "outlet_definition", "drawing_index"}:
            coverage += 0.03
        if coverage > best_score:
            best_score = min(1.0, coverage)
            best_text = entry.text
    return FactMatch(expected=expected, matched=best_text, score=round(best_score, 4))


def score_facts(bundle: SiteSchematicBundle, facts: Iterable[str]) -> tuple[float, tuple[FactMatch, ...]]:
    corpus = build_bundle_corpus(bundle)
    matches = tuple(best_fact_match(fact, corpus) for fact in facts)
    if not matches:
        return 1.0, ()
    coverage = sum(match.score for match in matches) / len(matches)
    return round(coverage, 4), matches


def _has_required_statuses(bundle: SiteSchematicBundle, route_id: str) -> bool:
    statuses = {row.status for row in bundle.note_clauses_structured}
    if route_id == "wireless_ap_heavy_telecom_packet":
        return "stated" in statuses and ("owner_furnished" in statuses or "coordination_required" in statuses)
    # Low-voltage packets can satisfy this contract with any three review-aware statuses.
    return "stated" in statuses and len(statuses & {"coordination_required", "field_verify_required", "approximate", "owner_furnished"}) >= 2


def _required_region_match(bundle: SiteSchematicBundle, route_id: str) -> bool:
    by_page: dict[int, set[str]] = {}
    for region in bundle.regions:
        by_page.setdefault(region.page_index, set()).add(region.kind)
    if route_id == "wireless_ap_heavy_telecom_packet":
        return {"title_block", "revision_block", "legend_block", "abbreviation_block", "notes_spec_block", "plan_body_block"} <= by_page.get(1, set())
    return {"title_block", "revision_block", "notes_spec_block", "plan_body_block"} <= by_page.get(1, set()) and {"legend_block", "abbreviation_block"} <= by_page.get(2, set())


def _minimum_output_keys_match(bundle: SiteSchematicBundle, gold: dict[str, Any]) -> bool:
    summary = bundle.summary()
    mapping = {
        "typed_pages": lambda: summary["typed_pages"] == summary["page_count"],
        "page_regions": lambda: summary["regions"] > 0,
        "legend_entries": lambda: summary["legend_entries"] > 0,
        "abbreviation_entries": lambda: summary["abbreviations"] > 0,
        "outlet_type_definitions": lambda: summary["outlet_type_definitions"] > 0,
        "device_definition_rows": lambda: summary["legend_entries"] > 0 and summary["outlet_type_definitions"] > 0,
        "plan_symbol_instances": lambda: summary["symbol_instances"] > 0,
        # Low-voltage sheets can legitimately surface unresolved/weak links in early passes.
        "symbol_links": lambda: summary["symbol_links"] > 0,
        "room_labels": lambda: summary["room_labels"] > 0,
        "closet_labels": lambda: len(bundle.closets) > 0 or any("idf" in row.label.lower() or "mdf" in row.label.lower() for row in bundle.rooms),
        "routing_notes": lambda: summary["pathway_rules"] > 0 or summary["termination_rules"] > 0,
        "riser_topology": lambda: len(bundle.riser_edges) > 0,
        "rack_bonding_details": lambda: len(bundle.racks) > 0 and summary["grounding_requirements"] > 0,
        "drawing_index_rows": lambda: summary["drawing_index_rows"] > 0,
        "equipment_room_objects": lambda: len(bundle.racks) > 0 or any(page.sheet_type == "equipment_room_layout" for page in bundle.pages),
        "grounding_objects": lambda: summary["grounding_requirements"] > 0,
        "installation_detail_objects": lambda: any(page.sheet_type == "installation_detail" for page in bundle.pages),
    }
    required = gold.get("packet_expectations", {}).get("minimum_outputs", [])
    return all(mapping[key]() for key in required if key in mapping)


def _check_color_pairs(bundle: SiteSchematicBundle, required_pairs: Iterable[tuple[str, str]]) -> bool:
    existing = [(row.color.lower(), _clean(row.meaning).lower()) for row in bundle.color_conventions]
    for color, meaning in required_pairs:
        expected_tokens = _tokens(meaning)
        matched = False
        for row_color, row_meaning in existing:
            if color != row_color:
                continue
            meaning_tokens = _tokens(row_meaning)
            overlap = len(expected_tokens & meaning_tokens) / max(1, len(expected_tokens))
            if overlap >= 0.4 or meaning in row_meaning:
                matched = True
                break
        if not matched:
            return False
    return True


def _graph_expectations_match(bundle: SiteSchematicBundle, route_id: str) -> bool:
    relations = {edge.relation for edge in bundle.graph.edges}
    if route_id == "wireless_ap_heavy_telecom_packet":
        ap_links = [link for link in bundle.symbol_links if link.symbol_token in {"AP", "WAP"}]
        ap_note_text = " ".join(" ".join(link.related_note_clauses) for link in ap_links).lower()
        cctv_links = [link for link in bundle.symbol_links if link.symbol_token in {"CCTV", "FIC"}]
        cctv_notes = " ".join(" ".join(link.related_note_clauses) for link in cctv_links).lower()
        closets = " ".join(closet.label.lower() for closet in bundle.closets)
        grounding = " ".join(req.text.lower() for req in bundle.grounding_requirements)
        cctv_rule_text = " ".join(row.text.lower() for row in bundle.termination_rules + bundle.note_clauses_structured)
        return (
            any(link.status == "linked" for link in ap_links)
            and "slack" in ap_note_text
            and "patch panel" in ap_note_text
            and any(note.status == "owner_furnished" for note in bundle.note_clauses_structured)
            and ("cctv" in cctv_notes or "camera" in cctv_notes or "cctv" in cctv_rule_text)
            and {"matches_legend", "related_note", "routed_to", "grounded_by", "homeruns_to"} <= relations
            and "idf" in closets
            and "mdf" in closets
            and "rack" in grounding
        )
    wireless_node_linked = any(link.status == "linked" and link.symbol_token == "WN" for link in bundle.symbol_links)
    admin_term = any("admin patch panel" in rule.text.lower() for rule in bundle.termination_rules) or any("dedicated admin patch panel" in row.remarks.lower() or "dedicated admin patch panel" in row.closet_termination.lower() for row in bundle.outlet_type_definitions)
    pos_term = any("pos patch panel" in rule.text.lower() for rule in bundle.termination_rules) or any("dedicated pos patch panel" in row.remarks.lower() or "dedicated pos patch panel" in row.closet_termination.lower() for row in bundle.outlet_type_definitions)
    roof_note = " ".join(row.text.lower() for row in list(bundle.pathway_rules) + list(bundle.note_clauses_structured))
    grounding = " ".join(req.text.lower() for req in bundle.grounding_requirements)
    return (
        wireless_node_linked
        and admin_term
        and pos_term
        and {"matches_legend", "grounded_by", "homeruns_to"} <= relations
        and "tgb" in grounding
        and "tmgb" in grounding
        and (("satellite" in roof_note or "dish" in roof_note) and "weatherhead" in roof_note and "pull string" in roof_note)
    )


def exact_anchor_checks(bundle: SiteSchematicBundle, route_id: str) -> dict[str, bool]:
    if route_id == "wireless_ap_heavy_telecom_packet":
        blue_ok = any(
            row.color.lower() == "blue" and any(token in row.meaning.lower() for token in ("lan", "data cable", "data cables"))
            for row in bundle.color_conventions
        )
        return {
            "wap_20ft_slack": any("20'" in row.text or "20 feet" in row.text.lower() for row in bundle.service_loop_requirements),
            "wap_dedicated_patch_panel": any("patch panel" in row.text.lower() and "wap" in row.text.lower() for row in bundle.termination_rules),
            "owner_provided_wap": any(row.status == "owner_furnished" for row in bundle.note_clauses_structured),
            "jack_color_conventions": _check_color_pairs(bundle, (("red", "wireless"), ("green", "camera"), ("black", "wall phones"))) and blue_ok,
        }
    return {
        "environment_70f_60rh": any("70" in row.text and "rh" in row.text.lower() for row in bundle.environmental_requirements),
        "tgb_tmgb_present": any("tgb" in row.text.lower() for row in bundle.grounding_requirements) and any("tmgb" in row.text.lower() for row in bundle.grounding_requirements),
        "site_survey_responsibility": any("site survey" in row.text.lower() for row in bundle.responsibility_assignments),
        "color_cables": _check_color_pairs(bundle, (("blue", "all data system cable"), ("gray", "guestroom voice cable"), ("yellow", "wireless node cable"))),
    }


def build_gold_scorecard(bundle: SiteSchematicBundle, gold: dict[str, Any]) -> GoldScorecard:
    expected_pages = gold["packet_expectations"]["page_count"]
    expected_sheet_types = gold["packet_expectations"]["sheet_type_counts"]
    route_id = gold["route_id"]
    critical_sections: dict[str, float] = {}
    unmatched_examples: dict[str, tuple[str, ...]] = {}
    for key, value in gold.items():
        if not key.startswith("critical_") or not isinstance(value, list):
            continue
        coverage, matches = score_facts(bundle, value)
        critical_sections[key] = coverage
        unmatched_examples[key] = tuple(match.expected for match in matches if not match.passed)[:5]
    return GoldScorecard(
        route_id=route_id,
        page_count_match=bundle.page_count == expected_pages,
        typed_pages_match=bundle.typed_pages == expected_pages,
        sheet_type_counts_match=dict(bundle.sheet_type_counts) == dict(expected_sheet_types),
        region_presence_match=_required_region_match(bundle, route_id),
        minimum_output_keys_match=_minimum_output_keys_match(bundle, gold),
        legality_status_match=_has_required_statuses(bundle, route_id),
        graph_expectations_match=_graph_expectations_match(bundle, route_id),
        critical_sections=critical_sections,
        exact_anchor_checks=exact_anchor_checks(bundle, route_id),
        unmatched_examples=unmatched_examples,
    )
