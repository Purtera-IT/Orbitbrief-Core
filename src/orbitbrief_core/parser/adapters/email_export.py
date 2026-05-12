from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from orbitbrief_core.parser.adapters.base import AbstractAdapter, AdapterInfo
from orbitbrief_core.parser.adapters.common import add_flag, extract_bytes, extract_text, make_builder
from orbitbrief_core.parser.adapters.mail_common import EmailMessageCandidate, parse_email_artifact
from orbitbrief_core.parser.adapters.text_common import segment_text
from orbitbrief_core.parser.router import ParsePlan, RouterInput
from orbitbrief_core.parser.shared.types import ReviewCategory, ReviewSeverity


@dataclass(frozen=True, slots=True)
class EmailExportParseConfig:
    paragraphize_current_message_text: bool = True
    attach_quote_spans: bool = True


class EmailExportAdapter(AbstractAdapter):
    info = AdapterInfo(
        name="EmailExportAdapter",
        modality="email_export",
        description="Thread-aware email export adapter with quote/forward/signature/disclaimer demotion.",
    )

    def __init__(self, config: EmailExportParseConfig | None = None) -> None:
        self._config = config or EmailExportParseConfig()

    def parse(self, *, router_input: RouterInput, parse_plan: ParsePlan, compiled_pack: Any):
        builder = make_builder(router_input=router_input, parse_plan=parse_plan, compiled_pack=compiled_pack)
        text = extract_text(router_input)
        raw_bytes = extract_bytes(router_input)
        parse_result = parse_email_artifact(text, raw_bytes=raw_bytes)
        root_section_id = builder.add_section(title="EMAIL_THREAD", section_path=("EMAIL_THREAD",), metadata={"synthetic": True, "adapter": "email_export"})
        builder.set_section_root(root_section_id)

        actor_ids: dict[str, str] = {}
        previous_message_id: str | None = None
        chronology_rank = 0
        thread_id = "thread:email_export:000001"

        for diagnostic in parse_result.diagnostics:
            add_flag(
                builder,
                severity=ReviewSeverity.INFO,
                category=ReviewCategory.QUALITY,
                message=f"email_adapter_diagnostic: {diagnostic}",
                metadata={"adapter": "email_export"},
            )
        if any(message.boundary_review_needed for message in parse_result.messages):
            add_flag(
                builder,
                severity=ReviewSeverity.WARNING,
                category=ReviewCategory.AMBIGUITY,
                message="Email boundary detection has uncertain regions; review recommended.",
                metadata={"adapter": "email_export", "code": "boundary_uncertain"},
            )

        section_titles_seen: dict[str, int] = {}
        for message_index, message in enumerate(parse_result.messages, start=1):
            author_id = self._ensure_actor(builder, actor_ids, message.sender_name, message.sender)
            recipient_ids = [self._ensure_actor(builder, actor_ids, None, email_addr) for email_addr in message.recipient_emails]
            cc_ids = [self._ensure_actor(builder, actor_ids, None, email_addr) for email_addr in message.cc_emails]
            section_title = self._unique_title(message.subject or f"Message {message_index}", section_titles_seen)
            section_id = builder.add_section(
                title=section_title,
                section_path=("EMAIL_THREAD", section_title),
                parent_section_id=root_section_id,
                metadata={"adapter": "email_export", "message_id": message.message_id},
            )
            time_anchor_id = None
            if message.date_iso or message.date_text:
                label = message.date_text or message.date_iso or f"message_time:{message_index}"
                time_anchor_id = builder.add_time_anchor(
                    label=label,
                    iso8601=message.date_iso,
                    metadata={"adapter": "email_export", "raw_date": message.date_text},
                )
                chronology_rank += 1
            message_node_id = builder.add_message(
                message_id=f"message:{message.message_id}",
                thread_id=thread_id,
                author_id=author_id,
                section_id=section_id,
                time_anchor_id=time_anchor_id,
                parent_message_id=previous_message_id,
                metadata={
                    "subject": message.subject,
                    "recipient_actor_ids": recipient_ids,
                    "cc_actor_ids": cc_ids,
                    **dict(message.metadata),
                },
            )
            if previous_message_id is None:
                builder.set_thread_id(thread_id)

            self._emit_message_body(
                builder=builder,
                section_id=section_id,
                message_id=message_node_id,
                message=message,
                chronology_rank_start=chronology_rank,
            )
            chronology_rank += 10
            previous_message_id = message_node_id
        return builder.build()

    @staticmethod
    def _unique_title(title: str, seen: dict[str, int]) -> str:
        clean = " ".join(title.split())[:120] or "Message"
        count = seen.get(clean, 0)
        seen[clean] = count + 1
        return clean if count == 0 else f"{clean} #{count + 1}"

    def _ensure_actor(self, builder, actor_ids: dict[str, str], display_name: str | None, email_addr: str | None) -> str:
        key = (email_addr or display_name or "unknown").strip().lower()
        if key in actor_ids:
            return actor_ids[key]
        actor_id = builder.add_actor(display_name=display_name or email_addr or "Unknown", role_label="email_actor", email=email_addr)
        actor_ids[key] = actor_id
        return actor_id

    def _emit_message_body(
        self,
        *,
        builder,
        section_id: str,
        message_id: str,
        message: EmailMessageCandidate,
        chronology_rank_start: int,
    ) -> None:
        if message.boundary_segments:
            self._emit_boundary_segments(
                builder=builder,
                section_id=section_id,
                message_id=message_id,
                message=message,
                chronology_rank_start=chronology_rank_start,
            )
            return
        current_text = message.current_text.strip() or message.body_text.strip()
        self._emit_segmented_current_body(
            builder=builder,
            section_id=section_id,
            message_id=message_id,
            subject=message.subject,
            base_offset=message.start_char,
            text=current_text,
            chronology_rank_start=chronology_rank_start,
            authority_score=0.9,
            base_metadata={"kind": "email_current"},
        )

    def _section_path_for_offset(self, *, subject: str | None, segmentation, offset: int) -> tuple[str, ...]:
        base = ("EMAIL_THREAD", subject or "message")
        active_heading = None
        for heading in segmentation.headings:
            if heading.start_char <= offset:
                active_heading = heading.title
            else:
                break
        return base + ((active_heading,) if active_heading else ())

    def _emit_segmented_current_body(
        self,
        *,
        builder,
        section_id: str,
        message_id: str,
        subject: str | None,
        base_offset: int,
        text: str,
        chronology_rank_start: int,
        authority_score: float,
        base_metadata: dict[str, Any],
    ) -> int:
        segmentation = segment_text(text)
        chronology_rank = chronology_rank_start
        if not segmentation.headings and not segmentation.bullets and not segmentation.paragraphs:
            span_id = builder.add_span(
                text=text,
                normalized_text=text,
                char_range=(base_offset, base_offset + len(text)),
                section_path=("EMAIL_THREAD", subject or "message"),
                message_id=message_id,
                chronology_rank=chronology_rank,
                authority_score=authority_score,
                metadata=dict(base_metadata),
            )
            builder.attach_span_to_section(span_id, section_id)
            builder.attach_message_to_spans(message_id, (span_id,))
            return chronology_rank + 1

        for heading in segmentation.headings:
            section_path = self._section_path_for_offset(subject=subject, segmentation=segmentation, offset=heading.start_char)
            span_id = builder.add_span(
                text=heading.title,
                normalized_text=heading.normalized_title,
                char_range=(base_offset + heading.start_char, base_offset + heading.end_char),
                section_path=section_path,
                message_id=message_id,
                chronology_rank=chronology_rank,
                authority_score=min(0.98, authority_score + 0.03),
                metadata={
                    **dict(base_metadata),
                    "kind": "heading",
                    "heading_id": heading.heading_id,
                    "heading_level": heading.level,
                    "heading_style": heading.style,
                },
            )
            builder.attach_span_to_section(span_id, section_id)
            builder.attach_message_to_spans(message_id, (span_id,))
            chronology_rank += 1

        for bullet in segmentation.bullets:
            section_path = self._section_path_for_offset(subject=subject, segmentation=segmentation, offset=bullet.start_char)
            span_id = builder.add_span(
                text=bullet.text,
                normalized_text=bullet.normalized_text,
                char_range=(base_offset + bullet.start_char, base_offset + bullet.end_char),
                section_path=section_path,
                message_id=message_id,
                chronology_rank=chronology_rank,
                authority_score=authority_score,
                metadata={
                    **dict(base_metadata),
                    "kind": "bullet",
                    "bullet_id": bullet.bullet_id,
                    "level": bullet.level,
                    "marker": bullet.marker,
                },
            )
            builder.attach_span_to_section(span_id, section_id)
            builder.attach_message_to_spans(message_id, (span_id,))
            chronology_rank += 1

        for paragraph in segmentation.paragraphs:
            section_path = self._section_path_for_offset(subject=subject, segmentation=segmentation, offset=paragraph.start_char)
            span_id = builder.add_span(
                text=paragraph.text,
                normalized_text=paragraph.normalized_text,
                char_range=(base_offset + paragraph.start_char, base_offset + paragraph.end_char),
                section_path=section_path,
                message_id=message_id,
                chronology_rank=chronology_rank,
                authority_score=authority_score,
                metadata={
                    **dict(base_metadata),
                    "kind": paragraph.kind,
                    "paragraph_id": paragraph.paragraph_id,
                    **dict(paragraph.metadata),
                },
            )
            builder.attach_span_to_section(span_id, section_id)
            builder.attach_message_to_spans(message_id, (span_id,))
            chronology_rank += 1
        return chronology_rank

    def _emit_boundary_segments(
        self,
        *,
        builder,
        section_id: str,
        message_id: str,
        message: EmailMessageCandidate,
        chronology_rank_start: int,
    ) -> None:
        chronology_rank = chronology_rank_start
        segment_order = tuple(message.boundary_segments)
        for segment in segment_order:
            if segment.boundary_class == "current_authored":
                chronology_rank = self._emit_segmented_current_body(
                    builder=builder,
                    section_id=section_id,
                    message_id=message_id,
                    subject=message.subject,
                    base_offset=message.start_char + segment.start_char,
                    text=segment.text,
                    chronology_rank_start=chronology_rank,
                    authority_score=segment.authority_weight,
                    base_metadata={
                        "kind": "email_current",
                        "boundary_class": segment.boundary_class,
                        "authority_kind": segment.authority_kind,
                        "authority_weight": segment.authority_weight,
                        "boundary_confidence": segment.boundary_confidence,
                        "segment_source": segment.segment_source,
                    },
                )
                continue

            kind = {
                "quoted_context": "quoted_context",
                "forwarded_context": "forwarded_context",
                "signature": "signature",
                "disclaimer": "disclaimer",
                "noise": "noise",
            }.get(segment.boundary_class, "email_noise")
            span_id = builder.add_span(
                text=segment.text,
                normalized_text=segment.text,
                char_range=(message.start_char + segment.start_char, message.start_char + segment.end_char),
                section_path=("EMAIL_THREAD", message.subject or "message"),
                message_id=message_id,
                chronology_rank=chronology_rank,
                authority_score=segment.authority_weight,
                metadata={
                    "kind": kind,
                    "boundary_class": segment.boundary_class,
                    "authority_kind": segment.authority_kind,
                    "authority_weight": segment.authority_weight,
                    "boundary_confidence": segment.boundary_confidence,
                    "segment_source": segment.segment_source,
                    **dict(segment.metadata),
                },
            )
            builder.attach_span_to_section(span_id, section_id)
            builder.attach_message_to_spans(message_id, (span_id,))
            if segment.boundary_class in {"quoted_context", "forwarded_context"}:
                add_flag(
                    builder,
                    severity=ReviewSeverity.INFO,
                    category=ReviewCategory.AMBIGUITY,
                    message=f"{segment.boundary_class} retained as low-authority context.",
                    span_id=span_id,
                    metadata={"adapter": "email_export", "boundary_class": segment.boundary_class},
                )
            if segment.boundary_class in {"signature", "disclaimer", "noise"}:
                add_flag(
                    builder,
                    severity=ReviewSeverity.INFO,
                    category=ReviewCategory.QUALITY,
                    message="Signature/disclaimer/noise preserved as low-authority context.",
                    span_id=span_id,
                    metadata={"adapter": "email_export", "boundary_class": segment.boundary_class},
                )
            if segment.boundary_confidence < 0.62:
                add_flag(
                    builder,
                    severity=ReviewSeverity.WARNING,
                    category=ReviewCategory.AMBIGUITY,
                    message=f"{segment.boundary_class} boundary is uncertain.",
                    span_id=span_id,
                    metadata={"adapter": "email_export", "code": f"{segment.boundary_class}_boundary_uncertain"},
                )
            chronology_rank += 1


def parse_email_export(*, router_input: RouterInput, parse_plan: ParsePlan, compiled_pack: Any):
    return EmailExportAdapter().parse(router_input=router_input, parse_plan=parse_plan, compiled_pack=compiled_pack)
