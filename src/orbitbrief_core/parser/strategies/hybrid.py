from __future__ import annotations

from dataclasses import replace
from typing import Any

from orbitbrief_core.parser.router import ParsePlan
from orbitbrief_core.parser.shared.types import DiscourseType, DocumentParse, ReviewCategory, ReviewFlag, ReviewSeverity
from orbitbrief_core.parser.strategies.call_transcript import CallTranscriptStrategy
from orbitbrief_core.parser.strategies.email_thread import EmailThreadStrategy
from orbitbrief_core.parser.strategies.meeting_notes import MeetingNotesStrategy
from orbitbrief_core.parser.strategies.project_memo import ProjectMemoStrategy
from orbitbrief_core.parser.strategies.base import with_strategy_diag


class HybridStrategy:
    name = "hybrid"
    supported_discourse_types = (DiscourseType.HYBRID_NOTES_MEMO,)

    def __init__(self) -> None:
        self._call = CallTranscriptStrategy()
        self._notes = MeetingNotesStrategy()
        self._email = EmailThreadStrategy()
        self._memo = ProjectMemoStrategy()

    def apply(
        self,
        *,
        document_parse: DocumentParse,
        parse_plan: ParsePlan,
        compiled_pack: Any,
    ) -> DocumentParse:
        spans = list(document_parse.evidence_spans)
        conversation_like = sum(1 for span in spans if span.speaker_id or ":" in span.text[:40])
        email_like = sum(1 for span in spans if span.message_id or str(span.metadata.get("kind", "")).startswith("email_"))
        memo_like = sum(1 for span in spans if len(span.section_path) > 1 or "memo" in span.normalized_text.lower())

        current = document_parse
        applied: list[str] = []
        if email_like > 0:
            current = self._email.apply(document_parse=current, parse_plan=parse_plan, compiled_pack=compiled_pack)
            applied.append("email_thread")
        if conversation_like >= 2:
            current = self._call.apply(document_parse=current, parse_plan=parse_plan, compiled_pack=compiled_pack)
            applied.append("call_transcript")
        else:
            current = self._notes.apply(document_parse=current, parse_plan=parse_plan, compiled_pack=compiled_pack)
            applied.append("meeting_notes")
        if memo_like > 0:
            current = self._memo.apply(document_parse=current, parse_plan=parse_plan, compiled_pack=compiled_pack)
            applied.append("project_memo")

        metadata = dict(current.metadata)
        metadata["hybrid_mix"] = {
            "conversation_like": conversation_like,
            "email_like": email_like,
            "memo_like": memo_like,
            "applied": applied,
        }
        flags = list(current.review_flags)
        flags.append(
            ReviewFlag(
                flag_id=f"strategy:{current.doc_id}:hybrid:active",
                severity=ReviewSeverity.INFO,
                category=ReviewCategory.AMBIGUITY,
                message="Hybrid strategy applied combined conversation + memo enrichment.",
                metadata={"strategy": "hybrid", "applied": applied},
            )
        )
        return with_strategy_diag(replace(current, metadata=metadata, review_flags=tuple(flags)), self.name, f"applied={applied}")
