from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from orbitbrief_core.parser.shared.types import AuthorityClass, DocumentParse, PacketCandidate, PacketKind

_PACKET_FAMILY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("scope_packet", ("scope", "in scope", "included")),
    ("exclusion_packet", ("exclude", "out of scope", "not included", "exclusion")),
    ("assumption_packet", ("assumption", "assume")),
    ("risk_packet", ("risk", "issue", "blocker")),
    ("dependency_packet", ("dependency", "depends on")),
    ("site_packet", ("site", "location")),
    ("quantity_packet", ("qty", "quantity", "count", "number of")),
    ("deliverable_packet", ("deliverable", "output", "handoff")),
    ("schedule_packet", ("schedule", "timeline", "date", "week", "month")),
    ("responsibility_packet", ("responsibility", "owner", "customer", "by others")),
    ("open_question_packet", ("?", "open question", "unknown", "tbd")),
)


@dataclass(frozen=True, slots=True)
class PacketizerResult:
    packets: tuple[PacketCandidate, ...]
    diagnostics: tuple[str, ...] = ()


def build_packets(document_parse: DocumentParse, *, compiled_pack: Any | None = None) -> PacketizerResult:
    diagnostics: list[str] = []
    spans = list(document_parse.evidence_spans)
    packets: list[PacketCandidate] = []
    packet_index = 0

    for family_name, keywords in _PACKET_FAMILY_KEYWORDS:
        family_spans = []
        for span in spans:
            text = span.normalized_text.lower()
            section_text = " ".join(span.section_path).lower()
            parser_cues = span.metadata.get("parser_cues", [])
            blob = " ".join([text, section_text, " ".join(parser_cues) if isinstance(parser_cues, list) else ""])
            if any(keyword in blob for keyword in keywords):
                family_spans.append(span)
        if not family_spans:
            continue

        primary = sorted(family_spans, key=lambda span: (-span.authority_score, span.span_id))[0]
        ordered = sorted(family_spans, key=lambda span: span.span_id)
        span_ids = tuple(span.span_id for span in ordered)
        confidence = max(0.3, min(0.95, sum(span.authority_score for span in family_spans) / len(family_spans)))
        packet_id = f"packet:{family_name}:{packet_index:04d}"
        packet_index += 1
        packets.append(
            PacketCandidate(
                packet_id=packet_id,
                packet_kind=PacketKind.CLAIM,
                span_ids=span_ids,
                primary_span_id=primary.span_id,
                confidence=confidence,
                authority_class=AuthorityClass.FIRST_PASS if confidence >= 0.6 else AuthorityClass.UNKNOWN,
                metadata={
                    "packet_family": family_name,
                    "packet_policy": document_parse.metadata.get("adapter_context", {}).get("packet_policy"),
                    "span_count": len(span_ids),
                },
            )
        )
        diagnostics.append(f"packetized:{family_name}:{len(span_ids)}")

    return PacketizerResult(
        packets=tuple(sorted(packets, key=lambda packet: packet.packet_id)),
        diagnostics=tuple(diagnostics),
    )
