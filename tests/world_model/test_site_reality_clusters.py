"""Site-reality clusters the synthetic 3-site / 4-source dataset correctly."""
from __future__ import annotations

from typing import Any

from orbitbrief_core.world_model.site_reality import SiteRealityEngine


def test_three_site_envelope_collapses_to_three_clusters(
    runtime_from_envelope, three_site_envelope: dict[str, Any]
) -> None:
    """5 site keys across 4 sources → 3 logical sites (A × 2 keys merged twice)."""
    engine = SiteRealityEngine(chat_client=None)
    rt = runtime_from_envelope(three_site_envelope)
    state = engine.compute(rt)
    assert state.cluster_count == 3, [c.cluster_id for c in state.clusters]
    # Two pairs merged: A's two keys (via co_mention) and C's two keys
    # (via canonical_name match). One singleton (B).
    assert state.merged_keys == 2, state.merged_keys


def test_clusters_carry_their_artifact_provenance(
    runtime_from_envelope, three_site_envelope: dict[str, Any]
) -> None:
    """Each cluster lists every artifact that touched any of its site keys."""
    engine = SiteRealityEngine(chat_client=None)
    rt = runtime_from_envelope(three_site_envelope)
    state = engine.compute(rt)
    by_name = {c.canonical_name: c for c in state.clusters}
    a = by_name["Building A"]
    c = by_name["Building C"]
    b = by_name["Building B"]
    assert set(a.artifact_ids) == {"src_pdf", "src_xlsx"}, a.artifact_ids
    assert set(c.artifact_ids) == {"src_email", "src_transcript"}, c.artifact_ids
    assert set(b.artifact_ids) == {"src_pdf"}, b.artifact_ids


def test_cluster_ids_are_stable_across_runs(
    runtime_from_envelope, three_site_envelope: dict[str, Any]
) -> None:
    """Same envelope → same cluster ids and same internal ordering."""
    engine = SiteRealityEngine(chat_client=None)
    rt1 = runtime_from_envelope(three_site_envelope)
    rt2 = runtime_from_envelope(three_site_envelope)
    s1 = engine.compute(rt1).model_dump_json()
    s2 = engine.compute(rt2).model_dump_json()
    assert s1 == s2


def test_no_chat_client_no_escalation(
    runtime_from_envelope, three_site_envelope: dict[str, Any]
) -> None:
    """Without a chat client, no escalation entries should be logged."""
    engine = SiteRealityEngine(chat_client=None)
    rt = runtime_from_envelope(three_site_envelope)
    state = engine.compute(rt)
    assert state.escalation_log["count"] == 0
    for cluster in state.clusters:
        assert cluster.name_resolved_by_llm is False
