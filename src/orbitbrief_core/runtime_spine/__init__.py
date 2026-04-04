"""Legacy runtime_spine compatibility surface.

This shim intentionally avoids maintaining a second parser registry truth.
When compatibility callers request parser registry symbols, they are forwarded
to the canonical parser package control plane.
"""

from __future__ import annotations

__all__ = [
    "run_pipeline",
    "parse_extract_and_postprocess",
    "ParserRegistry",
    "load_parser_registry",
    "ExtractorRegistry",
    "load_extractor_registry",
    "PipelineDecision",
    "decide_pipeline_state",
]


def __getattr__(name: str):
    if name == "run_pipeline":
        from .pipeline import run_pipeline  # type: ignore

        return run_pipeline
    if name == "parse_extract_and_postprocess":
        from .pipeline import parse_extract_and_postprocess  # type: ignore

        return parse_extract_and_postprocess
    if name == "ParserRegistry":
        from orbitbrief_core.parser.registry import ParserRegistry

        return ParserRegistry
    if name == "load_parser_registry":
        from orbitbrief_core.parser.registry import load_parser_registry

        return load_parser_registry
    if name == "ExtractorRegistry":
        from orbitbrief_core.runtime_spine.extractors.registry import ExtractorRegistry

        return ExtractorRegistry
    if name == "load_extractor_registry":
        from orbitbrief_core.runtime_spine.extractors.registry import load_extractor_registry

        return load_extractor_registry
    if name == "PipelineDecision":
        from orbitbrief_core.runtime_spine.fallback import PipelineDecision

        return PipelineDecision
    if name == "decide_pipeline_state":
        from orbitbrief_core.runtime_spine.fallback import decide_pipeline_state

        return decide_pipeline_state
    raise AttributeError(name)
