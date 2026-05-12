from __future__ import annotations

from dataclasses import dataclass

from orbitbrief_core.parser.graph.indices import GraphIndices
from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.runtime import parse_and_packetize


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
        "09:00 Alice: Deliverable is migration runbook.\n"
        "09:01 Alice: Deliverable includes checklist.\n"
        "09:02 Bob: Risk is permit delay.\n"
        "09:03 Bob: Mitigation is permit pre-check.\n"
        "09:04 Alice: Open question on site count?"
    )
    result = parse_and_packetize(
        router_input=RouterInput(doc_id="graph_neighbors_7_3_001", filename="notes.txt", raw_text_preview=text, metadata={"raw_text": text}),
        compiled_pack=_compiled_pack_stub(),
    )
    return result.document_parse


def test_graph_indices_builds_span_neighbor_ids_deterministically() -> None:
    parsed = _sample_parse()
    indices_a = GraphIndices.from_parse(parsed)
    indices_b = GraphIndices.from_parse(parsed)
    assert indices_a.span_neighbor_ids == indices_b.span_neighbor_ids
    assert indices_a.ordered_spans
    for span in indices_a.ordered_spans:
        neighbors = indices_a.neighbors_for_span(span.span_id)
        assert isinstance(neighbors, tuple)
        assert span.span_id not in neighbors
        # no duplicates
        assert len(neighbors) == len(set(neighbors))


def test_graph_indices_neighbor_semantics_include_local_adjacency() -> None:
    parsed = _sample_parse()
    indices = GraphIndices.from_parse(parsed)
    ordered = indices.ordered_spans
    assert len(ordered) >= 3
    middle = ordered[len(ordered) // 2]
    middle_neighbors = indices.neighbors_for_span(middle.span_id)
    # bounded local contract: previous and next must be present
    assert ordered[len(ordered) // 2 - 1].span_id in middle_neighbors
    assert ordered[len(ordered) // 2 + 1].span_id in middle_neighbors
    # stable ordering by document order
    neighbor_positions = [next(i for i, span in enumerate(ordered) if span.span_id == sid) for sid in middle_neighbors]
    assert neighbor_positions == sorted(neighbor_positions)


def test_graph_indices_neighbors_include_local_section_and_message_when_available() -> None:
    parsed = _sample_parse()
    indices = GraphIndices.from_parse(parsed)
    # same-section bounded neighborhood: if section has >= 3 spans, first should include at least two neighbors
    multi_span_sections = [spans for spans in indices.spans_by_section_path.values() if len(spans) >= 3]
    assert multi_span_sections
    section_spans = multi_span_sections[0]
    first = section_spans[0]
    first_neighbors = indices.neighbors_for_span(first.span_id)
    assert len(first_neighbors) >= 2

    # same-message bounded neighborhood (if parser emitted message ids)
    for spans in indices.spans_by_message_id.values():
        if len(spans) >= 2:
            left = spans[0].span_id
            right = spans[1].span_id
            assert right in indices.neighbors_for_span(left)
            break
