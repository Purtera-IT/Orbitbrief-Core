from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from orbitbrief_core.parser.adapters.base import AbstractAdapter, AdapterInfo
from orbitbrief_core.parser.adapters.common import add_flag, extract_bytes, extract_path, extract_text, make_builder
from orbitbrief_core.parser.adapters.docx_common import (
    StructuredDocxHypothesis,
    build_deterministic_docx_hypothesis,
    reconcile_docx_hypotheses,
)
from orbitbrief_core.parser.adapters.providers.docx_structured_provider import extract_docx_structured_hypothesis
from orbitbrief_core.parser.adapters.text_common import extract_time_strings, infer_heading_level, normalize_text
from orbitbrief_core.parser.router import ParsePlan, RouterInput
from orbitbrief_core.parser.shared.types import ReviewCategory, ReviewSeverity

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NS = {"w": _W_NS}
_CONTACT_TABLE_HEADINGS = {"customer contacts", "purtera sales contacts", "sales contacts"}


@dataclass(frozen=True, slots=True)
class DocxBlock:
    block_kind: str
    text: str
    style_name: str | None
    level: int | None
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DocxParseConfig:
    flatten_tables: bool = True
    preserve_lists: bool = True
    fallback_to_text: bool = True
    allow_alternate_structure: bool = True


