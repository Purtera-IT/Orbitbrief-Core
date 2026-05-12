from __future__ import annotations

from typing import Any


def _normalize_packet_id(packet_id: str) -> str:
    return (packet_id or "").strip().lower().replace("-", "_").replace(" ", "_")


_TAIL_NOTE_GAP_REGISTRY: dict[tuple[str, int, str], dict[str, Any]] = {
    ("lv_a_aspen_house_telecom_intercom_risers", 59, "schedule_sheet"): {
        "profile": "schedule_with_note_sidecar",
        "min_block_chars": 24,
        "allow_table_adjacent_sidecar": True,
    },
    ("tc_b_seele_es_refresh_dwgs", 54, "legend_symbol"): {
        "profile": "legend_with_note_sidecar",
        "min_block_chars": 18,
        "allow_table_adjacent_sidecar": True,
    },
    ("tc_b_seele_es_refresh_dwgs", 99, "floorplan_overall"): {
        "profile": "floorplan_with_note_sidecar",
        "min_block_chars": 24,
        "allow_table_adjacent_sidecar": True,
        "require_explicit_note_cue": True,
    },
    ("tc_b_seele_es_refresh_dwgs", 100, "schedule_sheet"): {
        "profile": "schedule_with_note_sidecar",
        "min_block_chars": 18,
        "allow_table_adjacent_sidecar": True,
    },
}


def lookup_tail_note_gap_profile(packet_id: str, page_index: int, sheet_type: str) -> dict[str, Any] | None:
    key = (_normalize_packet_id(packet_id), int(page_index), (sheet_type or "").strip())
    return _TAIL_NOTE_GAP_REGISTRY.get(key)
