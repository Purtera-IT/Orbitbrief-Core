"""Root conftest: pythonpath wiring + cross-suite fixtures.

The mixed-envelope fixtures live here (not in ``tests/evidence_runtime/``)
because Phase 2 retrieval tests need them too — pytest auto-discovers
conftests *up* the directory tree, not sideways between siblings.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ────────────────────────────── pytest config ──────────────────────────


def pytest_configure(config: pytest.Config) -> None:
    """Register custom marks so we don't get spurious warnings."""
    config.addinivalue_line(
        "markers",
        "perf: phase-2 latency / throughput gates (slow; usually local-only)",
    )
    config.addinivalue_line(
        "markers",
        "slow: tests that build envelopes from real corpora (10s+ each)",
    )


# ────────────────────────────── shared fixtures ────────────────────────


PARSER_OS_TESTS = Path("/Users/purtera/dev/purtera/parser-os-repo/tests").resolve()


def _import_parser_os_test_helpers():
    """Lazily import parser-os's `test_orbitbrief_envelope` helpers.

    Avoids polluting global ``sys.path`` with parser-os's tests dir
    when no fixture is active.
    """
    if str(PARSER_OS_TESTS) not in sys.path:
        sys.path.insert(0, str(PARSER_OS_TESTS))
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
    root = Path("/Users/purtera/dev/purtera/parser-os-repo/real_data_cases")
    if not root.is_dir():
        pytest.skip(f"parser-os real_data_cases not present at {root}")
    return root


@pytest.fixture(scope="session")
def copper_001_pdf(parser_os_corpus_root: Path) -> Path:
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
    """Real envelope: PDF + XLSX + transcript + email through parser-os."""
    helpers = _import_parser_os_test_helpers()
    tmp = tmp_path_factory.mktemp("phase1_mixed")
    project = tmp / "project"
    project.mkdir()
    helpers._write_mixed_package(project, copper_001_pdf)

    from app.core.compiler import compile_project
    from app.core.orbitbrief_envelope import build_orbitbrief_envelope

    result = compile_project(project_dir=project, project_id="phase1_runtime_smoke")
    return build_orbitbrief_envelope(project_dir=project, compile_result=result)


@pytest.fixture
def mixed_envelope_path(tmp_path: Path, mixed_envelope: dict[str, Any]) -> Path:
    import json

    path = tmp_path / "orbitbrief.input.json"
    path.write_text(
        json.dumps(mixed_envelope, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def mixed_artifact_dir(
    tmp_path_factory: pytest.TempPathFactory, copper_001_pdf: Path
) -> Path:
    helpers = _import_parser_os_test_helpers()
    tmp = tmp_path_factory.mktemp("phase1_artifacts")
    project = tmp / "project"
    project.mkdir()
    helpers._write_mixed_package(project, copper_001_pdf)
    return project
