from __future__ import annotations

from pathlib import Path

from .container import ContainerParser
from .drawing_vector import DrawingVectorParser
from .pdf_ocr import PdfOcrParser
from .pdf_text import PdfTextParser
from .text_narrative import TextNarrativeParser
from .tabular import TabularParser
from .models import ParsedArtifact


class ParserRegistry:
    def __init__(self) -> None:
        self._parsers = {
            "text_narrative_parser": TextNarrativeParser(),
            "tabular_parser": TabularParser(),
            "pdf_text_parser": PdfTextParser(),
            "pdf_ocr_parser": PdfOcrParser(),
            "drawing_vector_parser": DrawingVectorParser(),
            "container_parser": ContainerParser(),
        }

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
