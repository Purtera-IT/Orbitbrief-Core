from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class PacketHardpageSummary:
    packet_id: str
    required_page_types: tuple[str, ...] = field(default_factory=tuple)
    satisfied_page_types: tuple[str, ...] = field(default_factory=tuple)

    @property
    def rate(self) -> float:
        required = set(self.required_page_types)
        if not required:
            return 1.0
        return len(set(self.satisfied_page_types)) / len(required)


def build_packet_hardpage_summary(packet_id: str, page_rows: list[dict[str, Any]]) -> PacketHardpageSummary:
    present_types = {str(row.get("sheet_type", "")) for row in page_rows}
    required: list[str] = []
    for sheet_type in [
        "legend_symbol",
        "riser_diagram",
        "equipment_room_layout",
        "rack_detail",
        "installation_detail",
        "floorplan_overall",
    ]:
        if sheet_type in present_types:
            required.append(sheet_type)
    satisfied: list[str] = []
    for row in page_rows:
        sheet_type = str(row.get("sheet_type", ""))
        if sheet_type not in required:
            continue
        legend_ok = bool(row.get("legend_grounding_ok", False))
        connector_required = bool(row.get("connector_required", False))
        connector_ok = bool(row.get("connector_grounding_ok", False))
        if legend_ok and (not connector_required or connector_ok):
            satisfied.append(sheet_type)
    return PacketHardpageSummary(
        packet_id=packet_id,
        required_page_types=tuple(required),
        satisfied_page_types=tuple(satisfied),
    )
