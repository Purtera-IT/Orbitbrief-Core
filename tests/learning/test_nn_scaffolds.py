"""Unit tests for the six disconnected NN scaffolds.

Verifies each one:

1. Imports without side effects
2. Exposes ``IS_ACTIVE = False``
3. Has its ``training_data_builder`` and ``eval_harness`` stubs raise
   ``NotImplementedError`` when called (so a misconfigured production
   deployment fails LOUD instead of silently no-op'ing)
4. Has a ``config.yaml`` file
5. Has a ``README.md`` documenting the activation path

Also asserts the top-level ``IS_ANY_ACTIVE`` aggregate is False — so
the orchestrator (which can check that single flag) defaults to the
heuristic path.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest


SCAFFOLDS = [
    "entity_cross_encoder",
    "embedding_head_finetune",
    "atom_type_classifier",
    "pm_rejection_classifier",
    "gap_rule_generator",
    "margin_regression",
]


@pytest.fixture
def scaffolds_dir() -> Path:
    """Absolute path to the nn_scaffolds directory."""
    from orbitbrief_core import learning
    learning_dir = Path(learning.__file__).parent
    return learning_dir / "nn_scaffolds"


# ──────────────────────────────────────────────────────────────────
# Per-scaffold smoke tests
# ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", SCAFFOLDS)
def test_scaffold_imports_cleanly(name: str) -> None:
    """Every scaffold must import without side effects."""
    mod = importlib.import_module(f"orbitbrief_core.learning.nn_scaffolds.{name}")
    assert mod is not None


@pytest.mark.parametrize("name", SCAFFOLDS)
def test_scaffold_is_active_false(name: str) -> None:
    """Every scaffold MUST default to IS_ACTIVE = False."""
    mod = importlib.import_module(f"orbitbrief_core.learning.nn_scaffolds.{name}")
    assert hasattr(mod, "IS_ACTIVE"), f"{name} missing IS_ACTIVE sentinel"
    assert mod.IS_ACTIVE is False, f"{name}.IS_ACTIVE was {mod.IS_ACTIVE}, not False"


@pytest.mark.parametrize("name", SCAFFOLDS)
def test_scaffold_training_builder_raises(name: str) -> None:
    """Calling the training-data builder before activation raises loudly."""
    mod = importlib.import_module(
        f"orbitbrief_core.learning.nn_scaffolds.{name}.training_data_builder"
    )
    # Find the public build/mine function (one per module; conventional name varies)
    candidates = [
        getattr(mod, n)
        for n in dir(mod)
        if (n.startswith("build_") or n.startswith("mine_"))
        and callable(getattr(mod, n))
    ]
    assert candidates, f"{name}.training_data_builder has no build_/mine_ function"
    build_fn = candidates[0]
    with pytest.raises(NotImplementedError, match="scaffolded but not connected"):
        # Try calling with positional None — different signatures, but each
        # raises NotImplementedError before any real work.
        try:
            build_fn(None)
        except TypeError:
            # Some builders take a Config dataclass; try with an empty kwargs dict.
            build_fn({})  # type: ignore[arg-type]


@pytest.mark.parametrize("name", SCAFFOLDS)
def test_scaffold_eval_harness_raises(name: str) -> None:
    """Calling the eval harness before activation raises loudly."""
    mod = importlib.import_module(
        f"orbitbrief_core.learning.nn_scaffolds.{name}.eval_harness"
    )
    candidates = [
        getattr(mod, n)
        for n in dir(mod)
        if n.startswith("evaluate") and callable(getattr(mod, n))
    ]
    assert candidates, f"{name}.eval_harness has no evaluate* function"
    eval_fn = candidates[0]
    with pytest.raises(NotImplementedError, match="scaffolded but not connected"):
        # Call with placeholder args; eval_fn raises before doing anything
        try:
            eval_fn("dummy_model_path", "dummy_test_path")
        except TypeError:
            try:
                eval_fn("dummy_model_path")
            except TypeError:
                eval_fn(None)


@pytest.mark.parametrize("name", SCAFFOLDS)
def test_scaffold_has_config_yaml(name: str, scaffolds_dir: Path) -> None:
    config_path = scaffolds_dir / name / "config.yaml"
    assert config_path.exists(), f"{name}/config.yaml missing"
    content = config_path.read_text(encoding="utf-8")
    assert "SCAFFOLDED" in content, (
        f"{name}/config.yaml should mark itself SCAFFOLDED"
    )


@pytest.mark.parametrize("name", SCAFFOLDS)
def test_scaffold_has_readme(name: str, scaffolds_dir: Path) -> None:
    readme = scaffolds_dir / name / "README.md"
    assert readme.exists(), f"{name}/README.md missing"
    content = readme.read_text(encoding="utf-8")
    assert "NOT ACTIVE" in content, f"{name}/README.md should label itself NOT ACTIVE"
    assert "Activation gates" in content or "Activation path" in content, (
        f"{name}/README.md must document activation path or gates"
    )


# ──────────────────────────────────────────────────────────────────
# Top-level integration
# ──────────────────────────────────────────────────────────────────


def test_top_level_is_any_active_false() -> None:
    """The aggregate IS_ANY_ACTIVE must be False — defines the
    behavior of every orchestrator gate check."""
    from orbitbrief_core.learning.nn_scaffolds import IS_ANY_ACTIVE
    assert IS_ANY_ACTIVE is False


def test_top_level_imports_all_six_sentinels() -> None:
    """All six per-module sentinels must be importable from the parent."""
    from orbitbrief_core.learning.nn_scaffolds import (
        ATOM_TYPE_CLASSIFIER_ACTIVE,
        EMBEDDING_HEAD_FINETUNE_ACTIVE,
        ENTITY_CROSS_ENCODER_ACTIVE,
        GAP_RULE_GENERATOR_ACTIVE,
        MARGIN_REGRESSION_ACTIVE,
        PM_REJECTION_CLASSIFIER_ACTIVE,
    )
    assert all(
        v is False
        for v in [
            ATOM_TYPE_CLASSIFIER_ACTIVE,
            EMBEDDING_HEAD_FINETUNE_ACTIVE,
            ENTITY_CROSS_ENCODER_ACTIVE,
            GAP_RULE_GENERATOR_ACTIVE,
            MARGIN_REGRESSION_ACTIVE,
            PM_REJECTION_CLASSIFIER_ACTIVE,
        ]
    )


def test_lora_scaffold_still_present() -> None:
    """The 7th (LoRA) scaffold from the earlier commit must still exist."""
    from orbitbrief_core.learning.lora_scaffold import IS_ACTIVE
    assert IS_ACTIVE is False


def test_top_level_readme_lists_all_six() -> None:
    """The nn_scaffolds/README.md must list every scaffold by name."""
    from orbitbrief_core import learning
    readme = Path(learning.__file__).parent / "nn_scaffolds" / "README.md"
    content = readme.read_text(encoding="utf-8")
    for name in SCAFFOLDS:
        assert name in content, f"nn_scaffolds/README.md does not mention {name}"


def test_no_scaffold_imports_torch_or_heavy_libs() -> None:
    """Scaffolds must not import torch / transformers / etc. at module level
    — they only describe what WOULD be done, not actually do it. Importing
    the scaffold should be free of heavy ML dependencies so production
    services that don't activate them never pay the import cost."""
    import sys

    # Snapshot heavy modules NOT imported before importing the scaffolds
    forbidden = {"torch", "transformers", "sentence_transformers", "peft", "trl"}
    before = set(sys.modules.keys())
    for name in SCAFFOLDS:
        importlib.import_module(f"orbitbrief_core.learning.nn_scaffolds.{name}")
        importlib.import_module(
            f"orbitbrief_core.learning.nn_scaffolds.{name}.training_data_builder"
        )
        importlib.import_module(
            f"orbitbrief_core.learning.nn_scaffolds.{name}.eval_harness"
        )
    after = set(sys.modules.keys())
    newly_imported = (after - before) & forbidden
    assert not newly_imported, (
        f"NN scaffolds illegally imported heavy ML libs: {newly_imported}. "
        "Scaffolds must be import-cost-free."
    )
