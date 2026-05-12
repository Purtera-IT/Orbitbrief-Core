from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


NOISE_PATTERNS = (
    re.compile(r"\bplotted\b", re.IGNORECASE),
    re.compile(r"\buser:\b", re.IGNORECASE),
    re.compile(r"\bissued for construction\b", re.IGNORECASE),
    re.compile(r"\bproject requirements notes", re.IGNORECASE),
    re.compile(r"\bmatt mitchell\b", re.IGNORECASE),
    re.compile(r"\bchambray\b", re.IGNORECASE),
)


@dataclass
class CanonicalItem:
    seq: int
    page_index: int
    lane: str
    text: str
    source_path: str
    bbox: list[float] | None
    confidence: float


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def _looks_like_noise(text: str) -> bool:
    if not text:
        return True
    t = text.strip()
    if len(t) < 3:
        return True
    if len(re.sub(r"[A-Za-z0-9]", "", t)) > len(t) * 0.5:
        return True
    return any(p.search(t) for p in NOISE_PATTERNS)


def _anchor(bbox: list[float] | None) -> tuple[float, float]:
    if isinstance(bbox, list) and len(bbox) == 4:
        return float(bbox[1]), float(bbox[0])
    return 1e9, 1e9


def _add(items: list[dict[str, Any]], lane: str, text: str, source: str, bbox: list[float] | None, confidence: float) -> None:
    cleaned = (text or "").strip()
    if _looks_like_noise(cleaned):
        return
    items.append(
        {
            "ordinal": len(items),
            "lane": lane,
            "text": cleaned,
            "source_path": source,
            "bbox": bbox,
            "confidence": float(confidence),
            "anchor": _anchor(bbox),
        }
    )


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Stable dedupe by normalized text, keeping first top-ordered instance.
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in items:
        key = _norm(row["text"])
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def build_page_stream(packet_dir: Path, page_index: int) -> list[CanonicalItem]:
    sheet_inventory = _load(packet_dir / "sheet_inventory.json")
    sheet_type = "unknown"
    for row in sheet_inventory:
        if int(row.get("page_index", -1)) == page_index:
            sheet_type = str(row.get("sheet_type", "unknown"))
            break

    legend = _load(packet_dir / "legend_and_outlet_semantics.json")
    tables = _load(packet_dir / "universal_tables.json")
    notes = _load(packet_dir / "notes_and_rules.json")
    labels = _load(packet_dir / "plan_text_labels.json")

    items: list[dict[str, Any]] = []

    # Prefer structured note lane for universal readability.
    for i, row in enumerate(notes.get("note_clauses_structured", [])):
        if row.get("page_index") != page_index:
            continue
        _add(
            items,
            "note_clause",
            str(row.get("text", "")),
            f"notes_and_rules.note_clauses_structured[{i}]",
            row.get("bbox"),
            row.get("confidence", 0.0) or 0.0,
        )

    # Include rule lanes.
    for key in (
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
    ):
        for i, row in enumerate(notes.get(key, [])):
            if row.get("page_index") != page_index:
                continue
            _add(
                items,
                key,
                str(row.get("text", "")),
                f"notes_and_rules.{key}[{i}]",
                row.get("bbox"),
                row.get("confidence", 0.0) or 0.0,
            )

    # Add tables/drawing-index only where those lanes should dominate.
    allow_table_lanes = sheet_type not in {"notes_spec"}
    if allow_table_lanes:
        for ti, table in enumerate(tables.get("tables", [])):
            if table.get("page_index") != page_index:
                continue
            table_bbox = table.get("bbox")
            for ri, row in enumerate(table.get("rows", [])):
                _add(
                    items,
                    f"table_row:{table.get('table_kind', 'unknown')}",
                    str(row.get("raw_text_joined", "")),
                    f"universal_tables.tables[{ti}].rows[{ri}]",
                    row.get("bbox") or table_bbox,
                    table.get("confidence", 0.0) or 0.0,
                )

        for i, row in enumerate(legend.get("drawing_index_rows", [])):
            if row.get("page_index") != page_index:
                continue
            sheet_num = str(row.get("sheet_number", "")).strip()
            sheet_title = str(row.get("sheet_title", "")).strip()
            joined = f"{sheet_num} {sheet_title}".strip()
            _add(
                items,
                "drawing_index",
                joined,
                f"legend_and_outlet_semantics.drawing_index_rows[{i}]",
                row.get("bbox"),
                row.get("confidence", 0.0) or 0.0,
            )

    # Plan labels (room/rack/outlet/symbol text).
    for key, text_key in (
        ("rooms", "label"),
        ("closets", "label"),
        ("racks", "label"),
        ("device_instances", "text"),
        ("outlet_instances", "text"),
        ("symbol_instances", "text"),
    ):
        for i, row in enumerate(labels.get(key, [])):
            if row.get("page_index") != page_index:
                continue
            _add(
                items,
                key,
                str(row.get(text_key, "") or row.get("token", "")),
                f"plan_text_labels.{key}[{i}]",
                row.get("bbox"),
                row.get("confidence", 0.0) or 0.0,
            )

    # Top-to-bottom ordering, then stable dedupe.
    items.sort(key=lambda r: (r["anchor"][0], r["anchor"][1], r["ordinal"]))
    items = _dedupe(items)

    out: list[CanonicalItem] = []
    for i, row in enumerate(items, start=1):
        out.append(
            CanonicalItem(
                seq=i,
                page_index=page_index,
                lane=row["lane"],
                text=row["text"],
                source_path=row["source_path"],
                bbox=row["bbox"],
                confidence=row["confidence"],
            )
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate clean OrbitBrief extraction stream.")
    parser.add_argument("--packet-dir", required=True, help="Path to parser_full_extraction_corpus/<packet_id>")
    parser.add_argument("--page-index", type=int, required=True, help="1-based page index")
    parser.add_argument("--output-json", required=True, help="Output JSON path")
    parser.add_argument("--output-md", required=True, help="Output markdown path")
    args = parser.parse_args()

    packet_dir = Path(args.packet_dir)
    page_index = int(args.page_index)
    out_json = Path(args.output_json)
    out_md = Path(args.output_md)

    stream = build_page_stream(packet_dir, page_index)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps([asdict(x) for x in stream], indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        f"# Clean OrbitBrief Stream (Page {page_index})",
        "",
        f"- packet_dir: `{packet_dir}`",
        f"- items: `{len(stream)}`",
        "",
        "| seq | lane | text | source_path |",
        "|---:|---|---|---|",
    ]
    for row in stream:
        text = row.text.replace("|", " ").replace("\n", " ")
        if len(text) > 220:
            text = text[:217] + "..."
        lines.append(f"| {row.seq} | {row.lane} | {text} | `{row.source_path}` |")
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out_json}")
    print(f"Wrote {out_md}")
    print(f"Items: {len(stream)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
