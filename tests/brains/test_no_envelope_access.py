"""The brains layer must never reach into the envelope, runtime, or seam.

Phase-5 verify gate. Two complementary checks:

1. **import-linter contracts** (``brains-no-substrate`` and the
   pre-existing ``no-retrieval-bypass``) reject any forbidden
   import. We invoke the linter programmatically and assert all
   contracts are kept.
2. **AST scan** of every ``.py`` file under
   ``src/orbitbrief_core/brains/`` confirms no module names a
   forbidden symbol via ``import`` or ``from``. Belt-and-braces:
   the AST scan would catch even a deferred local import that an
   import-graph analyzer might miss.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
BRAINS_ROOT = REPO_ROOT / "src" / "orbitbrief_core" / "brains"

# Anything under these prefixes is forbidden inside brains.
FORBIDDEN_PREFIXES: tuple[str, ...] = (
    "orbitbrief_core.evidence_runtime",
    "orbitbrief_core.seam",
    "orbitbrief_core.retrieval",
    "orbitbrief_core.world_model.pack_prior",
    "orbitbrief_core.world_model.site_reality",
    "orbitbrief_core.world_model.refiner",
    "orbitbrief_core.world_model.planner.runner",
    # Parser-os internals (envelopes are produced from these).
    "app.parsers",
    "app.segmentation",
    "parser_os.parsers",
    "parser_os.segmentation",
)


def _iter_brain_modules() -> Iterable[Path]:
    if not BRAINS_ROOT.is_dir():
        return ()
    return [p for p in BRAINS_ROOT.rglob("*.py") if p.is_file()]


def _import_targets(tree: ast.AST) -> set[str]:
    """All dotted names this module imports (``import x.y`` and ``from x.y import z``)."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod:
                out.add(mod)
    return out


def test_ast_scan_no_forbidden_imports() -> None:
    """No brain file imports anything under :data:`FORBIDDEN_PREFIXES`."""
    violations: list[tuple[str, str]] = []
    for py in _iter_brain_modules():
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for dotted in _import_targets(tree):
            for prefix in FORBIDDEN_PREFIXES:
                if dotted == prefix or dotted.startswith(prefix + "."):
                    violations.append(
                        (str(py.relative_to(REPO_ROOT)), dotted)
                    )
    assert not violations, (
        "brains layer reached into substrate / parser-os internals:\n"
        + "\n".join(f"  {p}: {sym}" for p, sym in violations)
    )


def test_import_linter_contracts_are_kept() -> None:
    """All import-linter contracts (including the brains contracts) report KEPT."""
    importlinter_cli = pytest.importorskip("importlinter.cli")
    runner = importlinter_cli.lint_imports
    # ``lint_imports`` returns 0 on success, non-zero on broken contracts.
    rc = runner(
        config_filename=str(REPO_ROOT / ".importlinter"),
        is_debug_mode=False,
        show_timings=False,
        verbose=False,
    )
    assert rc == 0, "import-linter reported a broken contract"


def test_brains_can_import_allowed_layers() -> None:
    """Sanity: the explicitly allowed dependencies still work."""
    # Smoke import to make sure Phase-5 didn't accidentally break the
    # brain's own surface.
    from orbitbrief_core.brains.managed_services import ManagedServicesBrain  # noqa: F401
    from orbitbrief_core.brains import RetrievalBundle  # noqa: F401
    from orbitbrief_core.world_model.planner.schema import BriefState  # noqa: F401
    from orbitbrief_core.inference import OpenAIChatClient  # noqa: F401
