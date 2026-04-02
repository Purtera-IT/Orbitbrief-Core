from __future__ import annotations

from dataclasses import replace

from orbitbrief_core.parser.shared.types import AuthorityClass, DocumentParse, ReviewCategory, ReviewFlag, ReviewSeverity


def apply_authority_scoring(document_parse: DocumentParse) -> tuple[DocumentParse, tuple[str, ...]]:
    diagnostics: list[str] = []
    spans = []
    flags = list(document_parse.review_flags)
    for span in document_parse.evidence_spans:
        kind = str(span.metadata.get("kind", "")).lower()
        text = span.normalized_text.lower()
        authority = span.authority_score
        authority_class = span.authority_class
        noise_tags: list[str] = []

        if kind in {"quoted_context", "forwarded_context"}:
            authority = min(authority, 0.3)
            authority_class = AuthorityClass.UNKNOWN
            noise_tags.append("quoted_or_forwarded")
        if kind in {"email_noise"} or any(token in text for token in ("confidential", "disclaimer", "do not distribute")):
            authority = min(authority, 0.2)
            authority_class = AuthorityClass.UNKNOWN
            noise_tags.append("boilerplate")
        if any(token in text for token in ("maybe", "might", "perhaps", "possibly")):
            authority = min(authority, 0.45)
            noise_tags.append("speculative")
        if kind in {"email_current", "speaker_turn"}:
            authority = max(authority, 0.82)
            authority_class = AuthorityClass.FIRST_PASS

        meta = dict(span.metadata)
        if noise_tags:
            meta["noise_tags"] = sorted(set(noise_tags))
            flags.append(
                ReviewFlag(
                    flag_id=f"authority:{document_parse.doc_id}:{span.span_id}",
                    severity=ReviewSeverity.INFO,
                    category=ReviewCategory.AUTHORITY_GAP,
                    message="Span authority adjusted due to noise/speculation context.",
                    span_id=span.span_id,
                    metadata={"noise_tags": sorted(set(noise_tags))},
                )
            )
            diagnostics.append(f"authority_demoted:{span.span_id}")

        spans.append(
            replace(
                span,
                authority_score=max(0.0, min(1.0, authority)),
                authority_class=authority_class,
                metadata=meta,
            )
        )

    return replace(document_parse, evidence_spans=tuple(spans), review_flags=tuple(flags)), tuple(diagnostics)
