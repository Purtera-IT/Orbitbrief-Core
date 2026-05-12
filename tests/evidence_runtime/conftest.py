"""Phase-1 fixtures: build real envelopes from parser-os fixtures."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest


# Make the parser-os test helpers importable so we can reuse
# `_write_mixed_package`, which constructs a minimal multi-artifact
# project (PDF + XLSX + transcript + email). We do this lazily so the
# parser-os test directory is added to ``sys.path`` only inside this
# conftest's scope, not globally.
PARSER_OS_TESTS = Path("/Users/purtera/dev/purtera/parser-os-repo/tests").resolve()


def _import_parser_os_test_helpers():
    if str(PARSER_OS_TESTS) not in sys.path:
        sys.path.insert(0, str(PARSER_OS_TESTS))
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "parser_os_envelope_tests",
        str(PARSER_OS_TESTS / "test_orbitbrief_envelope.py"),
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def parser_os_corpus_root() -> Path:
    """Real-data root inside parser-os."""
    root = Path("/Users/purtera/dev/purtera/parser-os-repo/real_data_cases")
    if not root.is_dir():
        pytest.skip(f"parser-os real_data_cases not present at {root}")
    return root


@pytest.fixture(scope="session")
def copper_001_pdf(parser_os_corpus_root: Path) -> Path:
    """Single, deterministic real-data PDF used by the mixed-package builder."""
    pdf = (
        parser_os_corpus_root
        / "COPPER_001_SPRING_LAKE_AUDITORIUM"
        / "CASE_DOSSIER.pdf"
    )
    if not pdf.is_file():
        pytest.skip(f"COPPER_001 dossier PDF not available at {pdf}")
    return pdf


@pytest.fixture
def mixed_envelope(
    tmp_path_factory: pytest.TempPathFactory, copper_001_pdf: Path
) -> dict[str, Any]:
    """A full envelope built from a 4-artifact mixed-package project.

    Real PDF + XLSX + transcript + email run through parser-os so we
    exercise every code path the runtime cares about (atoms, edges,
    packets, entities, indexes).
    """
    helpers = _import_parser_os_test_helpers()
    tmp = tmp_path_factory.mktemp("phase1_mixed")
    project = tmp / "project"
    project.mkdir()
    helpers._write_mixed_package(project, copper_001_pdf)

    from app.core.compiler import compile_project
    from app.core.orbitbrief_envelope import build_orbitbrief_envelope

    result = compile_project(project_dir=project, project_id="phase1_runtime_smoke")
    envelope = build_orbitbrief_envelope(project_dir=project, compile_result=result)
    return envelope


@pytest.fixture
def mixed_envelope_path(
    tmp_path: Path, mixed_envelope: dict[str, Any]
) -> Path:
    """Same envelope as :func:`mixed_envelope` but persisted to disk."""
    import json

    path = tmp_path / "orbitbrief.input.json"
    # Use the same canonical form the runtime stores so on-disk and
    # in-DB representations agree byte-for-byte.
    path.write_text(json.dumps(mixed_envelope, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def mixed_artifact_dir(
    tmp_path_factory: pytest.TempPathFactory, copper_001_pdf: Path
) -> Path:
    """Project directory with the original input files, suitable for replay."""
    helpers = _import_parser_os_test_helpers()
    tmp = tmp_path_factory.mktemp("phase1_artifacts")
    project = tmp / "project"
    project.mkdir()
    helpers._write_mixed_package(project, copper_001_pdf)
    return project
