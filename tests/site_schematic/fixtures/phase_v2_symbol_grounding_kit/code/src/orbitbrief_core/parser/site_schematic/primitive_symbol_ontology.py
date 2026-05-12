from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

UNIVERSAL_PRIMITIVE_FAMILIES = [
    "ap_wap_marker",
    "data_outlet_marker",
    "av_endpoint_marker",
    "room_scheduler_marker",
    "cctv_camera_marker",
    "door_contact_marker",
    "access_intercom_marker",
    "telecom_rack_front",
    "patch_panel_row",
    "ladder_rack_runway",
    "riser_endpoint",
    "conduit_pathway",
    "pull_or_junction_box",
    "pathway_support_symbol",
    "wall_phone_marker",
    "unknown_symbol_group",
]

@dataclass
class PrimitiveSymbolOntologyEntry:
    family: str
    aliases: List[str] = field(default_factory=list)
    notes: str = ""

DEFAULT_V2_ONTOLOGY = [
    PrimitiveSymbolOntologyEntry("ap_wap_marker", ["ap", "wap", "wireless access point"]),
    PrimitiveSymbolOntologyEntry("data_outlet_marker", ["data", "cat6", "telecom outlet"]),
    PrimitiveSymbolOntologyEntry("av_endpoint_marker", ["av", "projector", "ceiling control"]),
    PrimitiveSymbolOntologyEntry("room_scheduler_marker", ["room scheduler", "rs1", "rs2", "rs3"]),
    PrimitiveSymbolOntologyEntry("cctv_camera_marker", ["camera", "cctv"]),
    PrimitiveSymbolOntologyEntry("door_contact_marker", ["door contact", "dc"]),
    PrimitiveSymbolOntologyEntry("access_intercom_marker", ["intercom", "card reader", "access"]),
    PrimitiveSymbolOntologyEntry("telecom_rack_front", ["rack", "cabinet", "mdf", "idf"]),
    PrimitiveSymbolOntologyEntry("patch_panel_row", ["patch panel"]),
    PrimitiveSymbolOntologyEntry("ladder_rack_runway", ["ladder rack", "runway"]),
    PrimitiveSymbolOntologyEntry("riser_endpoint", ["riser", "endpoint"]),
    PrimitiveSymbolOntologyEntry("conduit_pathway", ["conduit", "pathway"]),
    PrimitiveSymbolOntologyEntry("pull_or_junction_box", ["pull box", "junction box", "jbox", "pb"]),
    PrimitiveSymbolOntologyEntry("pathway_support_symbol", ["j-hook", "support"]),
    PrimitiveSymbolOntologyEntry("wall_phone_marker", ["wallphone", "telephone"]),
]
