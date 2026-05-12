from __future__ import annotations

from collections import Counter


_WIRELESS_TOKENS = (
    "wireless",
    "wi-fi",
    "wifi",
    "wap",
    "access point",
    "ap ",
    " ap",
    "camera",
    "cctv",
    "room scheduling",
    "scheduler panel",
    "zigbee",
    "wireless node",
)
_SECURITY_TOKENS = (
    "security",
    "access control",
    "intercom",
    "card reader",
    "door contact",
    "duress",
    "keypad",
    "cctv",
    "camera",
    "intrusion",
    "emergency phone",
)
_MATV_TOKENS = (
    "matv",
    "coax",
    "rg-6",
    "rg-11",
    "satellite dish",
    "headend",
    "tv outlet",
    "iptv",
)
_LOW_VOLTAGE_TOKENS = (
    "mdf",
    "idf",
    "patch panel",
    "conduit",
    "grounding",
    "busbar",
    "cat6",
    "cat-6",
    "fiber",
    "structured cabling",
    "riser",
    "telecomm",
    "telecommunications",
    "voice",
    "data",
    "110 block",
)


def _count(text: str, tokens: tuple[str, ...]) -> int:
    lowered = text.lower()
    return sum(lowered.count(token) for token in tokens)


def compute_document_overlay_hints(page_texts: list[str]) -> dict[str, bool]:
    text = "\n".join(page_texts).lower()
    counter = Counter()
    counter["wireless"] = _count(text, _WIRELESS_TOKENS)
    counter["security"] = _count(text, _SECURITY_TOKENS)
    counter["matv"] = _count(text, _MATV_TOKENS)
    counter["low_voltage"] = _count(text, _LOW_VOLTAGE_TOKENS)
    # Security and MATV packets are still low-voltage, so keep that lane sticky.
    counter["low_voltage"] += counter["security"] + counter["matv"]
    return {
        "default_wireless": counter["wireless"] >= 3,
        "default_security": counter["security"] >= 2,
        "default_matv": counter["matv"] >= 2,
        "default_low_voltage": counter["low_voltage"] >= 3,
    }


def classify_overlay_tags(
    text: str,
    *,
    default_wireless: bool = False,
    default_low_voltage: bool = False,
    default_security: bool = False,
    default_matv: bool = False,
    sheet_type: str = "",
) -> tuple[str, ...]:
    lowered = (text or "").lower()
    tags: list[str] = []
    if (
        default_wireless
        or any(token in lowered for token in _WIRELESS_TOKENS)
        or (
            sheet_type in {"legend_symbol", "floorplan_overall", "floorplan_detail"}
            and any(token in lowered for token in ("ap", "cm", "wm", "wireless node", "camera", "cctv", "zigbee", "ext"))
        )
    ):
        tags.append("wireless")
    if default_security or any(token in lowered for token in _SECURITY_TOKENS):
        tags.append("security")
    if default_matv or any(token in lowered for token in _MATV_TOKENS):
        tags.append("matv")
    if (
        default_low_voltage
        or any(token in lowered for token in _LOW_VOLTAGE_TOKENS)
        or sheet_type in {"notes_spec", "schedule_sheet", "riser_diagram", "rack_detail", "equipment_room_layout", "installation_detail"}
        or "security" in tags
        or "matv" in tags
    ):
        tags.append("low_voltage")
    return tuple(dict.fromkeys(tags))