class DocxAdapter(AbstractAdapter):
    info = AdapterInfo(
        name="DocxAdapter",
        modality="docx",
        description="OOXML-aware DOCX adapter with section/list/table preservation.",
        optional_dependencies=("docx",),
    )

    def __init__(self, config: DocxParseConfig | None = None) -> None:
        self._config = config or DocxParseConfig()

    def parse(self, *, router_input: RouterInput, parse_plan: ParsePlan, compiled_pack: Any):
        builder = make_builder(router_input=router_input, parse_plan=parse_plan, compiled_pack=compiled_pack)
        root_section_id = builder.add_section(
            title="ROOT",
            section_path=("ROOT",),
            metadata=self._ensure_reconciliation_metadata({"synthetic": True, "adapter": "docx"}),
        )
        builder.set_section_root(root_section_id)

        deterministic_blocks = self._extract_blocks(router_input)
        if not deterministic_blocks:
            if self._config.fallback_to_text:
                text = normalize_text(extract_text(router_input))
                span_id = builder.add_span(
                    text=text,
                    normalized_text=text,
                    section_path=("ROOT",),
                    chronology_rank=0,
                    authority_score=0.65,
                    metadata=self._ensure_reconciliation_metadata({"kind": "docx_text_fallback"}),
                )
                builder.attach_span_to_section(span_id, root_section_id)
                add_flag(
                    builder,
                    severity=ReviewSeverity.WARNING,
                    category=ReviewCategory.AMBIGUITY,
                    message="DOCX structure unavailable; adapter fell back to flat text.",
                    span_id=span_id,
                    metadata={"adapter": "docx"},
                )
                return builder.build()
            raise RuntimeError("Unable to parse DOCX artifact and fallback disabled.")

        deterministic_hypothesis = build_deterministic_docx_hypothesis(deterministic_blocks)
        alternate_hypothesis: StructuredDocxHypothesis | None = None
        if self._config.allow_alternate_structure:
            alternate_hypothesis = extract_docx_structured_hypothesis(
                docx_path=extract_path(router_input),
                docx_bytes=extract_bytes(router_input),
            )
        reconciliation = reconcile_docx_hypotheses(primary=deterministic_hypothesis, alternate=alternate_hypothesis)
        add_flag(
            builder,
            severity=ReviewSeverity.INFO,
            category=ReviewCategory.QUALITY,
            message="DOCX structure reconciliation completed.",
            metadata={
                "adapter": "docx",
                "reconciliation_diagnostics": list(reconciliation.diagnostics),
                "winner_source": reconciliation.metadata.get("winner_source"),
            },
        )
        blocks = reconciliation.blocks

        section_stack: list[tuple[int, str, tuple[str, ...]]] = [(0, root_section_id, ("ROOT",))]
        chronology_rank = 0
        for block in blocks:
            block_metadata = self._ensure_reconciliation_metadata(dict(block.metadata))
            if block.role == "heading":
                level = block.heading_level or infer_heading_level(block.text)
                while section_stack and level <= section_stack[-1][0]:
                    section_stack.pop()
                parent_id, parent_path = section_stack[-1][1], section_stack[-1][2]
                section_path = parent_path + (block.text,)
                section_id = builder.add_section(
                    title=block.text,
                    section_path=section_path,
                    parent_section_id=parent_id,
                    metadata=self._ensure_reconciliation_metadata({"style": block.style_name, **block_metadata}),
                )
                section_stack.append((level, section_id, section_path))
                heading_span_id = builder.add_span(
                    text=block.text,
                    normalized_text=block.text.lower(),
                    section_path=section_path,
                    chronology_rank=chronology_rank,
                    authority_score=0.9,
                    metadata=self._ensure_reconciliation_metadata({"kind": "heading", **block_metadata}),
                )
                builder.attach_span_to_section(heading_span_id, section_id)
                chronology_rank += 1
                continue

            current_section_id, current_path = section_stack[-1][1], section_stack[-1][2]
            span_id = builder.add_span(
                text=block.text,
                normalized_text=block.text,
                section_path=current_path,
                chronology_rank=chronology_rank,
                authority_score=0.84 if block.role != "table_row" else 0.7,
                metadata={
                    "kind": block.role,
                    "style_name": block.style_name,
                    **block_metadata,
                    "list_level": block.list_level,
                    "table_group_id": block.table_group_id,
                    "section_hint": block.section_hint,
                },
            )
            builder.attach_span_to_section(span_id, current_section_id)
            if block.role == "table_row":
                add_flag(
                    builder,
                    severity=ReviewSeverity.INFO,
                    category=ReviewCategory.QUALITY,
                    message="DOCX table row flattened into narrative span pending dedicated table semantics.",
                    span_id=span_id,
                    metadata={"adapter": "docx"},
                )
            if extract_time_strings(block.text):
                add_flag(
                    builder,
                    severity=ReviewSeverity.INFO,
                    category=ReviewCategory.QUALITY,
                    message="DOCX block includes inline time cues.",
                    span_id=span_id,
                    metadata={"times": list(extract_time_strings(block.text))},
                )
            chronology_rank += 1
        return builder.build()

    @staticmethod
    def _ensure_reconciliation_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        metadata.setdefault("winner_source", "ooxml")
        metadata.setdefault("winner_hypothesis_id", "hypothesis:docx_ooxml")
        metadata.setdefault("reconciled", False)
        metadata.setdefault("reconciliation_reason_codes", [])
        metadata.setdefault("competing_sources", [])
        return metadata

    def _extract_blocks(self, router_input: RouterInput) -> tuple[DocxBlock, ...]:
        sdt_blocks = list(self._extract_sdt_blocks(router_input))
        try:
            from docx import Document as DocxDocument  # type: ignore
            from docx.document import Document as _DocumentType  # type: ignore
            from docx.oxml.table import CT_Tbl  # type: ignore
            from docx.oxml.text.paragraph import CT_P  # type: ignore
            from docx.table import Table  # type: ignore
            from docx.text.paragraph import Paragraph  # type: ignore
        except Exception:
            return tuple(sdt_blocks)

        path = extract_path(router_input)
        raw = extract_bytes(router_input)
        try:
            if raw is not None:
                document = DocxDocument(io.BytesIO(raw))
            elif path is not None:
                document = DocxDocument(str(path))
            else:
                return tuple(sdt_blocks)
        except Exception:
            return tuple(sdt_blocks)

        def iter_block_items(parent) -> Iterator[Any]:
            parent_elm = parent.element.body if isinstance(parent, _DocumentType) else parent._tc
            for child in parent_elm.iterchildren():
                if isinstance(child, CT_P):
                    yield Paragraph(child, parent)
                elif isinstance(child, CT_Tbl):
                    yield Table(child, parent)

        blocks: list[DocxBlock] = list(sdt_blocks)
        table_index = 0
        current_heading_text: str | None = None
        for element in iter_block_items(document):
            if element.__class__.__name__ == "Paragraph":
                paragraph_text = normalize_text(element.text or "").strip()
                if not paragraph_text:
                    continue
                style_name = getattr(getattr(element, "style", None), "name", None)
                level = self._heading_level_from_style(style_name)
                list_level = self._list_level_from_paragraph(element)
                metadata = {
                    "style_name": style_name,
                    "is_list": self._is_list_paragraph(element, style_name),
                    "list_level": list_level,
                }
                if level is not None:
                    blocks.append(DocxBlock("heading", paragraph_text, style_name, level, metadata))
                    current_heading_text = paragraph_text
                    continue
                if metadata["is_list"] and self._config.preserve_lists:
                    blocks.append(DocxBlock("bullet", paragraph_text, style_name, None, metadata))
                else:
                    blocks.append(DocxBlock("paragraph", paragraph_text, style_name, None, metadata))
            else:
                if not self._config.flatten_tables:
                    continue
                blocks.extend(
                    self._table_rows_to_blocks(
                        rows=self._table_rows_from_python_docx(element),
                        table_group_id=f"table:ooxml:body:{table_index:04d}",
                        section_label=current_heading_text,
                    )
                )
                table_index += 1
        return tuple(blocks)

    def _extract_sdt_blocks(self, router_input: RouterInput) -> tuple[DocxBlock, ...]:
        xml_root, styles = self._load_docx_xml(router_input)
        if xml_root is None:
            return ()
        body = xml_root.find(f"{{{_W_NS}}}body")
        if body is None:
            return ()
        blocks: list[DocxBlock] = []
        table_index = 0
        for child in list(body):
            if _local_name(child.tag) != "sdt":
                continue
            sdt_content = child.find(f"{{{_W_NS}}}sdtContent")
            if sdt_content is None:
                continue
            current_heading_text: str | None = None
            for inner in list(sdt_content):
                tag_name = _local_name(inner.tag)
                if tag_name == "p":
                    block = self._xml_paragraph_to_block(inner, styles=styles)
                    if block is None:
                        continue
                    blocks.append(block)
                    if block.block_kind == "heading":
                        current_heading_text = block.text
                elif tag_name == "tbl" and self._config.flatten_tables:
                    rows = self._table_rows_from_xml(inner)
                    blocks.extend(
                        self._table_rows_to_blocks(
                            rows=rows,
                            table_group_id=f"table:ooxml:sdt:{table_index:04d}",
                            section_label=current_heading_text,
                        )
                    )
                    table_index += 1
        return tuple(blocks)

    def _xml_paragraph_to_block(self, element: ET.Element, *, styles: dict[str, str]) -> DocxBlock | None:
        paragraph_text = _xml_text(element)
        if not paragraph_text:
            return None
        style_name = _xml_paragraph_style_name(element, styles)
        level = self._heading_level_from_style(style_name)
        list_level = _xml_list_level(element)
        metadata = {
            "style_name": style_name,
            "is_list": list_level is not None,
            "list_level": list_level,
        }
        if level is None and _looks_like_structural_heading_text(paragraph_text):
            level = 1
        if level is not None:
            return DocxBlock("heading", paragraph_text, style_name, level, metadata)
        if list_level is not None and self._config.preserve_lists:
            return DocxBlock("bullet", paragraph_text, style_name, None, metadata)
        return DocxBlock("paragraph", paragraph_text, style_name, None, metadata)

    def _table_rows_to_blocks(
        self,
        *,
        rows: list[list[str]],
        table_group_id: str,
        section_label: str | None,
    ) -> tuple[DocxBlock, ...]:
        blocks: list[DocxBlock] = []
        header_cells = self._header_cells(rows)
        for row_index, cells in enumerate(rows):
            clean_cells = [normalize_text(cell).strip() for cell in cells]
            if not any(clean_cells):
                continue
            metadata: dict[str, Any] = {
                "row_index": row_index,
                "cell_count": len(clean_cells),
                "table_group_id": table_group_id,
                "section_hint": section_label,
            }
            if header_cells and row_index > 0:
                row_values = {
                    header_cells[idx]: clean_cells[idx]
                    for idx in range(min(len(header_cells), len(clean_cells)))
                    if header_cells[idx] and clean_cells[idx]
                }
                if row_values:
                    metadata["row_values"] = row_values
            if len(clean_cells) == 2 and row_index > 0 and not header_cells:
                left, right = clean_cells
                if left and right and len(left) <= 64 and len(right) <= 256:
                    metadata["label"] = left.rstrip(":")
                    metadata["value"] = right
            self._augment_table_row_metadata(metadata, section_label=section_label, cells=clean_cells)
            row_text = " | ".join(cell for cell in clean_cells if cell)
            blocks.append(DocxBlock("table_row", row_text, "table", None, metadata))
        return tuple(blocks)

    @staticmethod
    def _table_rows_from_python_docx(table: Any) -> list[list[str]]:
        rows: list[list[str]] = []
        for row in table.rows:
            rows.append([normalize_text(cell.text or "").strip() for cell in row.cells])
        return rows

    @staticmethod
    def _table_rows_from_xml(table_element: ET.Element) -> list[list[str]]:
        rows: list[list[str]] = []
        for row in table_element.findall("w:tr", _NS):
            cells: list[str] = []
            for cell in row.findall("w:tc", _NS):
                cells.append(_xml_text(cell))
            rows.append(cells)
        return rows

    @staticmethod
    def _header_cells(rows: list[list[str]]) -> list[str] | None:
        if not rows:
            return None
        candidate = [normalize_text(cell).strip() for cell in rows[0] if normalize_text(cell).strip()]
        if len(candidate) < 2:
            return None
        header_tokens = (
            "name",
            "title",
            "email",
            "description",
            "billing",
            "date",
            "revision",
            "version",
            "fees",
            "rate",
            "units",
            "frequency",
            "address",
        )
        header_hits = sum(1 for cell in candidate if any(token in cell.lower() for token in header_tokens))
        mostly_short = sum(1 for cell in candidate if len(cell) <= 40) >= max(2, len(candidate) - 1)
        if header_hits >= 1 and mostly_short:
            return [normalize_text(cell).strip() for cell in rows[0]]
        return None

    @staticmethod
    def _augment_table_row_metadata(metadata: dict[str, Any], *, section_label: str | None, cells: list[str]) -> None:
        normalized_section = _normalize_heading_text(section_label)
        row_values = metadata.get("row_values")
        if normalized_section in {"customer contacts"}:
            metadata["contact_scope"] = "customer"
            metadata["target_claim_family_hints"] = ["contact_claim"]
        elif normalized_section in {"purtera sales contacts", "sales contacts"}:
            metadata["contact_scope"] = "vendor"
        if isinstance(row_values, dict):
            normalized_keys = { _normalize_heading_text(str(key)): str(value) for key, value in row_values.items() }
            if normalized_section == "introduction":
                if any(key in normalized_keys for key in ("quoted by", "sow version", "revision history")):
                    metadata.setdefault("table_semantics", "introduction_table")
        if normalized_section in _CONTACT_TABLE_HEADINGS:
            metadata.setdefault("table_semantics", "contact_table")
        if any(cell for cell in cells if "@" in cell):
            metadata.setdefault("target_claim_family_hints", ["contact_claim"] if metadata.get("contact_scope") == "customer" else metadata.get("target_claim_family_hints", []))

    @staticmethod
    def _load_docx_xml(router_input: RouterInput) -> tuple[ET.Element | None, dict[str, str]]:
        raw = extract_bytes(router_input)
        path = extract_path(router_input)
        archive_source: bytes | None = raw
        if archive_source is None and path is not None and path.exists():
            archive_source = path.read_bytes()
        if archive_source is None:
            return (None, {})
        try:
            with ZipFile(io.BytesIO(archive_source)) as zf:
                document_xml = zf.read("word/document.xml")
                styles_xml = zf.read("word/styles.xml") if "word/styles.xml" in zf.namelist() else b""
        except Exception:
            return (None, {})
        try:
            xml_root = ET.fromstring(document_xml)
        except Exception:
            return (None, {})
        return (xml_root, _style_name_map(styles_xml))

    @staticmethod
    def _heading_level_from_style(style_name: str | None) -> int | None:
        if not style_name:
            return None
        match = re.search(r"heading\s*(\d+)", style_name, flags=re.I)
        if match:
            return max(1, int(match.group(1)))
        return None

    @staticmethod
    def _is_list_paragraph(paragraph: Any, style_name: str | None) -> bool:
        if style_name and any(token in style_name.lower() for token in ("list", "bullet", "number")):
            return True
        ppr = getattr(getattr(paragraph, "_p", None), "pPr", None)
        if ppr is None:
            return False
        return getattr(ppr, "numPr", None) is not None

    @staticmethod
    def _list_level_from_paragraph(paragraph: Any) -> int | None:
        ppr = getattr(getattr(paragraph, "_p", None), "pPr", None)
        if ppr is None:
            return None
        num_pr = getattr(ppr, "numPr", None)
        if num_pr is None:
            return None
        ilvl = getattr(num_pr, "ilvl", None)
        if ilvl is None:
            return 1
        try:
            val = int(getattr(ilvl, "val", 0))
        except Exception:
            return 1
        return max(1, val + 1)


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _xml_text(element: ET.Element) -> str:
    parts: list[str] = []
    for node in element.iter():
        if _local_name(node.tag) == "t" and node.text:
            parts.append(node.text)
    return normalize_text(" ".join(part for part in parts if part).strip())


