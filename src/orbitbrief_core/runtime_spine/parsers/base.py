from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .models import ParsedArtifact


class Parser(Protocol):
    parser_id: str
    parser_version: str
    supported_modalities: set[str]

    def parse(self, path: Path, modality: str, role_hint: str | None = None) -> ParsedArtifact:
        ...
