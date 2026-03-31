from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ParserSpan:
    start: int
    end: int
    page_or_sheet: str | None = None


@dataclass(slots=True)
class ParsedBlock:
    block_id: str
    block_type: str
    text: str | None = None
    cells: dict[str, Any] | None = None
    span: ParserSpan | None = None
    confidence: float = 1.0
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ParsedArtifact:
    parser_id: str
    parser_version: str
    role_hint: str | None
    modality: str
    source_path: str
    source_hash: str
    blocks: list[ParsedBlock] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
