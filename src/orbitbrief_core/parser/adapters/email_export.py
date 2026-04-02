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
        current_text = message.current_text.strip() or message.body_text.strip()
        current_segmentation = segment_text(current_text)
        chronology_rank = chronology_rank_start
        for paragraph in current_segmentation.paragraphs:
            span_id = builder.add_span(
                text=paragraph.text,
                normalized_text=paragraph.normalized_text,
                char_range=(message.start_char + paragraph.start_char, message.start_char + paragraph.end_char),
                section_path=("EMAIL_THREAD", message.subject or "message"),
                message_id=message_id,
                chronology_rank=chronology_rank,
                authority_score=0.9,
                metadata={"kind": "email_current", "paragraph_id": paragraph.paragraph_id},
            )
            builder.attach_span_to_section(span_id, section_id)
            builder.attach_message_to_spans(message_id, (span_id,))
            chronology_rank += 1

        if not self._config.attach_quote_spans:
            return
        for block in message.quoted_blocks:
            span_id = builder.add_span(
                text=block.text,
                normalized_text=block.text,
                char_range=(message.start_char + block.start_char, message.start_char + block.end_char),
                section_path=("EMAIL_THREAD", message.subject or "message"),
                message_id=message_id,
                chronology_rank=chronology_rank,
                authority_score=0.34,
                metadata={"kind": "quoted_context", **dict(block.metadata)},
            )
            builder.attach_span_to_section(span_id, section_id)
            builder.attach_message_to_spans(message_id, (span_id,))
            add_flag(
                builder,
                severity=ReviewSeverity.INFO,
                category=ReviewCategory.AMBIGUITY,
                message="Quoted email history retained as low-authority context.",
                span_id=span_id,
                metadata={"adapter": "email_export"},
            )
            chronology_rank += 1
        for block in message.forwarded_blocks:
            span_id = builder.add_span(
                text=block.text,
                normalized_text=block.text,
                char_range=(message.start_char + block.start_char, message.start_char + block.end_char),
                section_path=("EMAIL_THREAD", message.subject or "message"),
                message_id=message_id,
                chronology_rank=chronology_rank,
                authority_score=0.28,
                metadata={"kind": "forwarded_context", **dict(block.metadata)},
            )
            builder.attach_span_to_section(span_id, section_id)
            builder.attach_message_to_spans(message_id, (span_id,))
            add_flag(
                builder,
                severity=ReviewSeverity.INFO,
                category=ReviewCategory.AMBIGUITY,
                message="Forwarded content retained as demoted context.",
                span_id=span_id,
                metadata={"adapter": "email_export"},
            )
            chronology_rank += 1
        for block in (*message.signature_blocks, *message.disclaimer_blocks):
            span_id = builder.add_span(
                text=block.text,
                normalized_text=block.text,
                char_range=(message.start_char + block.start_char, message.start_char + block.end_char),
                section_path=("EMAIL_THREAD", message.subject or "message"),
                message_id=message_id,
                chronology_rank=chronology_rank,
                authority_score=0.15,
                metadata={"kind": "email_noise", **dict(block.metadata)},
            )
            builder.attach_message_to_spans(message_id, (span_id,))
            add_flag(
                builder,
                severity=ReviewSeverity.INFO,
                category=ReviewCategory.QUALITY,
                message="Signature/disclaimer preserved as noise context and should not be over-trusted.",
                span_id=span_id,
                metadata={"adapter": "email_export"},
            )
            chronology_rank += 1


def parse_email_export(*, router_input: RouterInput, parse_plan: ParsePlan, compiled_pack: Any):
    return EmailExportAdapter().parse(router_input=router_input, parse_plan=parse_plan, compiled_pack=compiled_pack)
