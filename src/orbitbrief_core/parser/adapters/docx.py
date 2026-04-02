from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any, Iterator

from orbitbrief_core.parser.adapters.base import AbstractAdapter, AdapterInfo
from orbitbrief_core.parser.adapters.common import add_flag, extract_bytes, extract_path, extract_text, make_builder
from orbitbrief_core.parser.adapters.text_common import extract_time_strings, infer_heading_level, normalize_text
from orbitbrief_core.parser.router import ParsePlan, RouterInput
from orbitbrief_core.parser.shared.types import ReviewCategory, ReviewSeverity


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
        root_section_id = builder.add_section(title="ROOT", section_path=("ROOT",), metadata={"synthetic": True, "adapter": "docx"})
        builder.set_section_root(root_section_id)

        blocks = self._extract_blocks(router_input)
        if not blocks:
            if self._config.fallback_to_text:
                text = normalize_text(extract_text(router_input))
                span_id = builder.add_span(
                    text=text,
                    normalized_text=text,
                    section_path=("ROOT",),
                    chronology_rank=0,
                    authority_score=0.65,
                    metadata={"kind": "docx_text_fallback"},
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

        section_stack: list[tuple[int, str, tuple[str, ...]]] = [(0, root_section_id, ("ROOT",))]
        chronology_rank = 0
        for block in blocks:
            if block.block_kind == "heading":
                level = block.level or infer_heading_level(block.text)
                while section_stack and level <= section_stack[-1][0]:
                    section_stack.pop()
                parent_id, parent_path = section_stack[-1][1], section_stack[-1][2]
                section_path = parent_path + (block.text,)
                section_id = builder.add_section(
                    title=block.text,
                    section_path=section_path,
                    parent_section_id=parent_id,
                    metadata={"style": block.style_name, **block.metadata},
                )
                section_stack.append((level, section_id, section_path))
                heading_span_id = builder.add_span(
                    text=block.text,
                    normalized_text=block.text.lower(),
                    section_path=section_path,
                    chronology_rank=chronology_rank,
                    authority_score=0.9,
                    metadata={"kind": "heading", **block.metadata},
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
                authority_score=0.84 if block.block_kind != "table_row" else 0.7,
                metadata={"kind": block.block_kind, "style_name": block.style_name, **block.metadata},
            )
            builder.attach_span_to_section(span_id, current_section_id)
            if block.block_kind == "table_row":
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

    def _extract_blocks(self, router_input: RouterInput) -> tuple[DocxBlock, ...]:
        try:
            from docx import Document as DocxDocument  # type: ignore
            from docx.document import Document as _DocumentType  # type: ignore
            from docx.oxml.table import CT_Tbl  # type: ignore
            from docx.oxml.text.paragraph import CT_P  # type: ignore
            from docx.table import Table  # type: ignore
            from docx.text.paragraph import Paragraph  # type: ignore
        except Exception:
            return ()

        path = extract_path(router_input)
        raw = extract_bytes(router_input)
        try:
            if raw is not None:
                document = DocxDocument(io.BytesIO(raw))
            elif path is not None:
                document = DocxDocument(str(path))
            else:
                return ()
        except Exception:
            return ()

        def iter_block_items(parent) -> Iterator[Any]:
            parent_elm = parent.element.body if isinstance(parent, _DocumentType) else parent._tc
            for child in parent_elm.iterchildren():
                if isinstance(child, CT_P):
                    yield Paragraph(child, parent)
                elif isinstance(child, CT_Tbl):
                    yield Table(child, parent)

        blocks: list[DocxBlock] = []
        for element in iter_block_items(document):
            if element.__class__.__name__ == "Paragraph":
                paragraph_text = normalize_text(element.text or "").strip()
                if not paragraph_text:
                    continue
                style_name = getattr(getattr(element, "style", None), "name", None)
                level = self._heading_level_from_style(style_name)
                metadata = {
                    "style_name": style_name,
                    "is_list": self._is_list_paragraph(element, style_name),
                }
                if level is not None:
                    blocks.append(DocxBlock("heading", paragraph_text, style_name, level, metadata))
                    continue
                if metadata["is_list"] and self._config.preserve_lists:
                    blocks.append(DocxBlock("bullet", paragraph_text, style_name, None, metadata))
                else:
                    blocks.append(DocxBlock("paragraph", paragraph_text, style_name, None, metadata))
            else:
                if not self._config.flatten_tables:
                    continue
                for row_index, row in enumerate(element.rows):
                    cells = [normalize_text(cell.text or "").strip() for cell in row.cells]
                    if not any(cells):
                        continue
                    row_text = " | ".join(cell for cell in cells if cell)
                    blocks.append(
                        DocxBlock(
                            "table_row",
                            row_text,
                            "table",
                            None,
                            {"row_index": row_index, "cell_count": len(cells)},
                        )
                    )
        return tuple(blocks)

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


def parse_docx(*, router_input: RouterInput, parse_plan: ParsePlan, compiled_pack: Any):
    return DocxAdapter().parse(router_input=router_input, parse_plan=parse_plan, compiled_pack=compiled_pack)
