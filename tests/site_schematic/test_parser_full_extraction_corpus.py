from __future__ import annotations

from pathlib import Path

import json

from .parser_full_extraction_eval import ARTIFACT_ROOT, run_parser_full_extraction_corpus


def test_parser_full_extraction_corpus_artifacts_exist() -> None:
    summary_path = ARTIFACT_ROOT / "corpus_summary.json"
    if summary_path.exists():
        report = json.loads(summary_path.read_text(encoding="utf-8"))
        root = ARTIFACT_ROOT
    else:
        result = run_parser_full_extraction_corpus()
        report = result["corpus_summary"]
        root = Path(result["artifact_root"])
    assert report["document_count"] == 12
    assert (root / "corpus_manifest.json").exists()
    assert (root / "corpus_summary.json").exists()
    assert (root / "corpus_summary.md").exists()
    assert (root / "corpus_readiness_for_vision.md").exists()
