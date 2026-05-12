from __future__ import annotations

from dataclasses import dataclass

from orbitbrief_core.parser.graph import GraphBuildConfig, GraphNeuralHooks
from orbitbrief_core.parser.graph_builder import build_graph
from orbitbrief_core.parser.graph.neural_hooks import PacketSeedRequest, SameTopicRequest, ScoreResult, SupportRequest
from orbitbrief_core.parser.graph.scorers.config import GraphScorerPolicies, ScorerPolicy
from orbitbrief_core.parser.graph.scorers.packet_seed import PacketSeedScoringService
from orbitbrief_core.parser.graph.scorers.same_topic import SameTopicScoringService
from orbitbrief_core.parser.graph.scorers.support import SupportScoringService
from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.runtime import route_and_parse


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
        {"modality": "docx", "parser_profile_id": "parser:professional_services_text:docx"},
        {"modality": "email_export", "parser_profile_id": "parser:professional_services_text:email_export"},
        {"modality": "pdf_text", "parser_profile_id": "parser:professional_services_text:pdf_text"},
        {"modality": "pdf_ocr", "parser_profile_id": "parser:professional_services_text:pdf_ocr"},
    ]
    return _CompiledPackStub(manifest=_ManifestStub(), parser_profiles={"rows": rows})


def _sample_parse():
    compiled_pack = _compiled_pack_stub()
    text = (
        "09:00 Alice: Deliverable is migration runbook.\n"
        "09:03 Alice: Deliverable includes cutover checklist.\n"
        "09:05 Bob: Risk is permit delay.\n"
        "09:07 Bob: Risk mitigation is permit pre-check.\n"
        "09:09 Alice: Open question on final site count?"
    )
    parse_plan, parsed = route_and_parse(
        router_input=RouterInput(doc_id="graph_neural_7_1_001", filename="call.txt", raw_text_preview=text, metadata={"raw_text": text}),
        compiled_pack=compiled_pack,
    )
    return parse_plan, parsed, compiled_pack


class _FakeSameTopicScorer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def score(self, request: SameTopicRequest) -> ScoreResult:
        self.calls.append((request.left_span_id, request.right_span_id))
        score = 0.85 if request.signals.lexical_overlap >= 0.1 else 0.4
        return ScoreResult(score=score, model_name="fake-same-topic", abstained=False)


class _FakeSupportScorer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def score(self, request: SupportRequest) -> ScoreResult:
        self.calls.append((request.anchor_span_id, request.candidate_span_id))
        score = 0.82 if request.signals.same_actor or request.signals.cue_similarity > 0.0 else 0.5
        # Explicit abstain path below policy abstain threshold.
        if score < 0.55:
            return ScoreResult(score=score, model_name="fake-support", abstained=False, raw_metadata={"reason": "low_signal"})
        return ScoreResult(score=score, model_name="fake-support", abstained=False)


class _FakePacketSeedScorer:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def score(self, request: PacketSeedRequest) -> ScoreResult:
        self.calls.append(request.span_id)
        boost = 0.86 if request.family_hints else 0.45
        return ScoreResult(score=boost, model_name="fake-packet-seed", abstained=False)


def test_graph_without_neural_hooks_keeps_deterministic_behavior() -> None:
    parse_plan, parsed, compiled_pack = _sample_parse()
    result = build_graph(
        document_parse=parsed,
        parse_plan=parse_plan,
        compiled_pack=compiled_pack,
        hooks=None,
    )
    assert result.document_parse.evidence_graph.edges
    assert all("neural_score" not in edge.metadata for edge in result.document_parse.evidence_graph.edges)


def test_graph_neural_hooks_score_prefiltered_candidates_only() -> None:
    parse_plan, parsed, compiled_pack = _sample_parse()
    same_topic = _FakeSameTopicScorer()
    support = _FakeSupportScorer()
    packet_seed = _FakePacketSeedScorer()
    config = GraphBuildConfig(
        max_scored_pairs_per_span=2,
        max_scored_support_per_anchor=2,
        scorer_policies=GraphScorerPolicies(
            same_topic=ScorerPolicy(threshold=0.7, abstain_below=0.2, max_fanout=2, enabled=True),
            support=ScorerPolicy(threshold=0.7, abstain_below=0.55, max_fanout=1, enabled=True),
            packet_seed=ScorerPolicy(threshold=0.7, abstain_below=0.2, max_fanout=3, enabled=True),
        ),
    )
    result = build_graph(
        document_parse=parsed,
        parse_plan=parse_plan,
        compiled_pack=compiled_pack,
        config=config,
        hooks=GraphNeuralHooks(
            same_topic_scorer=same_topic,
            support_scorer=support,
            packet_seed_scorer=packet_seed,
        ),
    )
    span_count = len(result.document_parse.evidence_spans)
    assert len(same_topic.calls) <= span_count * config.max_scored_pairs_per_span
    assert len(packet_seed.calls) <= span_count
    # Scored edges preserve explainability metadata.
    neural_edges = [edge for edge in result.document_parse.evidence_graph.edges if "neural_score" in edge.metadata]
    assert neural_edges
    assert any(str(edge.metadata.get("edge_family")) == "same_topic" for edge in neural_edges)
    assert any(str(edge.metadata.get("edge_family")) == "context_for" for edge in neural_edges)
    assert all(edge.metadata.get("reason_codes") for edge in neural_edges)
    # Packet seed metadata carries optional neural annotation.
    seeded = [span for span in result.document_parse.evidence_spans if span.metadata.get("packet_seed_neural")]
    assert seeded
    assert result.scorer_diagnostics
    assert any(item.scorer_name == "same_topic" and item.accepted for item in result.scorer_diagnostics)
    scorer_summary = result.document_parse.metadata.get("graph_scorer_summary", {})
    assert scorer_summary.get("total_scored_candidates", 0) >= len(result.scorer_diagnostics)
    assert scorer_summary.get("accepted_candidates", 0) >= 1


def test_unavailable_neural_backends_fail_closed() -> None:
    parse_plan, parsed, compiled_pack = _sample_parse()
    hooks = GraphNeuralHooks(
        same_topic_scorer=SameTopicScoringService(),
        support_scorer=SupportScoringService(),
        packet_seed_scorer=PacketSeedScoringService(),
    )
    result = build_graph(
        document_parse=parsed,
        parse_plan=parse_plan,
        compiled_pack=compiled_pack,
        hooks=hooks,
    )
    assert result.document_parse.evidence_graph.edges
    assert all("neural_score" not in edge.metadata for edge in result.document_parse.evidence_graph.edges)
    assert result.scorer_diagnostics
    assert all(item.abstained for item in result.scorer_diagnostics)
