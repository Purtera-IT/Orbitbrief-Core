from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import yaml

from ..config import repo_root
from .models import ParsedArtifact


class ParserRegistry:
    def __init__(self) -> None:
        config_path = repo_root() / "config" / "runtime" / "parsers" / "parser_registry.yaml"
        payload = yaml.safe_load(config_path.read_text())
        self._parsers: dict[str, Any] = {}
        for entry in payload.get("parsers", []):
            parser_id = entry["parser_id"]
            module = importlib.import_module(entry["module"])
            parser_cls = getattr(module, entry["class_name"])
            self._parsers[parser_id] = parser_cls()

    def by_modality(self, modality: str):
        for parser in self._parsers.values():
            if modality in parser.supported_modalities:
                return parser
        raise KeyError(f"No parser registered for modality: {modality}")

    def parse(self, path: Path, modality: str, role_hint: str | None = None) -> ParsedArtifact:
        parser = self.by_modality(modality)
        return parser.parse(path, modality, role_hint=role_hint)

    def parser_ids(self) -> list[str]:
        return sorted(self._parsers.keys())
