from __future__ import annotations

from typing import Any


def select_grounding_sample_rows(rows: list[dict[str, Any]], limit: int = 25) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for row in rows:
        selected.append(
            {
                "grounded_family": row.get("grounded_family"),
                "grounding_state": row.get("grounding_state"),
                "legend_match_score": row.get("legend_match_score"),
                "legend_text_association_score": row.get("legend_text_association_score"),
                "room_device_association_score": row.get("room_device_association_score"),
                "connector_context_score": row.get("connector_context_score"),
                "page_type_compatibility": row.get("page_type_compatibility"),
                "connector_grounding_ok": row.get("connector_grounding_ok"),
                "room_device_association_ok": row.get("room_device_association_ok"),
            }
        )
        if len(selected) >= limit:
            break
    return selected
