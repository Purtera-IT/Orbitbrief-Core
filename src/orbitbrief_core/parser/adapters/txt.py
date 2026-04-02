from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from orbitbrief_core.parser.adapters.base import AbstractAdapter, AdapterInfo
from orbitbrief_core.parser.adapters.common import add_flag, extract_text, make_builder
from orbitbrief_core.parser.adapters.text_common import (
    HeadingCandidate,
    TextSegmentationResult,
    extract_time_strings,
    segment_text,
)
from orbitbrief_core.parser.router import ParsePlan, RouterInput
from orbitbrief_core.parser.shared.types import DiscourseType, ReviewCategory, ReviewSeverity


@dataclass(frozen=True, slots=True)
class TxtParseConfig:
    create_root_section: bool = True
    attach_heading_spans: bool = True
    emit_diagnostics_as_flags: bool = True


class TxtAdapter(AbstractAdapter):
    info = AdapterInfo(
        name="TxtAdapter",
        modality="txt",
        description="Deterministic-first plain-text adapter for transcripts, notes, and memo-like text.",
    )

    def __init__(self, config: TxtParseConfig | None = None) -> None:
        self._config = config or TxtParseConfig()

    def parse(
        self,
        *,
        router_input: RouterInput,
        parse_plan: ParsePlan,
        compiled_pack: Any,
    ):
        builder = make_builder(router_input=router_input, parse_plan=parse_plan, compiled_pack=compiled_pack)
        text = extract_text(router_input)
        segmentation = segment_text(text, discourse_type=parse_plan.discourse_type)
        root_section_id, heading_sections = self._build_section_tree(builder, segmentation) if self._config.create_root_section else (None, {})
        if root_section_id is not None:
            builder.set_section_root(root_section_id)

        if parse_plan.discourse_type is DiscourseType.CALL_TRANSCRIPT and segmentation.speaker_turns:
            self._emit_transcript(builder, segmentation, heading_sections, root_section_id)
        else:
            self._emit_narrative(builder, segmentation, heading_sections, root_section_id)

        for diagnostic in segmentation.diagnostics:
            if self._config.emit_diagnostics_as_flags:
                add_flag(
                    builder,
                    severity=ReviewSeverity.WARNING,
                    category=ReviewCategory.AMBIGUITY,
                    message=f"txt_adapter_diagnostic: {diagnostic}",
                    metadata={"adapter": "txt"},
                )
        return builder.build()

    def _build_section_tree(self, builder, segmentation: TextSegmentationResult):
        root_section_id = builder.add_section(title="ROOT", section_path=("ROOT",), metadata={"synthetic": True, "adapter": "txt"})
        heading_sections: dict[str, tuple[str, tuple[str, ...]]] = {}
        stack: list[tuple[int, str, tuple[str, ...]]] = [(0, root_section_id, ("ROOT",))]
        for heading in segmentation.headings:
            while stack and heading.level <= stack[-1][0]:
                stack.pop()
            parent_level, parent_id, parent_path = stack[-1] if stack else (0, root_section_id, ("ROOT",))
            section_path = parent_path + (heading.title,)
            section_id = builder.add_section(
                title=heading.title,
                section_path=section_path,
                parent_section_id=parent_id,
                metadata={"style": heading.style, "level": heading.level, "adapter": "txt"},
            )
            heading_sections[heading.heading_id] = (section_id, section_path)
            stack.append((heading.level, section_id, section_path))
            if self._config.attach_heading_spans:
                span_id = builder.add_span(
                    text=heading.title,
                    normalized_text=heading.normalized_title,
                    char_range=(heading.start_char, heading.end_char),
                    section_path=section_path,
                    chronology_rank=heading.heading_index,
                    authority_score=0.82,
                    metadata={"kind": "heading", "style": heading.style, "heading_id": heading.heading_id},
                )
                builder.attach_span_to_section(span_id, section_id)
        return root_section_id, heading_sections

    def _section_for_offset(
        self,
        headings: tuple[HeadingCandidate, ...],
        heading_sections: dict[str, tuple[str, tuple[str, ...]]],
        offset: int,
        root_section_id: str | None,
    ) -> tuple[str | None, tuple[str, ...]]:
        current_section_id = root_section_id
        current_path = ("ROOT",) if root_section_id else ()
        for heading in sorted(headings, key=lambda item: item.start_char):
            if heading.start_char > offset:
                break
            current_section_id, current_path = heading_sections.get(heading.heading_id, (current_section_id, current_path))
        return current_section_id, current_path

    def _emit_transcript(self, builder, segmentation: TextSegmentationResult, heading_sections, root_section_id: str | None) -> None:
        actor_ids: dict[str, str] = {}
        chronology_rank = 0
        for turn in segmentation.speaker_turns:
            speaker_key = turn.speaker_label.strip().lower()
            actor_id = actor_ids.get(speaker_key)
            if actor_id is None:
                actor_id = builder.add_actor(display_name=turn.speaker_label, role_label="speaker", metadata={"source": "txt_transcript"})
                actor_ids[speaker_key] = actor_id
            time_anchor_id = None
            if turn.time_text:
                time_anchor_id = builder.add_time_anchor(
                    label=turn.time_text,
                    metadata={"source": "txt_transcript_time"},
                )
                chronology_rank += 1
            current_section_id, current_path = self._section_for_offset(segmentation.headings, heading_sections, turn.start_char, root_section_id)
            span_id = builder.add_span(
                text=turn.text,
                normalized_text=turn.normalized_text,
                char_range=(turn.start_char, turn.end_char),
                section_path=current_path,
                speaker_id=actor_id,
                time_anchor_id=time_anchor_id,
                chronology_rank=chronology_rank,
                authority_score=0.86,
                metadata={"kind": "speaker_turn", "speaker_label": turn.speaker_label, "turn_id": turn.turn_id},
            )
            if current_section_id is not None:
                builder.attach_span_to_section(span_id, current_section_id)
            builder.attach_actor_to_spans(actor_id, (span_id,))
            if turn.time_text:
                add_flag(
                    builder,
                    severity=ReviewSeverity.INFO,
                    category=ReviewCategory.QUALITY,
                    message="Transcript turn includes explicit time cue.",
                    span_id=span_id,
                    metadata={"time_text": turn.time_text},
                )
            chronology_rank += 1
        if not segmentation.speaker_turns:
            add_flag(
                builder,
                severity=ReviewSeverity.WARNING,
                category=ReviewCategory.AMBIGUITY,
                message="Transcript route selected but no speaker turns were recovered.",
                metadata={"adapter": "txt"},
            )

    def _emit_narrative(self, builder, segmentation: TextSegmentationResult, heading_sections, root_section_id: str | None) -> None:
        chronology_rank = 0
        for bullet in segmentation.bullets:
            current_section_id, current_path = self._section_for_offset(segmentation.headings, heading_sections, bullet.start_char, root_section_id)
            span_id = builder.add_span(
                text=bullet.text,
                normalized_text=bullet.normalized_text,
                char_range=(bullet.start_char, bullet.end_char),
                section_path=current_path,
                chronology_rank=chronology_rank,
                authority_score=0.78,
                metadata={"kind": "bullet", "level": bullet.level, "marker": bullet.marker, "bullet_id": bullet.bullet_id},
            )
            if current_section_id is not None:
                builder.attach_span_to_section(span_id, current_section_id)
            chronology_rank += 1

        for paragraph in segmentation.paragraphs:
            current_section_id, current_path = self._section_for_offset(segmentation.headings, heading_sections, paragraph.start_char, root_section_id)
            span_id = builder.add_span(
                text=paragraph.text,
                normalized_text=paragraph.normalized_text,
                char_range=(paragraph.start_char, paragraph.end_char),
                section_path=current_path,
                chronology_rank=chronology_rank,
                authority_score=0.8,
                metadata={"kind": paragraph.kind, "paragraph_id": paragraph.paragraph_id, **dict(paragraph.metadata)},
            )
            if current_section_id is not None:
                builder.attach_span_to_section(span_id, current_section_id)
            if paragraph.kind == "action_item":
                add_flag(
                    builder,
                    severity=ReviewSeverity.INFO,
                    category=ReviewCategory.QUALITY,
                    message="Paragraph includes action-item style cues.",
                    span_id=span_id,
                    metadata={"adapter": "txt"},
                )
            if extract_time_strings(paragraph.text):
                add_flag(
                    builder,
                    severity=ReviewSeverity.INFO,
                    category=ReviewCategory.QUALITY,
                    message="Paragraph includes inline time cues.",
                    span_id=span_id,
                    metadata={"times": list(extract_time_strings(paragraph.text))},
                )
            chronology_rank += 1


def parse_txt(*, router_input: RouterInput, parse_plan: ParsePlan, compiled_pack: Any):
    return TxtAdapter().parse(router_input=router_input, parse_plan=parse_plan, compiled_pack=compiled_pack)
