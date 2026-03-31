from __future__ import annotations

from pathlib import Path

from ..file_utils import load_csv_rows, load_xlsx_rows, sha256_file
from .models import ParsedArtifact, ParsedBlock


class TabularParser:
    parser_id = "tabular_parser"
    parser_version = "0.1.0"
    supported_modalities = {"csv", "xlsx", "xls"}

    def parse(self, path: Path, modality: str, role_hint: str | None = None) -> ParsedArtifact:
        if modality == "csv":
            headers, rows = load_csv_rows(path)
            sheet_name = "csv"
        elif modality in {"xlsx", "xls"}:
            sheet_name, headers, rows = load_xlsx_rows(path)
        else:
            raise ValueError(f"Unsupported tabular modality: {modality}")

        blocks = [
            ParsedBlock(
                block_id=f"row_{idx+1}",
                block_type="table_row",
                cells=row,
                confidence=0.95,
                tags=[sheet_name],
            )
            for idx, row in enumerate(rows)
        ]
        return ParsedArtifact(
            parser_id=self.parser_id,
            parser_version=self.parser_version,
            role_hint=role_hint,
            modality=modality,
            source_path=str(path),
            source_hash=sha256_file(path),
            blocks=blocks,
            metadata={"sheet_name": sheet_name, "headers": headers, "row_count": len(rows)},
        )
