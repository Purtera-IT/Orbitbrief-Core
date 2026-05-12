from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List


@dataclass
class PacketHardpageSummary:
    packet_id: str
    required_page_types: List[str] = field(default_factory=list)
    satisfied_page_types: List[str] = field(default_factory=list)

    @property
    def rate(self) -> float:
        if not self.required_page_types:
            return 1.0
        return len(set(self.satisfied_page_types)) / len(set(self.required_page_types))


def build_packet_hardpage_summary(packet_id: str, page_rows: Iterable[Dict[str, object]]) -> PacketHardpageSummary:
    page_rows = list(page_rows)
    required = []
    present_types = {str(r.get("sheet_type", "")) for r in page_rows}
    for t in ["legend_symbol", "riser_diagram", "equipment_room_layout", "installation_detail", "floorplan_overall"]:
        if t in present_types:
            required.append(t)

    satisfied = []
    for r in page_rows:
        st = str(r.get("sheet_type", ""))
        if st in required:
            if bool(r.get("legend_grounding_ok", False)) and (not bool(r.get("connector_required", False)) or bool(r.get("connector_grounding_ok", False))):
                satisfied.append(st)

    return PacketHardpageSummary(packet_id=packet_id, required_page_types=required, satisfied_page_types=satisfied)
