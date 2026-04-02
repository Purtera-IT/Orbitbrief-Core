from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from orbitbrief_core.parser.adapters.base import AbstractAdapter, AdapterInfo
from orbitbrief_core.parser.adapters.common import add_flag, extract_text, make_builder
from orbitbrief_core.parser.adapters.text_common import normalize_text
from orbitbrief_core.parser.router import ParsePlan, RouterInput
from orbitbrief_core.parser.shared.types import ReviewCategory, ReviewSeverity


_PIPE_TABLE_RE = re.compile(r"(?m)^\s*\|.+\|\s*$")


@dataclass(frozen=True, slots=True)
class MarkdownParseConfig:
    attach_heading_spans: bool = True
    demote_code_fences: bool = True
    demote_block_quotes: bool = True


class MarkdownAdapter(AbstractAdapter):
    info = AdapterInfo(
        name="MarkdownAdapter",
        modality="md",
        description="Markdown-aware adapter with AST-first structure recovery and deterministic fallbacks.",
        optional_dependencies=("markdown_it",),
    )

    def __init__(self, config: MarkdownParseConfig | None = None) -> None:
        self._config = config or MarkdownParseConfig()

    def parse(self, *, router_input: RouterInput, parse_plan: ParsePlan, compiled_pack: Any):
        builder = make_builder(router_input=router_input, parse_plan=parse_plan, compiled_pack=compiled_pack)
        text = normalize_text(extract_text(router_input))
        root_section_id = builder.add_section(title="ROOT", section_path=("ROOT",), metadata={"synthetic": True, "adapter": "md"})
        builder.set_section_root(root_section_id)

        try:
            from markdown_it import MarkdownIt  # type: ignore
        except Exception:
            return self._fallback_parse(builder, text, root_section_id)

        md = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False}).enable("table")
        tokens = md.parse(text)
        line_offsets = self._line_offsets(text)
        section_stack: list[tuple[int, str, tuple[str, ...]]] = [(0, root_section_id, ("ROOT",))]
        chronology_rank = 0
        index = 0
        while index < len(tokens):
            token = tokens[index]
            token_type = token.type
            if token_type == "heading_open":
                level = int(token.tag[1]) if token.tag.startswith("h") and token.tag[1:].isdigit() else 1
                inline = tokens[index + 1] if index + 1 < len(tokens) else None
                title = (inline.content if inline is not None else "").strip()
                while section_stack and level <= section_stack[-1][0]:
                    section_stack.pop()
                parent_id, parent_path = section_stack[-1][1], section_stack[-1][2]
                section_path = parent_path + (title,)
                section_id = builder.add_section(
                    title=title,
                    section_path=section_path,
                    parent_section_id=parent_id,
                    metadata={"style": "markdown_heading", "level": level},
                )
                section_stack.append((level, section_id, section_path))
                if self._config.attach_heading_spans:
                    char_range = self._token_range(token.map, line_offsets, text)
                    span_id = builder.add_span(
                        text=title,
                        normalized_text=title.lower(),
                        char_range=char_range,
                        section_path=section_path,
                        chronology_rank=chronology_rank,
                        authority_score=0.88,
                        metadata={"kind": "heading", "level": level},
                    )
                    builder.attach_span_to_section(span_id, section_id)
                    chronology_rank += 1
                index += 3
                continue

            if token_type in {"paragraph_open", "blockquote_open", "list_item_open", "fence", "code_block", "table_open"}:
                if token_type in {"fence", "code_block"}:
                    if self._config.demote_code_fences:
                        add_flag(
                            builder,
                            severity=ReviewSeverity.INFO,
                            category=ReviewCategory.QUALITY,
                            message="Markdown code fence/code block preserved as low-authority context.",
                            metadata={"adapter": "md", "token_type": token_type},
                        )
                    index += 1
                    continue
                if token_type == "table_open":
                    table_lines = self._capture_table(text, token.map)
                    if table_lines:
                        current_section_id, current_path = section_stack[-1][1], section_stack[-1][2]
                        span_id = builder.add_span(
                            text=table_lines,
                            normalized_text=table_lines,
                            char_range=self._token_range(token.map, line_offsets, text),
                            section_path=current_path,
                            chronology_rank=chronology_rank,
                            authority_score=0.66,
                            metadata={"kind": "markdown_table", "flattened": True},
                        )
                        builder.attach_span_to_section(span_id, current_section_id)
                        add_flag(
                            builder,
                            severity=ReviewSeverity.INFO,
                            category=ReviewCategory.QUALITY,
                            message="Markdown table flattened into narrative span pending dedicated table semantics.",
                            span_id=span_id,
                            metadata={"adapter": "md"},
                        )
                        chronology_rank += 1
                    index += 1
                    continue
                inline = self._find_next_inline(tokens, index + 1)
                content = (inline.content if inline is not None else "").strip()
                if not content:
                    index += 1
                    continue
                current_section_id, current_path = section_stack[-1][1], section_stack[-1][2]
                metadata = {"kind": token_type.replace("_open", "")}
                authority_score = 0.82
                if token_type == "blockquote_open" and self._config.demote_block_quotes:
                    authority_score = 0.48
                    add_flag(
                        builder,
                        severity=ReviewSeverity.INFO,
                        category=ReviewCategory.AMBIGUITY,
                        message="Markdown block quote captured as quoted context, not primary authored evidence.",
                        metadata={"adapter": "md"},
                    )
                if token_type == "list_item_open":
                    metadata["kind"] = "bullet"
                    authority_score = 0.8
                span_id = builder.add_span(
                    text=content,
                    normalized_text=content,
                    char_range=self._token_range(token.map, line_offsets, text),
                    section_path=current_path,
                    chronology_rank=chronology_rank,
                    authority_score=authority_score,
                    metadata=metadata,
                )
                builder.attach_span_to_section(span_id, current_section_id)
                chronology_rank += 1
            index += 1

        if _PIPE_TABLE_RE.search(text):
            add_flag(
                builder,
                severity=ReviewSeverity.INFO,
                category=ReviewCategory.QUALITY,
                message="Pipe-table syntax detected; adapter preserved it but full cell semantics are deferred.",
                metadata={"adapter": "md"},
            )
        return builder.build()

    def _fallback_parse(self, builder, text: str, section_id: str):
        for idx, paragraph in enumerate(p for p in text.split("\n\n") if p.strip()):
            stripped = paragraph.strip()
            if stripped.startswith("```"):
                add_flag(
                    builder,
                    severity=ReviewSeverity.INFO,
                    category=ReviewCategory.QUALITY,
                    message="Markdown code fence encountered during fallback parse.",
                    metadata={"adapter": "md_fallback"},
                )
                continue
            if stripped.startswith("#"):
                title = stripped.lstrip("#").strip()
                child_section_id = builder.add_section(
                    title=title,
                    section_path=("ROOT", title),
                    parent_section_id=section_id,
                    metadata={"style": "markdown_heading_fallback"},
                )
                builder.attach_span_to_section(
                    builder.add_span(text=title, normalized_text=title.lower(), section_path=("ROOT", title), chronology_rank=idx, authority_score=0.86, metadata={"kind": "heading"}),
                    child_section_id,
                )
                continue
            span_id = builder.add_span(
                text=stripped,
                normalized_text=stripped,
                section_path=("ROOT",),
                chronology_rank=idx,
                authority_score=0.8,
                metadata={"kind": "paragraph"},
            )
            builder.attach_span_to_section(span_id, section_id)
        add_flag(
            builder,
            severity=ReviewSeverity.WARNING,
            category=ReviewCategory.AMBIGUITY,
            message="markdown_it unavailable; markdown parsed via paragraph fallback.",
            metadata={"adapter": "md"},
        )
        return builder.build()

    @staticmethod
    def _line_offsets(text: str) -> tuple[int, ...]:
        offsets = [0]
        for idx, ch in enumerate(text):
            if ch == "\n":
                offsets.append(idx + 1)
        return tuple(offsets)

    @staticmethod
    def _token_range(token_map, line_offsets: tuple[int, ...], text: str) -> tuple[int, int] | None:
        if not token_map:
            return None
        start_line, end_line = token_map
        if start_line >= len(line_offsets):
            return None
        start = line_offsets[start_line]
        end = len(text) if end_line >= len(line_offsets) else line_offsets[end_line]
        return (start, end)

    @staticmethod
    def _find_next_inline(tokens, start_index: int):
        for token in tokens[start_index:]:
            if token.type == "inline":
                return token
            if token.type.endswith("_close"):
                break
        return None

    @staticmethod
    def _capture_table(text: str, token_map) -> str:
        if not token_map:
            return ""
        start_line, end_line = token_map
        lines = text.splitlines()
        captured = [line for line in lines[start_line:end_line] if line.strip()]
        return "\n".join(captured).strip()


def parse_markdown(*, router_input: RouterInput, parse_plan: ParsePlan, compiled_pack: Any):
    return MarkdownAdapter().parse(router_input=router_input, parse_plan=parse_plan, compiled_pack=compiled_pack)
