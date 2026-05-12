from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from orbitbrief_core.parser.adapters.base import AbstractAdapter, AdapterInfo
from orbitbrief_core.parser.adapters.common import add_flag, extract_text, make_builder
from orbitbrief_core.parser.adapters.text_common import (
    build_ambiguity_metadata,
    build_raw_lines,
    detect_bullet,
    detect_heading,
    infer_heading_strength,
    normalize_text,
)
from orbitbrief_core.parser.router import ParsePlan, RouterInput
from orbitbrief_core.parser.shared.types import ReviewCategory, ReviewSeverity


_PIPE_TABLE_RE = re.compile(r"^\s*\|.+\|\s*$")
_HR_RE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
_FENCE_RE = re.compile(r"^\s*(?P<fence>`{3,}|~{3,}).*$")


@dataclass(frozen=True, slots=True)
class MarkdownParseConfig:
    attach_heading_spans: bool = True
    demote_code_fences: bool = True
    demote_block_quotes: bool = True


class MarkdownAdapter(AbstractAdapter):
    info = AdapterInfo(
        name="MarkdownAdapter",
        modality="md",
        description="Deterministic markdown adapter preserving headings/lists/quotes/code/table structure.",
    )

    def __init__(self, config: MarkdownParseConfig | None = None) -> None:
        self._config = config or MarkdownParseConfig()

    def parse(self, *, router_input: RouterInput, parse_plan: ParsePlan, compiled_pack: Any):
        builder = make_builder(router_input=router_input, parse_plan=parse_plan, compiled_pack=compiled_pack)
        text = normalize_text(extract_text(router_input))
        raw_lines = build_raw_lines(text)
        root_section_id = builder.add_section(title="ROOT", section_path=("ROOT",), metadata={"synthetic": True, "adapter": "md"})
        builder.set_section_root(root_section_id)
        section_stack: list[tuple[int, str, tuple[str, ...]]] = [(0, root_section_id, ("ROOT",))]
        chronology_rank = 0
        index = 0
        while index < len(raw_lines):
            line = raw_lines[index]
            stripped = line.normalized_text
            if not stripped:
                index += 1
                continue

            fence = _FENCE_RE.match(line.text)
            if fence:
                index, chronology_rank = self._emit_code_fence(
                    builder=builder,
                    lines=raw_lines,
                    index=index,
                    section_stack=section_stack,
                    chronology_rank=chronology_rank,
                    fence_token=fence.group("fence"),
                )
                continue

            heading = detect_heading(line)
            if heading is not None and heading.style == "markdown":
                level = heading.level
                while section_stack and level <= section_stack[-1][0]:
                    section_stack.pop()
                parent_id, parent_path = section_stack[-1][1], section_stack[-1][2]
                section_path = parent_path + (heading.title,)
                section_id = builder.add_section(
                    title=heading.title,
                    section_path=section_path,
                    parent_section_id=parent_id,
                    metadata={"style": "markdown_heading", "level": level, **dict(heading.metadata)},
                )
                section_stack.append((level, section_id, section_path))
                if self._config.attach_heading_spans:
                    span_id = builder.add_span(
                        text=heading.title,
                        normalized_text=heading.normalized_title,
                        char_range=(heading.start_char, heading.end_char),
                        section_path=section_path,
                        chronology_rank=chronology_rank,
                        authority_score=0.88,
                        metadata={"kind": "heading", "level": level, **dict(heading.metadata)},
                    )
                    builder.attach_span_to_section(span_id, section_id)
                    chronology_rank += 1
                index += 1
                continue

            if _HR_RE.match(line.text):
                current_section_id, current_path = section_stack[-1][1], section_stack[-1][2]
                span_id = builder.add_span(
                    text=line.text.strip(),
                    normalized_text=line.text.strip(),
                    char_range=(line.char_start, line.char_end),
                    section_path=current_path,
                    chronology_rank=chronology_rank,
                    authority_score=0.5,
                    metadata={"kind": "horizontal_rule"},
                )
                builder.attach_span_to_section(span_id, current_section_id)
                chronology_rank += 1
                index += 1
                continue

            if stripped.startswith(">"):
                index, chronology_rank = self._emit_blockquote(
                    builder=builder,
                    lines=raw_lines,
                    index=index,
                    section_stack=section_stack,
                    chronology_rank=chronology_rank,
                )
                continue

            if _PIPE_TABLE_RE.match(line.text):
                index, chronology_rank = self._emit_table(
                    builder=builder,
                    lines=raw_lines,
                    index=index,
                    section_stack=section_stack,
                    chronology_rank=chronology_rank,
                )
                continue

            bullet = detect_bullet(line)
            if bullet is not None:
                current_section_id, current_path = section_stack[-1][1], section_stack[-1][2]
                span_id = builder.add_span(
                    text=bullet.text,
                    normalized_text=bullet.normalized_text,
                    char_range=(bullet.start_char, bullet.end_char),
                    section_path=current_path,
                    chronology_rank=chronology_rank,
                    authority_score=0.8,
                    metadata={
                        "kind": "bullet",
                        "level": bullet.level,
                        "marker": bullet.marker,
                        **dict(bullet.metadata),
                    },
                )
                builder.attach_span_to_section(span_id, current_section_id)
                chronology_rank += 1
                index += 1
                continue

            index, chronology_rank = self._emit_paragraph(
                builder=builder,
                lines=raw_lines,
                index=index,
                section_stack=section_stack,
                chronology_rank=chronology_rank,
            )

        if any(_PIPE_TABLE_RE.match(line.text) for line in raw_lines):
            add_flag(
                builder,
                severity=ReviewSeverity.INFO,
                category=ReviewCategory.QUALITY,
                message="Pipe-table syntax detected; adapter preserved it but full cell semantics are deferred.",
                metadata={"adapter": "md"},
            )
        return builder.build()

    def _emit_code_fence(self, *, builder, lines, index: int, section_stack, chronology_rank: int, fence_token: str) -> tuple[int, int]:
        start = index
        end = index
        for cursor in range(index + 1, len(lines)):
            if lines[cursor].normalized_text.startswith(fence_token):
                end = cursor
                break
        else:
            end = len(lines) - 1
        chunk = "\n".join(lines[i].text for i in range(start, end + 1)).strip()
        current_section_id, current_path = section_stack[-1][1], section_stack[-1][2]
        span_id = builder.add_span(
            text=chunk,
            normalized_text=chunk,
            char_range=(lines[start].char_start, lines[end].char_end),
            section_path=current_path,
            chronology_rank=chronology_rank,
            authority_score=0.35 if self._config.demote_code_fences else 0.7,
            metadata={"kind": "code_fence"},
        )
        builder.attach_span_to_section(span_id, current_section_id)
        add_flag(
            builder,
            severity=ReviewSeverity.INFO,
            category=ReviewCategory.QUALITY,
            message="Markdown code fence preserved as low-authority context.",
            span_id=span_id,
            metadata={"adapter": "md"},
        )
        return end + 1, chronology_rank + 1

    def _emit_blockquote(self, *, builder, lines, index: int, section_stack, chronology_rank: int) -> tuple[int, int]:
        start = index
        end = index
        quote_lines: list[str] = []
        while end < len(lines) and lines[end].normalized_text.startswith(">"):
            quote_lines.append(lines[end].normalized_text.lstrip(">").strip())
            end += 1
        text = " ".join(part for part in quote_lines if part).strip()
        current_section_id, current_path = section_stack[-1][1], section_stack[-1][2]
        span_id = builder.add_span(
            text=text,
            normalized_text=text,
            char_range=(lines[start].char_start, lines[end - 1].char_end),
            section_path=current_path,
            chronology_rank=chronology_rank,
            authority_score=0.48 if self._config.demote_block_quotes else 0.78,
            metadata={"kind": "blockquote"},
        )
        builder.attach_span_to_section(span_id, current_section_id)
        add_flag(
            builder,
            severity=ReviewSeverity.INFO,
            category=ReviewCategory.AMBIGUITY,
            message="Markdown block quote captured as quoted context.",
            span_id=span_id,
            metadata={"adapter": "md"},
        )
        return end, chronology_rank + 1

    def _emit_table(self, *, builder, lines, index: int, section_stack, chronology_rank: int) -> tuple[int, int]:
        start = index
        end = index
        table_lines: list[str] = []
        while end < len(lines) and _PIPE_TABLE_RE.match(lines[end].text):
            table_lines.append(lines[end].text.strip())
            end += 1
        table_text = "\n".join(table_lines).strip()
        current_section_id, current_path = section_stack[-1][1], section_stack[-1][2]
        span_id = builder.add_span(
            text=table_text,
            normalized_text=table_text,
            char_range=(lines[start].char_start, lines[end - 1].char_end),
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
        return end, chronology_rank + 1

    def _emit_paragraph(self, *, builder, lines, index: int, section_stack, chronology_rank: int) -> tuple[int, int]:
        start = index
        end = index
        paragraph_lines: list[str] = []
        while end < len(lines):
            current = lines[end]
            if not current.normalized_text:
                break
            if _FENCE_RE.match(current.text) or _HR_RE.match(current.text):
                break
            if current.normalized_text.startswith(">") or _PIPE_TABLE_RE.match(current.text):
                break
            heading = detect_heading(current)
            if heading is not None and heading.style == "markdown":
                break
            if detect_bullet(current) is not None:
                break
            paragraph_lines.append(current.normalized_text)
            end += 1
        paragraph_text = " ".join(part for part in paragraph_lines if part).strip()
        if not paragraph_text:
            return index + 1, chronology_rank
        current_section_id, current_path = section_stack[-1][1], section_stack[-1][2]
        heading_strength = infer_heading_strength(lines[start].text)
        ambiguity_tags: list[str] = []
        if 0.58 <= heading_strength < 0.8:
            ambiguity_tags.append("ambiguous_heading_candidate")
        span_id = builder.add_span(
            text=paragraph_text,
            normalized_text=paragraph_text,
            char_range=(lines[start].char_start, lines[end - 1].char_end),
            section_path=current_path,
            chronology_rank=chronology_rank,
            authority_score=0.82,
            metadata={"kind": "paragraph"}
            | build_ambiguity_metadata(
                ambiguity_tags=tuple(ambiguity_tags),
                candidate_heading_strength=heading_strength,
                candidate_section_break=bool(start > 0 and not lines[start - 1].normalized_text),
            ),
        )
        builder.attach_span_to_section(span_id, current_section_id)
        return end, chronology_rank + 1


def parse_markdown(*, router_input: RouterInput, parse_plan: ParsePlan, compiled_pack: Any):
    return MarkdownAdapter().parse(router_input=router_input, parse_plan=parse_plan, compiled_pack=compiled_pack)
