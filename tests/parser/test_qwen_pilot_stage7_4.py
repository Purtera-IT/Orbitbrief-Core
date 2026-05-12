from __future__ import annotations

from pathlib import Path

from orbitbrief_core.parser.graph.neural_hooks import SameTopicRequest
from orbitbrief_core.parser.graph.qwen_pilot import build_qwen_graph_hooks_from_env
from orbitbrief_core.runtime_spine.pipeline import run_pipeline


class _Signals:
    lexical_overlap = 0.2


def test_qwen_graph_hooks_are_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("ORBITBRIEF_ENABLE_QWEN_SCORERS", raising=False)
    assert build_qwen_graph_hooks_from_env() is None


def test_qwen_graph_hooks_abstain_cleanly_without_backend(monkeypatch) -> None:
    monkeypatch.setenv("ORBITBRIEF_ENABLE_QWEN_SCORERS", "1")
    hooks = build_qwen_graph_hooks_from_env()
    assert hooks is not None
    assert hooks.same_topic_scorer is not None
    result = hooks.same_topic_scorer.score(
        SameTopicRequest(
            left_span_id="left",
            right_span_id="right",
            left_text="Los Angeles office support",
            right_text="Los Angeles HQ support",
            signals=_Signals(),
        )
    )
    assert result.abstained is True
    assert result.model_name == "qwen:same_topic"


def test_runtime_stays_green_when_qwen_hooks_are_enabled_without_backends(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ORBITBRIEF_ENABLE_QWEN_SCORERS", "1")
    artifact = tmp_path / "notes.txt"
    artifact.write_text(
        "Project overview\nPurTera will provide dedicated support from the Los Angeles office across five locations.\nRisk permit delay.",
        encoding="utf-8",
    )

    result = run_pipeline(artifact, include_runtime_result=True)
    runtime_result = result["runtime_result"]

    assert runtime_result.pipeline_state in {"extract", "intake_only"}
    assert runtime_result.parse_runtime_result.document_parse.metadata.get("graph_builder") is not None
