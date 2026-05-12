from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .gold_eval import build_pdf_bundle
from .phase_d_universality_eval import (
    _bundle_phase_a_metrics,
    _bundle_phase_b_metrics,
    _bundle_phase_c_metrics,
    _native_only_eval_profile,
    _packet_runtime_rows,
)

ARTIFACT_ROOT = Path(__file__).resolve().parents[2] / "compiled_artifacts" / "parser_full_extraction_corpus"
_TABLE_FAMILIES = {
    "drawing_index",
    "symbol_legend",
    "abbreviation_matrix",
    "outlet_definition",
    "schedule",
    "component_spec",
    "manufacturer_part_table",
    "responsibility_matrix",
    "generic_grid",
    "embedded_detail_schedule",
}
_DETAIL_CUES = ("detail", "riser", "rack", "equipment", "callout", "grounding", "topology")
_NOTE_CUES = ("note", "spec", "requirement", "provided")
_TABLE_CUES = ("schedule", "legend", "index", "abbreviation", "matrix", "table", "sheet title")
_ROOM_CUES = ("room", "closet", "mdf", "idf", "corridor", "office", "conference")
_WORD_RE = re.compile(r"[a-z0-9]{2,}", flags=re.IGNORECASE)
_NOTE_CUE_RE = re.compile(r"(?i)\b(?:general notes?|keyed notes?|notes?|spec(?:ification)?s?|requirements?)\b")
_FINAL_TAIL_TARGETS = {
    ("lv_a_aspen_house_telecom_intercom_risers", 59),
    ("tc_b_seele_es_refresh_dwgs", 54),
    ("tc_b_seele_es_refresh_dwgs", 99),
    ("tc_b_seele_es_refresh_dwgs", 100),
}


def _token_set(text: str) -> set[str]:
    return {tok.lower() for tok in _WORD_RE.findall(text or "")}


def _has_note_cue(text: str) -> bool:
    lowered = (text or "").lower()
    if "keynotes" in lowered and not any(token in lowered for token in ("general note", "keyed note", "project requirement", "spec")):
        return False
    return bool(_NOTE_CUE_RE.search(lowered))


