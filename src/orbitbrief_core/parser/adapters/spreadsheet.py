from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orbitbrief_core.parser.adapters.base import AbstractAdapter, AdapterInfo
from orbitbrief_core.parser.adapters.common import add_flag, extract_path, make_builder
from orbitbrief_core.parser.adapters.spreadsheet_common import extract_spreadsheet_blocks, is_noise_sheet_name
from orbitbrief_core.parser.router import ParsePlan, RouterInput
from orbitbrief_core.parser.shared.types import ReviewCategory, ReviewSeverity


@dataclass(frozen=True, slots=True)
class SpreadsheetParseConfig:
    max_blocks: int = 96
    emit_sheet_review_flags: bool = True


class SpreadsheetAdapter(AbstractAdapter):
    info = AdapterInfo(
        name="SpreadsheetAdapter",
        modality="xlsx",
        description="Deterministic spreadsheet adapter for managed-services deal kits, rosters, and tabular packages.",
        optional_dependencies=("openpyxl",),
    )

    def __init__(self, config: SpreadsheetParseConfig | None = None) -> None:
        self._config = config or SpreadsheetParseConfig()

    def parse(self, *, router_input: RouterInput, parse_plan: ParsePlan, compiled_pack: Any):
        builder = make_builder(router_input=router_input, parse_plan=parse_plan, compiled_pack=compiled_pack)
        root_section_id = builder.add_section(
            title="WORKBOOK",
            section_path=("WORKBOOK",),
            metadata={"synthetic": True, "adapter": "spreadsheet"},
        )
        builder.set_section_root(root_section_id)

        path = extract_path(router_input)
        if path is None or not Path(path).exists():
            add_flag(
                builder,
                severity=ReviewSeverity.HIGH,
                category=ReviewCategory.QUALITY,
                message="Spreadsheet path was not available to the adapter.",
                metadata={"adapter": "spreadsheet"},
            )
            return builder.build()

        blocks = extract_spreadsheet_blocks(Path(path), max_blocks_per_sheet=max(12, self._config.max_blocks // 4))
        if not blocks:
            add_flag(
                builder,
                severity=ReviewSeverity.WARNING,
                category=ReviewCategory.QUALITY,
                message="Spreadsheet contained no relevant managed-services summary or row facts after deterministic filtering.",
                metadata={"adapter": "spreadsheet", "path": str(path)},
            )
            return builder.build()

        section_ids: dict[str, str] = {}
        chronology_rank = 0
        for block in blocks[: self._config.max_blocks]:
            section_id = section_ids.get(block.sheet_name)
            if section_id is None:
                section_path = ("WORKBOOK", block.sheet_name)
                section_id = builder.add_section(
                    title=block.sheet_name,
                    section_path=section_path,
                    parent_section_id=root_section_id,
                    metadata={
                        "adapter": "spreadsheet",
                        "sheet_name": block.sheet_name,
                        "noise_sheet": is_noise_sheet_name(block.sheet_name),
                    },
                )
                section_ids[block.sheet_name] = section_id

            span_id = builder.add_span(
                text=block.text,
                normalized_text=block.text.lower(),
                section_path=("WORKBOOK", block.sheet_name),
                chronology_rank=chronology_rank,
                authority_score=0.92 if block.kind == "spreadsheet_kv" else 0.9,
                metadata={
                    **dict(block.metadata),
                    "adapter": "spreadsheet",
                    "source_modality": parse_plan.metadata.get("modality", "xlsx"),
                },
            )
            builder.attach_span_to_section(span_id, section_id)
            chronology_rank += 1

        if self._config.emit_sheet_review_flags:
            skipped = tuple(router_input.metadata.get("spreadsheet_skipped_sheets", ())) if isinstance(router_input.metadata, dict) else ()
            if skipped:
                add_flag(
                    builder,
                    severity=ReviewSeverity.INFO,
                    category=ReviewCategory.QUALITY,
                    message="Spreadsheet helper/lookup sheets were ignored by the managed-services lane.",
                    metadata={"adapter": "spreadsheet", "skipped_sheets": list(skipped)},
                )
        return builder.build()