def _xml_paragraph_style_name(element: ET.Element, styles: dict[str, str]) -> str | None:
    ppr = element.find("w:pPr", _NS)
    if ppr is None:
        return None
    pstyle = ppr.find("w:pStyle", _NS)
    if pstyle is None:
        return None
    style_id = pstyle.get(f"{{{_W_NS}}}val") or pstyle.get("val")
    if not style_id:
        return None
    return styles.get(style_id, style_id)


def _xml_list_level(element: ET.Element) -> int | None:
    ilvl = element.find("w:pPr/w:numPr/w:ilvl", _NS)
    if ilvl is None:
        return None
    raw = ilvl.get(f"{{{_W_NS}}}val") or ilvl.get("val")
    try:
        return max(1, int(raw) + 1)
    except Exception:
        return 1


def _style_name_map(styles_xml: bytes) -> dict[str, str]:
    if not styles_xml:
        return {}
    try:
        root = ET.fromstring(styles_xml)
    except Exception:
        return {}
    styles: dict[str, str] = {}
    for style in root.findall("w:style", _NS):
        style_id = style.get(f"{{{_W_NS}}}styleId") or style.get("styleId")
        if not style_id:
            continue
        name = style.find("w:name", _NS)
        style_name = name.get(f"{{{_W_NS}}}val") if name is not None else None
        style_name = style_name or (name.get("val") if name is not None else None) or style_id
        styles[style_id] = style_name
    return styles


def _looks_like_structural_heading_text(text: str) -> bool:
    stripped = normalize_text(text or "").strip()
    if not stripped:
        return False
    if stripped.endswith((".", "?", "!", ";", ":")):
        return False
    words = stripped.split()
    if len(words) > 6:
        return False
    alpha_words = [word for word in words if any(ch.isalpha() for ch in word)]
    if not alpha_words:
        return False
    upperish = sum(1 for word in alpha_words if word.isupper() or word[:1].isupper())
    return upperish >= max(2, len(alpha_words) - 1)


def _normalize_heading_text(text: str | None) -> str:
    return " ".join(str(text or "").strip().lower().split())



def parse_docx(*, router_input: RouterInput, parse_plan: ParsePlan, compiled_pack: Any):
    return DocxAdapter().parse(router_input=router_input, parse_plan=parse_plan, compiled_pack=compiled_pack)
