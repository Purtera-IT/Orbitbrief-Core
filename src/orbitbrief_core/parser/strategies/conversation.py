from __future__ import annotations

from dataclasses import replace
from typing import Any

from orbitbrief_core.parser.router import ParsePlan
from orbitbrief_core.parser.shared.types import DocumentParse, ReviewCategory, ReviewFlag, ReviewSeverity


class ConversationStrategy:
    name = "conversation"

    def __init__(self, *, mode: str = "conversation") -> None:
        self._mode = mode

    def apply(
        self,
        *,
        document_parse: DocumentParse,
        parse_plan: ParsePlan,
        compiled_pack: Any,
    ) -> DocumentParse:
        spans = []
        for span in document_parse.evidence_spans:
            meta = dict(span.metadata)
            text = span.normalized_text.lower()
            if "?" in span.text:
                meta["conversation_signal"] = "open_question"
            elif any(token in text for token in ("we will", "i will", "commit", "agreed")):
                meta["conversation_signal"] = "commitment"
            elif any(token in text for token in ("decide", "decision", "approved")):
                meta["conversation_signal"] = "decision"
            meta["strategy_mode"] = self._mode
            spans.append(replace(span, metadata=meta))

        flags = list(document_parse.review_flags)
        if parse_plan.discourse_type.value == "call_transcript":
            speaker_spans = [span for span in spans if span.speaker_id]
            if not speaker_spans:
                flags.append(
                    ReviewFlag(
                        flag_id=f"strategy:{document_parse.doc_id}:conversation:no_speakers",
                        severity=ReviewSeverity.WARNING,
                        category=ReviewCategory.AMBIGUITY,
                        message="Conversation strategy found no speaker-linked spans.",
                        metadata={"strategy": self._mode},
                    )
                )

        metadata = dict(document_parse.metadata)
        strategy_diag = list(metadata.get("strategy_diagnostics", []))
        strategy_diag.append(f"{self._mode}:processed_spans={len(spans)}")
        metadata["strategy_diagnostics"] = strategy_diag

        return replace(
            document_parse,
            evidence_spans=tuple(spans),
            review_flags=tuple(flags),
            metadata=metadata,
        )
