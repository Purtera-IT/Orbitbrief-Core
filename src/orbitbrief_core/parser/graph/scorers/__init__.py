__all__ = [
    "ScorerPolicy",
    "GraphScorerPolicies",
    "SameTopicScoringService",
    "SupportScoringService",
    "PacketSeedScoringService",
    "RegionRelevanceScoringService",
    "evaluate_score_result",
    "apply_fanout",
]


def __getattr__(name: str):
    if name in {"ScorerPolicy", "GraphScorerPolicies"}:
        from orbitbrief_core.parser.graph.scorers.config import GraphScorerPolicies, ScorerPolicy

        return {"ScorerPolicy": ScorerPolicy, "GraphScorerPolicies": GraphScorerPolicies}[name]
    if name in {"SameTopicScoringService", "SupportScoringService", "PacketSeedScoringService", "RegionRelevanceScoringService"}:
        from orbitbrief_core.parser.graph.scorers.packet_seed import PacketSeedScoringService
        from orbitbrief_core.parser.graph.scorers.region_relevance import RegionRelevanceScoringService
        from orbitbrief_core.parser.graph.scorers.same_topic import SameTopicScoringService
        from orbitbrief_core.parser.graph.scorers.support import SupportScoringService

        return {
            "SameTopicScoringService": SameTopicScoringService,
            "SupportScoringService": SupportScoringService,
            "PacketSeedScoringService": PacketSeedScoringService,
            "RegionRelevanceScoringService": RegionRelevanceScoringService,
        }[name]
    if name in {"evaluate_score_result", "apply_fanout"}:
        from orbitbrief_core.parser.graph.scorers.policy import apply_fanout, evaluate_score_result

        return {"evaluate_score_result": evaluate_score_result, "apply_fanout": apply_fanout}[name]
    raise AttributeError(name)
