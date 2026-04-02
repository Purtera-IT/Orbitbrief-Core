"""Legacy runtime_spine compatibility surface.

The parser/compiler flow bundle in this workspace omits several older runtime_spine
modules. Keep package importable for tests and downstream compatibility without
forcing eager imports of missing modules.
"""

from __future__ import annotations

__all__ = ["run_pipeline", "ParserRegistry"]


def __getattr__(name: str):
    if name == "run_pipeline":
        from .pipeline import run_pipeline  # type: ignore

        return run_pipeline
    if name == "ParserRegistry":
        from .parsers import ParserRegistry  # type: ignore

        return ParserRegistry
    raise AttributeError(name)
