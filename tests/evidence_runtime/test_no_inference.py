"""Phase-1 invariant: ``evidence_runtime`` is a no-LLM zone.

If anyone ever needs an embedding, a tokenizer, a vector store, or
any model client inside the runtime, they're in the wrong layer —
that work belongs in ``retrieval`` (Phase 2) or ``brains`` (Phase 4).
This test pins the rule statically: AST-scan every module under
:mod:`orbitbrief_core.evidence_runtime` and reject any forbidden
import.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


# Top-level packages or module prefixes that must NOT appear in any
# import within evidence_runtime. These are the obvious LLM-stack
# offenders; add to the set when new ones are observed in the wild.
FORBIDDEN_IMPORT_PREFIXES: tuple[str, ...] = (
    "torch",
    "transformers",
    "sentence_transformers",
    "openai",
    "anthropic",
    "vllm",
    "outlines",
    "tiktoken",
    "tokenizers",
    "huggingface_hub",
    "langchain",
    "llama_index",
    "llama_cpp",
    "chromadb",
    "qdrant_client",
    "faiss",
    "pinecone",
    "weaviate",
    "lancedb",
    "milvus",
    "ollama",
    "ctransformers",
    # parser-os internal LLM scaffolding (if any) shouldn't leak
    # in either; the runtime only needs the seam types.
    "app.semantic.linker",
)

EVIDENCE_RUNTIME_ROOT = (
    Path(__file__).resolve().parent.parent.parent
    / "src"
    / "orbitbrief_core"
    / "evidence_runtime"
)


def _walk_imports(tree: ast.AST) -> list[tuple[int, str]]:
    """Yield (lineno, module_name) for every import in ``tree``."""
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                out.append((node.lineno, node.module))
    return out


def _violations_for_file(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    bad: list[tuple[int, str]] = []
    for lineno, mod in _walk_imports(tree):
        for prefix in FORBIDDEN_IMPORT_PREFIXES:
            if mod == prefix or mod.startswith(prefix + "."):
                bad.append((lineno, mod))
                break
    return bad


def test_evidence_runtime_root_exists() -> None:
    """Sanity: the directory we're scanning is the right one."""
    assert EVIDENCE_RUNTIME_ROOT.is_dir(), EVIDENCE_RUNTIME_ROOT


def test_evidence_runtime_imports_no_inference_libraries() -> None:
    """No LLM / embedding / vector-store imports anywhere under evidence_runtime."""
    offenders: list[tuple[Path, int, str]] = []
    for py in sorted(EVIDENCE_RUNTIME_ROOT.rglob("*.py")):
        for lineno, mod in _violations_for_file(py):
            offenders.append((py.relative_to(EVIDENCE_RUNTIME_ROOT), lineno, mod))

    if offenders:
        rendered = "\n".join(
            f"  {path}:{lineno}: imports {mod}" for path, lineno, mod in offenders
        )
        pytest.fail(
            "evidence_runtime imported a forbidden inference library:\n" + rendered
        )


def test_forbidden_set_is_actively_enforced() -> None:
    """Self-test: if we accidentally drop the forbidden list to empty, fail."""
    assert FORBIDDEN_IMPORT_PREFIXES, (
        "FORBIDDEN_IMPORT_PREFIXES became empty — the no-inference gate is dead. "
        "Re-add at least the LLM client / embedding / vector-store libraries."
    )
