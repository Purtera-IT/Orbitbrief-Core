from __future__ import annotations

from pathlib import Path
import zipfile

from ..file_utils import sha256_file
from .models import ParsedArtifact, ParsedBlock


class ContainerParser:
    parser_id = "container_parser"
    parser_version = "0.1.0"
    supported_modalities = {"zip"}

    def parse(self, path: Path, modality: str, role_hint: str | None = None) -> ParsedArtifact:
        members: list[str] = []
        with zipfile.ZipFile(path, "r") as zf:
            members = zf.namelist()
        blocks = [
            ParsedBlock(
                block_id=f"member_{idx+1}",
                block_type="container_member",
                text=member,
                confidence=1.0,
            )
            for idx, member in enumerate(members)
        ]
        return ParsedArtifact(
            parser_id=self.parser_id,
            parser_version=self.parser_version,
            role_hint=role_hint,
            modality=modality,
            source_path=str(path),
            source_hash=sha256_file(path),
            blocks=blocks,
            metadata={"member_count": len(members)},
        )
