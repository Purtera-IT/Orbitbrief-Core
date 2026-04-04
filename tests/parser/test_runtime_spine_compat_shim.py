from __future__ import annotations

from orbitbrief_core import runtime_spine
from orbitbrief_core.parser import registry as parser_registry


def test_runtime_spine_parser_registry_symbol_forwards_to_canonical_parser_registry() -> None:
    assert runtime_spine.ParserRegistry is parser_registry.ParserRegistry


def test_runtime_spine_loader_symbol_forwards_to_canonical_parser_loader() -> None:
    assert runtime_spine.load_parser_registry is parser_registry.load_parser_registry
