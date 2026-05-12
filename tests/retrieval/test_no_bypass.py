"""Phase-2 layering test: composer / brains / validator / calibrator
can't bypass retrieval.

The actual layers exist as of Phase 5+; this test verifies the
``no-retrieval-bypass`` lint contract still names every protected
source layer so a refactor can't silently drop one.

Two complementary checks:

1. The lint contract is named in ``.importlinter`` (so a refactor
   doesn't silently drop it).
2. ``RetrievalHit`` carries no body field — the runtime contract
   bound on the data side, not just the import side.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from orbitbrief_core.retrieval import RetrievalHit


REPO_ROOT = Path(__file__).resolve().parents[2]
LINT_CONFIG = REPO_ROOT / ".importlinter"


def test_importlinter_contract_exists() -> None:
    """``.importlinter`` declares the no-retrieval-bypass contract."""
    assert LINT_CONFIG.is_file(), LINT_CONFIG
    text = LINT_CONFIG.read_text(encoding="utf-8")
    # Spot-check the rule by name and the four protected source modules.
    assert "no-retrieval-bypass" in text
    for layer in (
        "orbitbrief_core.composer",
        "orbitbrief_core.brains",
        "orbitbrief_core.validator",
        "orbitbrief_core.calibrator",
    ):
        assert layer in text, f"layer {layer} not protected by no-retrieval-bypass"
    # And the forbidden target.
    assert "orbitbrief_core.retrieval" in text


def test_evidence_runtime_no_inference_contract_exists() -> None:
    """``evidence_runtime`` cannot import inference / retrieval (Phase 1 invariant pinned by lint)."""
    text = LINT_CONFIG.read_text(encoding="utf-8")
    assert "evidence-runtime-no-inference" in text


def test_retrieval_hit_carries_no_body() -> None:
    """RetrievalHit fields: ``id``, ``score``, ``kind``, ``metadata`` only.

    A regression that adds a ``text`` / ``body`` / ``snippet`` field
    here would defeat the entire bounded-IO point of the retrieval
    layer (callers could read bodies without going through the
    runtime, breaking provenance).
    """
    fields = set(RetrievalHit.__dataclass_fields__.keys())
    assert fields == {"id", "score", "kind", "metadata"}, fields


def test_retrieval_does_not_import_evidence_runtime_internals() -> None:
    """Retrieval reaches into evidence_runtime via the *public* facade only.

    Specifically: it may import :class:`EvidenceRuntime` and
    :class:`RuntimeKey`, but not :mod:`evidence_runtime.store`,
    :mod:`evidence_runtime.contradictions`, etc. (those are
    implementation details).
    """
    import ast

    retrieval_root = REPO_ROOT / "src" / "orbitbrief_core" / "retrieval"
    forbidden = {
        "orbitbrief_core.evidence_runtime.store",
        "orbitbrief_core.evidence_runtime.contradictions",
        "orbitbrief_core.evidence_runtime.provenance",
        "orbitbrief_core.evidence_runtime.query",
    }
    offenders: list[tuple[str, int, str]] = []
    for py in sorted(retrieval_root.rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in forbidden:
                offenders.append((str(py.relative_to(retrieval_root)), node.lineno, node.module))
    if offenders:
        rendered = "\n".join(f"  {f}:{ln}: {m}" for f, ln, m in offenders)
        pytest.fail("retrieval reached into evidence_runtime internals:\n" + rendered)
