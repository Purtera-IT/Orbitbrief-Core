from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.site_schematic.core import build_site_schematic_bundle_from_router_input


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export canonical page sections from site-schematic bundle output."
    )
    parser.add_argument("--pdf", required=True, help="Absolute or relative path to source PDF.")
    parser.add_argument("--page", type=int, default=1, help="1-indexed page to inspect.")
    parser.add_argument("--out", required=True, help="Output JSON path.")
    parser.add_argument(
        "--doc-id",
        default="",
        help="Optional router doc_id override. Defaults to PDF stem.",
    )
    return parser.parse_args()


def _build_payload(*, bundle_dict: dict[str, Any], page_index: int, pdf_path: Path) -> dict[str, Any]:
    pages = bundle_dict.get("pages", [])
    page_row = next((row for row in pages if int(row.get("page_index", 0)) == page_index), {})
    page_sections = [
        row
        for row in bundle_dict.get("page_sections", [])
        if int(row.get("page_index", 0)) == page_index
    ]
    drawing_rows = [
        row
        for row in bundle_dict.get("drawing_index_rows", [])
        if int(row.get("page_index", 0)) == page_index
    ]
    note_rows = [
        row
        for row in bundle_dict.get("note_clauses_structured", [])
        if int(row.get("page_index", 0)) == page_index
    ]
    summary = bundle_dict.get("summary", {})
    model_registry = bundle_dict.get("model_registry", {})
    section_detector = model_registry.get("section_detector", {}) if isinstance(model_registry, dict) else {}
    return {
        "pdf": str(pdf_path),
        "page_index": page_index,
        "source_modality": bundle_dict.get("source_modality", ""),
        "sheet_type": page_row.get("sheet_type", ""),
        "sheet_title": page_row.get("sheet_title", ""),
        "section_detector_mode": summary.get("section_detector_mode", ""),
        "section_detector": section_detector,
        "page_sections_count": len(page_sections),
        "drawing_index_rows_count": len(drawing_rows),
        "note_clauses_count": len(note_rows),
        "page_sections": page_sections,
        "drawing_index_rows": drawing_rows,
        "note_clauses_structured": note_rows,
    }


def main() -> None:
    args = _parse_args()
    pdf_path = Path(args.pdf).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    doc_id = str(args.doc_id or "").strip() or pdf_path.stem
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    router_input = RouterInput(
        doc_id=doc_id,
        filename=str(pdf_path),
        mime_type="application/pdf",
        metadata={"path": str(pdf_path)},
    )
    bundle = build_site_schematic_bundle_from_router_input(router_input, source_modality="site_schematic_pdf")
    payload = _build_payload(bundle_dict=bundle.to_dict(), page_index=max(1, int(args.page)), pdf_path=pdf_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()

