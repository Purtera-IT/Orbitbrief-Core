from __future__ import annotations

from dataclasses import dataclass, replace

from orbitbrief_core.parser.graph.indices import GraphIndices
from orbitbrief_core.parser.graph.signals import GraphSignals
from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.runtime import parse_and_packetize
from orbitbrief_core.parser.shared.types import PageRef


@dataclass(frozen=True, slots=True)
class _ManifestStub:
    pack_id: str = "professional_services_text"
    role_id: str = "transcript_or_notes"


@dataclass(frozen=True, slots=True)
class _CompiledPackStub:
    manifest: _ManifestStub
    parser_profiles: dict


def _compiled_pack_stub() -> _CompiledPackStub:
    rows = [
        {"modality": "txt", "parser_profile_id": "parser:professional_services_text:txt"},
        {"modality": "md", "parser_profile_id": "parser:professional_services_text:md"},
        {"modality": "email_export", "parser_profile_id": "parser:professional_services_text:email_export"},
    ]
    return _CompiledPackStub(manifest=_ManifestStub(), parser_profiles={"rows": rows})


def _sample_parse():
    text = (
        "09:00 Alice: Scope includes migration.\n"
        "09:05 Alice: Risk is permit delay.\n"
        "09:10 Bob: Open question on schedule."
    )
    result = parse_and_packetize(
        router_input=RouterInput(doc_id="graph_signals_4_2_001", filename="call.txt", raw_text_preview=text, metadata={"raw_text": text}),
        compiled_pack=_compiled_pack_stub(),
    )
    return result.document_parse


def test_pair_signals_include_raw_and_compatibility_features() -> None:
    parsed = _sample_parse()
    spans = parsed.evidence_spans
    left = replace(spans[0], metadata={**dict(spans[0].metadata), "ocr_confidence": 0.91})
    right = replace(spans[1], metadata={**dict(spans[1].metadata), "ocr_confidence": 0.78})
    parsed = replace(parsed, evidence_spans=(left, right, *spans[2:]))
    signals = GraphSignals(parse=parsed, indices=GraphIndices.from_parse(parsed))

    pair = signals.pair_signals(left.span_id, right.span_id)
    assert 0.0 <= pair.lexical_overlap <= 1.0
    assert pair.section_distance is not None
    assert pair.cue_similarity >= 0.0
    assert pair.ocr_confidence_compatibility is not None


def test_authority_signals_detect_same_actor_conservatively() -> None:
    parsed = _sample_parse()
    spans = parsed.evidence_spans
    alice_spans = [span for span in spans if str(span.metadata.get("speaker_label", "")).lower() == "alice"]
    assert len(alice_spans) >= 2
    signals = GraphSignals(parse=parsed, indices=GraphIndices.from_parse(parsed))

    authority = signals.authority_signals(alice_spans[0].span_id, alice_spans[1].span_id)
    assert authority.same_actor_exact is True
    assert authority.compatible is True
    assert authority.authority_delta <= 0.35


def test_chronology_signals_and_layout_signals() -> None:
    parsed = _sample_parse()
    spans = list(parsed.evidence_spans)
    spans[0] = replace(spans[0], page_ref=PageRef(page_index=1))
    spans[1] = replace(spans[1], page_ref=PageRef(page_index=1))
    spans[2] = replace(spans[2], page_ref=PageRef(page_index=2))
    parsed = replace(parsed, evidence_spans=tuple(spans))
    signals = GraphSignals(parse=parsed, indices=GraphIndices.from_parse(parsed))

    chronology = signals.chronology_signals(spans[0].span_id, spans[1].span_id)
    assert chronology.both_ranked is True
    assert chronology.chronology_distance is not None

    layout_same = signals.layout_signals(spans[0].span_id, spans[1].span_id)
    layout_diff = signals.layout_signals(spans[0].span_id, spans[2].span_id)
    assert layout_same.same_page is True
    assert layout_diff.same_page is False
    assert layout_diff.page_distance is not None


def test_cue_signals_are_cached_and_reusable_across_calls() -> None:
    parsed = _sample_parse()
    spans = parsed.evidence_spans
    signals = GraphSignals(parse=parsed, indices=GraphIndices.from_parse(parsed))

    cue_first = signals.cue_signals(spans[0].span_id, spans[1].span_id)
    cue_second = signals.cue_signals(spans[0].span_id, spans[1].span_id)
    pair_first = signals.pair_signals(spans[0].span_id, spans[1].span_id)
    pair_second = signals.pair_signals(spans[0].span_id, spans[1].span_id)

    assert cue_first is cue_second
    assert pair_first is pair_second
    assert cue_first.cue_similarity >= 0.0
