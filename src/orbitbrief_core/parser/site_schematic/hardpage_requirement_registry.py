from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class HardpageRequirement:
    packet_id: str
    required_page_types: tuple[str, ...] = field(default_factory=tuple)


def derive_required_hardpage_types(page_rows: list[dict[str, Any]]) -> list[str]:
    present = {str(row.get("sheet_type", "")) for row in page_rows}
    ordered = [
        "legend_symbol",
        "riser_diagram",
        "equipment_room_layout",
        "installation_detail",
        "floorplan_overall",
    ]
    return [sheet_type for sheet_type in ordered if sheet_type in present]