def _json_dump(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _jsonl_dump(path: Path, rows: list[dict[str, Any]]) -> None:
    data = "\n".join(json.dumps(row, ensure_ascii=True) for row in rows)
    path.write_text(data + ("\n" if data else ""), encoding="utf-8")


def _row_to_dict(row: Any) -> dict[str, Any]:
    if hasattr(row, "to_dict"):
        return row.to_dict()
    if hasattr(row, "__dataclass_fields__"):
        return asdict(row)
    if isinstance(row, dict):
        return dict(row)
    return {"value": str(row)}


def _page_gap_record(bundle: Any, page_index: int) -> dict[str, Any]:
    page_obj = next((row for row in bundle.pages if row.page_index == page_index), None)
    page_obs = next((row for row in bundle.page_observations if row.page_index == page_index), None)
    page_text = page_obs.page_text if page_obs else ""
    lowered = (page_text or "").lower()
    page_tables = [row for row in bundle.universal_tables if row.page_index == page_index]
    page_legend = [row for row in bundle.legend_entries if row.page_index == page_index]
    page_abbr = [row for row in bundle.abbreviations if row.page_index == page_index]
    page_draw = [row for row in bundle.drawing_index_rows if row.page_index == page_index]
    page_notes = [row for row in bundle.note_clauses_structured if row.page_index == page_index]
    page_scoped = [row for row in bundle.scoped_note_links if row.page_index == page_index]
    page_rooms = [row for row in bundle.rooms if row.page_index == page_index]
    page_closets = [row for row in bundle.closets if row.page_index == page_index]
    page_racks = [row for row in bundle.racks if row.page_index == page_index]
    page_outcomes = [row for row in bundle.symbol_resolution_outcomes if row.page_index == page_index]
    unresolved_symbols = [row for row in page_outcomes if row.status in {"unresolved", "detected_but_unmapped", "candidate_requires_review"}]

    classes: list[str] = []
    reasons: list[str] = []
    if any(token in lowered for token in _TABLE_CUES):
        if not page_tables and not (page_legend or page_abbr or page_draw):
            classes.append("table_legend_gap")
            reasons.append("table cues present but no universal table emitted")
    if _has_note_cue(lowered):
        if not page_notes and len(_token_set(page_text)) > 40:
            classes.append("text_only_gap")
            reasons.append("note/spec cues present but no structured note clause emitted")
        elif (
            sum(
                1
                for row in page_scoped
                if row.status != "scoped" and any(token in row.note_text.lower() for token in _DETAIL_CUES)
            )
            >= 2
        ):
            classes.append("locality_scope_gap")
            reasons.append("multiple detail-local scoped note links remain unresolved")
    if any(token in lowered for token in _DETAIL_CUES):
        if unresolved_symbols and not classes:
            classes.append("graphics_only_gap")
            reasons.append("detail/riser cues present; remaining unresolved items are symbol/diagram centric")
    if unresolved_symbols and any(kind in classes for kind in ("text_only_gap", "table_legend_gap", "locality_scope_gap")):
        classes.append("mixed_gap")
        reasons.append("both parser text and graphics-related unresolved items exist")
    if not classes and unresolved_symbols:
        classes.append("graphics_only_gap")
        reasons.append("remaining unresolved objects are symbol/linework related")

    if not classes:
        classes = ["none"]
    parser_text = {
        "page_index": page_index,
        "sheet_number": page_obj.sheet_number if page_obj else "",
        "sheet_title": page_obj.sheet_title if page_obj else "",
        "sheet_type": page_obj.sheet_type if page_obj else "unknown",
        "gap_classes": classes,
        "reasons": reasons,
        "table_count": len(page_tables),
        "note_clause_count": len(page_notes),
        "scoped_note_count": len(page_scoped),
        "room_label_count": len(page_rooms) + len(page_closets) + len(page_racks),
        "unresolved_symbol_count": len(unresolved_symbols),
    }
    return parser_text


def _bundle_metrics(bundle: Any, expected_tables: tuple[str, ...], expected_profiles: tuple[str, ...], expected_archetypes: tuple[str, ...]) -> dict[str, float]:
    a = _bundle_phase_a_metrics(bundle, expected_archetypes)
    b = _bundle_phase_b_metrics(bundle, expected_tables)
    c = _bundle_phase_c_metrics(bundle, expected_profiles)
    page_text_tokens: set[str] = set()
    for obs in bundle.page_observations:
        page_text_tokens.update(_token_set(obs.page_text))
    extracted_tokens: set[str] = set()
    for coll in (
        bundle.note_clauses_structured,
        bundle.legend_entries,
        bundle.abbreviations,
        bundle.drawing_index_rows,
        bundle.rooms,
        bundle.closets,
        bundle.racks,
        bundle.outlet_type_definitions,
    ):
        for row in coll:
            raw = " ".join(str(value) for value in _row_to_dict(row).values() if isinstance(value, (str, int, float)))
            extracted_tokens.update(_token_set(raw))
    for coll in (bundle.observations, bundle.regions, bundle.detail_regions, bundle.subregions, bundle.pseudo_pages):
        for row in coll:
            extracted_tokens.update(_token_set(str(_row_to_dict(row).get("text", ""))))
    for table in bundle.universal_tables:
        for row in table.rows:
            extracted_tokens.update(_token_set(row.raw_text_joined))
            for cell in row.cells:
                extracted_tokens.update(_token_set(cell.raw_text))
    visible_text_coverage = round(len(page_text_tokens & extracted_tokens) / max(1, len(page_text_tokens)), 4)
    notes_pages = [obs for obs in bundle.page_observations if _has_note_cue(obs.page_text or "")]
    notes_hit = sum(
        1 for obs in notes_pages if any(row.page_index == obs.page_index for row in bundle.note_clauses_structured)
    )
    table_pages = [obs for obs in bundle.page_observations if any(tok in (obs.page_text or "").lower() for tok in _TABLE_CUES)]
    table_hit = sum(
        1 for obs in table_pages if any(row.page_index == obs.page_index for row in bundle.universal_tables)
    )
    page_text_by_index = {obs.page_index: (obs.page_text or "").lower() for obs in bundle.page_observations}
    room_pages = [
        page
        for page in bundle.pages
        if page.sheet_type in {"floorplan_overall", "floorplan_detail", "equipment_room_layout"}
        and any(token in page_text_by_index.get(page.page_index, "") for token in _ROOM_CUES)
    ]
    room_hit = sum(
        1
        for page in room_pages
        if any(row.page_index == page.page_index for row in (*bundle.rooms, *bundle.closets, *bundle.racks))
    )
    gap_rows = [_page_gap_record(bundle, page.page_index) for page in bundle.pages]
    text_gap = sum(1 for row in gap_rows if "text_only_gap" in row["gap_classes"] or "table_legend_gap" in row["gap_classes"])
    graphics_gap = sum(1 for row in gap_rows if "graphics_only_gap" in row["gap_classes"])
    metrics = {
        "visible_text_coverage_estimate": visible_text_coverage,
        "legend_table_coverage_rate": round(table_hit / max(1, len(table_pages)), 4),
        "note_spec_coverage_rate": round(notes_hit / max(1, len(notes_pages)), 4),
        "semantic_lineage_coverage_rate": round(
            sum(1 for row in bundle.semantic_lineage_refs if row.source_table_id and row.source_row_id and row.source_cell_ids)
            / max(1, len(bundle.semantic_lineage_refs)),
            4,
        ),
        "room_label_coverage_rate": round(room_hit / max(1, len(room_pages)), 4),
        "unresolved_text_only_gap_rate": round(text_gap / max(1, bundle.page_count), 4),
        "graphics_only_gap_rate": round(graphics_gap / max(1, bundle.page_count), 4),
        "phase_a_sheet_type_accuracy": a["sheet_type_accuracy"],
        "phase_b_required_table_kind_coverage": b["required_table_kind_coverage"],
        "phase_c_locality_provenance_rate": c["locality_provenance_rate"],
    }
    ready = (
        metrics["visible_text_coverage_estimate"] >= 0.85
        and metrics["legend_table_coverage_rate"] >= 0.9
        and metrics["note_spec_coverage_rate"] >= 0.9
        and metrics["semantic_lineage_coverage_rate"] >= 0.95
        and metrics["unresolved_text_only_gap_rate"] <= 0.1
        and metrics["phase_b_required_table_kind_coverage"] >= 0.95
    )
    metrics["parser_ready_for_vision_handoff"] = 1.0 if ready else 0.0
    return metrics


def run_parser_full_extraction_corpus(*, artifact_root: Path | None = None) -> dict[str, Any]:
    root = artifact_root or ARTIFACT_ROOT
    root.mkdir(parents=True, exist_ok=True)
    runtimes = _packet_runtime_rows()
    corpus_docs: list[dict[str, Any]] = []

    with _native_only_eval_profile():
        for runtime in runtimes:
            if not runtime.downloaded or not runtime.pdf_path.exists():
                continue
            packet_dir = root / runtime.packet_id
            packet_dir.mkdir(parents=True, exist_ok=True)
            schema = {}
            if runtime.schema_path and runtime.schema_path.exists():
                schema = json.loads(runtime.schema_path.read_text(encoding="utf-8"))
            expected_tables = tuple(schema.get("expected_table_families", ()))
            expected_profiles = tuple(schema.get("expected_region_profiles", ()))
            expected_archetypes = tuple(schema.get("expected_archetypes", ()))
            bundle = build_pdf_bundle(runtime.pdf_path)
            metrics = _bundle_metrics(bundle, expected_tables, expected_profiles, expected_archetypes)

            sheet_inventory = [
                {
                    "page_index": page.page_index,
                    "sheet_id": page.sheet_number,
                    "sheet_title": page.sheet_title,
                    "sheet_type": page.sheet_type,
                    "page_label": page.page_label,
                    "zones": list(page.zones),
                }
                for page in bundle.pages
            ]
            page_text_rows = [
                {
                    "page_index": obs.page_index,
                    "sheet_number": next((p.sheet_number for p in bundle.pages if p.page_index == obs.page_index), ""),
                    "sheet_title": next((p.sheet_title for p in bundle.pages if p.page_index == obs.page_index), ""),
                    "sheet_type": next((p.sheet_type for p in bundle.pages if p.page_index == obs.page_index), "unknown"),
                    "provider": obs.provider,
                    "source_mode": obs.source_mode,
                    "text": obs.page_text,
                    "layout_block_count": len(obs.layout_blocks),
                    "table_block_count": len(obs.table_blocks),
                }
                for obs in bundle.page_observations
            ]
            notes_and_rules = {
                "scoped_note_links": [_row_to_dict(row) for row in bundle.scoped_note_links],
                "note_clauses_structured": [_row_to_dict(row) for row in bundle.note_clauses_structured],
                "mounting_rules": [_row_to_dict(row) for row in bundle.mounting_rules],
                "termination_rules": [_row_to_dict(row) for row in bundle.termination_rules],
                "environmental_requirements": [_row_to_dict(row) for row in bundle.environmental_requirements],
                "grounding_requirements": [_row_to_dict(row) for row in bundle.grounding_requirements],
                "testing_requirements": [_row_to_dict(row) for row in bundle.testing_requirements],
                "labeling_requirements": [_row_to_dict(row) for row in bundle.labeling_requirements],
                "responsibility_assignments": [_row_to_dict(row) for row in bundle.responsibility_assignments],
                "cable_rules": [_row_to_dict(row) for row in bundle.cable_rules],
                "pathway_rules": [_row_to_dict(row) for row in bundle.pathway_rules],
                "service_loop_requirements": [_row_to_dict(row) for row in bundle.service_loop_requirements],
            }
            universal_tables = {
                "table_count": len(bundle.universal_tables),
                "table_kinds": sorted({row.table_kind for row in bundle.universal_tables}),
                "tables": [_row_to_dict(row) for row in bundle.universal_tables],
                "semantic_lineage_refs": [_row_to_dict(row) for row in bundle.semantic_lineage_refs],
            }
            legend_semantics = {
                "legend_entries": [_row_to_dict(row) for row in bundle.legend_entries],
                "abbreviations": [_row_to_dict(row) for row in bundle.abbreviations],
                "outlet_definitions": [_row_to_dict(row) for row in bundle.outlet_type_definitions],
                "drawing_index_rows": [_row_to_dict(row) for row in bundle.drawing_index_rows],
            }
            plan_labels = {
                "rooms": [_row_to_dict(row) for row in bundle.rooms],
                "closets": [_row_to_dict(row) for row in bundle.closets],
                "racks": [_row_to_dict(row) for row in bundle.racks],
                "device_instances": [_row_to_dict(row) for row in bundle.device_instances],
                "outlet_instances": [_row_to_dict(row) for row in bundle.outlet_instances],
                "riser_edges": [_row_to_dict(row) for row in bundle.riser_edges],
                "topology_segments": [_row_to_dict(row) for row in bundle.topology_segments],
                "symbol_instances": [_row_to_dict(row) for row in bundle.symbol_instances],
                "symbol_links": [_row_to_dict(row) for row in bundle.symbol_links],
            }
            graph_summary = {
                "bundle_summary": bundle.summary(),
                "graph_summary": bundle.graph.summary(),
                "reasoning_findings": [_row_to_dict(row) for row in bundle.reasoning_findings],
                "consistency_checks": [_row_to_dict(row) for row in bundle.consistency_checks],
                "contradiction_flags": [_row_to_dict(row) for row in bundle.contradiction_flags],
            }
            page_gaps = [
                {
                    **_page_gap_record(bundle, page.page_index),
                    "packet_id": runtime.packet_id,
                }
                for page in bundle.pages
            ]
            unresolved_items = {
                "symbol_resolution_outcomes_unresolved": [
                    _row_to_dict(row)
                    for row in bundle.symbol_resolution_outcomes
                    if row.status in {"unresolved", "detected_but_unmapped", "candidate_requires_review", "conflicting"}
                ],
                "scoped_note_links_unresolved": [_row_to_dict(row) for row in bundle.scoped_note_links if row.status != "scoped"],
                "page_gap_records": page_gaps,
            }
            hard_pages = sorted(
                (
                    {
                        "page_index": page.page_index,
                        "sheet_id": page.sheet_number,
                        "sheet_title": page.sheet_title,
                        "sheet_type": page.sheet_type,
                        "layout_block_count": len(next((obs.layout_blocks for obs in bundle.page_observations if obs.page_index == page.page_index), ())),
                        "table_count": len([row for row in bundle.universal_tables if row.page_index == page.page_index]),
                        "note_clause_count": len([row for row in bundle.note_clauses_structured if row.page_index == page.page_index]),
                    }
                    for page in bundle.pages
                ),
                key=lambda row: (row["table_count"], row["layout_block_count"], row["note_clause_count"]),
                reverse=True,
            )[:8]
            gap_audit = {
                "document_id": runtime.packet_id,
                "page_gaps": page_gaps,
                "hard_pages_visual_audit_candidates": hard_pages,
                "metrics": metrics,
            }
            doc_summary = {
                "document_id": runtime.packet_id,
                "role": runtime.role,
                "category": runtime.category,
                "pdf_path": str(runtime.pdf_path),
                "page_count": bundle.page_count,
                "typed_pages": bundle.typed_pages,
                "metrics": metrics,
                "table_kinds": sorted({row.table_kind for row in bundle.universal_tables if row.table_kind in _TABLE_FAMILIES}),
                "sheet_type_counts": dict(bundle.sheet_type_counts),
            }

            _json_dump(packet_dir / "document_summary.json", doc_summary)
            _json_dump(packet_dir / "sheet_inventory.json", sheet_inventory)
            _jsonl_dump(packet_dir / "page_text.jsonl", page_text_rows)
            _json_dump(packet_dir / "notes_and_rules.json", notes_and_rules)
            _json_dump(packet_dir / "universal_tables.json", universal_tables)
            _json_dump(packet_dir / "legend_and_outlet_semantics.json", legend_semantics)
            _json_dump(packet_dir / "plan_text_labels.json", plan_labels)
            _json_dump(packet_dir / "parser_graph_summary.json", graph_summary)
            _json_dump(packet_dir / "unresolved_items.json", unresolved_items)
            _json_dump(packet_dir / "gap_audit.json", gap_audit)
            (packet_dir / "document_summary.md").write_text(
                "\n".join(
                    [
                        f"# {runtime.packet_id}",
                        "",
                        f"- Category: `{runtime.category}`",
                        f"- Role: `{runtime.role}`",
                        f"- Pages: `{bundle.page_count}`",
                        f"- Typed pages: `{bundle.typed_pages}`",
                        f"- visible_text_coverage_estimate: `{metrics['visible_text_coverage_estimate']}`",
                        f"- legend_table_coverage_rate: `{metrics['legend_table_coverage_rate']}`",
                        f"- note_spec_coverage_rate: `{metrics['note_spec_coverage_rate']}`",
                        f"- semantic_lineage_coverage_rate: `{metrics['semantic_lineage_coverage_rate']}`",
                        f"- room_label_coverage_rate: `{metrics['room_label_coverage_rate']}`",
                        f"- unresolved_text_only_gap_rate: `{metrics['unresolved_text_only_gap_rate']}`",
                        f"- graphics_only_gap_rate: `{metrics['graphics_only_gap_rate']}`",
                        f"- parser_ready_for_vision_handoff: `{'true' if metrics['parser_ready_for_vision_handoff'] >= 1.0 else 'false'}`",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            corpus_docs.append(doc_summary)

    corpus_manifest = {
        "artifact_root": str(root),
        "document_count": len(corpus_docs),
        "documents": corpus_docs,
    }
    _json_dump(root / "corpus_manifest.json", corpus_manifest)
    avg = lambda key: round(sum(float(row["metrics"][key]) for row in corpus_docs) / max(1, len(corpus_docs)), 4)
    corpus_summary = {
        "document_count": len(corpus_docs),
        "visible_text_coverage_estimate_avg": avg("visible_text_coverage_estimate"),
        "legend_table_coverage_rate_avg": avg("legend_table_coverage_rate"),
        "note_spec_coverage_rate_avg": avg("note_spec_coverage_rate"),
        "semantic_lineage_coverage_rate_avg": avg("semantic_lineage_coverage_rate"),
        "room_label_coverage_rate_avg": avg("room_label_coverage_rate"),
        "unresolved_text_only_gap_rate_avg": avg("unresolved_text_only_gap_rate"),
        "graphics_only_gap_rate_avg": avg("graphics_only_gap_rate"),
        "parser_ready_for_vision_handoff_count": sum(1 for row in corpus_docs if row["metrics"]["parser_ready_for_vision_handoff"] >= 1.0),
        "parser_ready_for_vision_handoff_rate": round(
            sum(1 for row in corpus_docs if row["metrics"]["parser_ready_for_vision_handoff"] >= 1.0) / max(1, len(corpus_docs)),
            4,
        ),
    }
    tail_status: list[dict[str, Any]] = []
    for row in corpus_docs:
        packet_id = row["document_id"]
        gap_path = root / packet_id / "gap_audit.json"
        if not gap_path.exists():
            continue
        gap_payload = json.loads(gap_path.read_text(encoding="utf-8"))
        for rec in gap_payload.get("page_gaps", []):
            if (packet_id, rec.get("page_index")) not in _FINAL_TAIL_TARGETS:
                continue
            tail_status.append(
                {
                    "packet_id": packet_id,
                    "page_index": rec.get("page_index"),
                    "sheet_type": rec.get("sheet_type"),
                    "gap_classes": rec.get("gap_classes", []),
                    "reasons": rec.get("reasons", []),
                    "note_clause_count": rec.get("note_clause_count", 0),
                    "scoped_note_count": rec.get("scoped_note_count", 0),
                }
            )
    corpus_summary["final_text_tail_status"] = sorted(tail_status, key=lambda item: (item["packet_id"], item["page_index"]))
    _json_dump(root / "corpus_summary.json", corpus_summary)
    (root / "corpus_summary.md").write_text(
        "\n".join(
            [
                "# Parser Full Extraction Corpus Summary",
                "",
                f"- Documents parsed: `{corpus_summary['document_count']}`",
                f"- visible_text_coverage_estimate_avg: `{corpus_summary['visible_text_coverage_estimate_avg']}`",
                f"- legend_table_coverage_rate_avg: `{corpus_summary['legend_table_coverage_rate_avg']}`",
                f"- note_spec_coverage_rate_avg: `{corpus_summary['note_spec_coverage_rate_avg']}`",
                f"- semantic_lineage_coverage_rate_avg: `{corpus_summary['semantic_lineage_coverage_rate_avg']}`",
                f"- room_label_coverage_rate_avg: `{corpus_summary['room_label_coverage_rate_avg']}`",
                f"- unresolved_text_only_gap_rate_avg: `{corpus_summary['unresolved_text_only_gap_rate_avg']}`",
                f"- graphics_only_gap_rate_avg: `{corpus_summary['graphics_only_gap_rate_avg']}`",
                f"- parser_ready_for_vision_handoff_rate: `{corpus_summary['parser_ready_for_vision_handoff_rate']}`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    readiness = (
        "Parser is effectively complete for text/legend/table/note extraction across the corpus."
        if corpus_summary["unresolved_text_only_gap_rate_avg"] <= 0.1
        and corpus_summary["legend_table_coverage_rate_avg"] >= 0.9
        and corpus_summary["note_spec_coverage_rate_avg"] >= 0.9
        else "Parser still has notable text/table/locality gaps before a clean vision-only handoff."
    )
    (root / "corpus_readiness_for_vision.md").write_text(
        "\n".join(
            [
                "# Parser Readiness For Vision Handoff",
                "",
                readiness,
                "",
                "Primary remaining gap class should be graphics/schematic-only if parser text/table/locality rates are high.",
                f"- graphics_only_gap_rate_avg: `{corpus_summary['graphics_only_gap_rate_avg']}`",
                f"- unresolved_text_only_gap_rate_avg: `{corpus_summary['unresolved_text_only_gap_rate_avg']}`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "artifact_root": str(root),
        "corpus_summary": corpus_summary,
        "documents": corpus_docs,
    }


if __name__ == "__main__":
    result = run_parser_full_extraction_corpus()
    print(json.dumps(result["corpus_summary"], indent=2))
