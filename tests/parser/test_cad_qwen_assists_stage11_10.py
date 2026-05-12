from __future__ import annotations

import time

from orbitbrief_core.parser.graph.neural_hooks import PacketSeedRequest, SameTopicRequest, SupportRequest
from orbitbrief_core.parser.graph.scorers.packet_seed import PacketSeedScoringService
from orbitbrief_core.parser.graph.scorers.region_relevance import RegionCandidate, RegionRelevanceRequest, RegionRelevanceScoringService
from orbitbrief_core.parser.graph.scorers.same_topic import SameTopicScoringService
from orbitbrief_core.parser.graph.scorers.support import SupportScoringService
from orbitbrief_core.runtime_spine.extractors.packet_to_claims import PacketExtractionContext, extract_claims_from_packet


class _Signals:
    lexical_overlap = 0.25
    cue_similarity = 0.2
    same_actor = True


def _cad_packet(*, family: str, text: str) -> dict:
    return {
        "packet_id": "packet:cad:assist:001",
        "span_ids": ("span:anchor", "span:support"),
        "primary_span_id": "span:anchor",
        "confidence": 0.83,
        "evidence_rows": [
            {"span_id": "span:anchor", "text": text, "normalized_text": text.lower()},
            {"span_id": "span:support", "text": "Support snippet: MDF/IDF and escort constraints", "normalized_text": "support snippet"},
        ],
        "metadata": {"packet_family": family, "packet_state": "extract", "uncertainty_markers": ()},
    }


def test_graph_scorers_fail_closed_on_timeout() -> None:
    def _sleep_backend(_request):
        time.sleep(0.2)
        return 0.95

    same_topic = SameTopicScoringService(model_name="qwen:same_topic", backend=_sleep_backend, timeout_ms=10)
    support = SupportScoringService(model_name="qwen:support", backend=_sleep_backend, timeout_ms=10)
    packet_seed = PacketSeedScoringService(model_name="qwen:packet_seed", backend=_sleep_backend, timeout_ms=10)

    same_topic_result = same_topic.score(
        SameTopicRequest(
            left_span_id="s1",
            right_span_id="s2",
            left_text="Room MDF-01 requires escort access",
            right_text="Escort required for MDF support closet",
            signals=_Signals(),
        )
    )
    support_result = support.score(
        SupportRequest(
            anchor_span_id="s1",
            candidate_span_id="s2",
            anchor_text="Room MDF-01 requires escort access",
            candidate_text="Escort required for MDF support closet",
            signals=_Signals(),
        )
    )
    packet_seed_result = packet_seed.score(
        PacketSeedRequest(
            span_id="s1",
            text="Revision note: escort is required",
            family_hints=("constructability_packet",),
            authority_class="high",
            authority_score=0.9,
            local_support_density=0.8,
            cue_strength=0.7,
        )
    )

    assert same_topic_result.abstained is True
    assert same_topic_result.raw_metadata.get("reason") == "backend_timeout"
    assert support_result.abstained is True
    assert support_result.raw_metadata.get("reason") == "backend_timeout"
    assert packet_seed_result.abstained is True
    assert packet_seed_result.raw_metadata.get("reason") == "backend_timeout"


def test_region_relevance_respects_bounded_candidates() -> None:
    seen = {}

    def _backend(request: RegionRelevanceRequest):
        seen["candidate_count"] = len(request.candidate_regions)
        return [(item.region_id, 0.95) for item in request.candidate_regions]

    service = RegionRelevanceScoringService(
        model_name="qwen:region_relevance",
        backend=_backend,
        threshold=0.5,
        max_fanout=2,
        max_candidate_count=1,
    )
    result = service.score(
        RegionRelevanceRequest(
            page_index=0,
            query_text="Find constructability note near telecom room",
            candidate_regions=(
                RegionCandidate(region_id="r1", page_index=0, bbox=None, text="Text 1"),
                RegionCandidate(region_id="r2", page_index=0, bbox=None, text="Text 2"),
            ),
        )
    )
    assert seen["candidate_count"] == 1
    assert len(result) == 1
    assert result[0].region_id == "r1"
    assert result[0].abstained is False


def test_cad_packet_assist_default_off_keeps_deterministic_body(monkeypatch) -> None:
    monkeypatch.delenv("ORBITBRIEF_ENABLE_QWEN_CAD_PACKET_ASSIST", raising=False)
    packet = _cad_packet(family="note_scope_packet", text="Note 3: Provide escort for after-hours access")
    claims, diagnostics = extract_claims_from_packet(packet, PacketExtractionContext(role_id="transcript_or_notes", modality="cad_sheet"))
    assert len(claims) == 1
    assert claims[0].claim_body == "Provide escort for after-hours access"
    assert claims[0].metadata.get("packet_local_model_assist", {}).get("attempted") is False
    assert not any(diag.code.startswith("cad_packet_assist_") for diag in diagnostics)


def test_cad_packet_assist_applies_when_confident(monkeypatch, tmp_path) -> None:
    module_path = tmp_path / "cad_assist_backend.py"
    module_path.write_text(
        "def assist(payload):\n"
        "    return {'normalized_body': 'After-hours escort required for telecom room access', 'confidence': 0.93, 'model_name': 'qwen-vl:test'}\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("ORBITBRIEF_ENABLE_QWEN_CAD_PACKET_ASSIST", "1")
    monkeypatch.setenv("ORBITBRIEF_QWEN_CAD_PACKET_ASSIST_BACKEND", "cad_assist_backend:assist")
    packet = _cad_packet(family="constructability_packet", text="Note 5: escort required")
    claims, diagnostics = extract_claims_from_packet(packet, PacketExtractionContext(role_id="transcript_or_notes", modality="cad_sheet"))
    assert len(claims) == 1
    assert claims[0].claim_body == "After-hours escort required for telecom room access"
    assist_meta = claims[0].metadata.get("packet_local_model_assist", {})
    assert assist_meta.get("applied") is True
    assert assist_meta.get("model_name") == "qwen-vl:test"
    assert any(diag.code == "cad_packet_assist_applied" for diag in diagnostics)

