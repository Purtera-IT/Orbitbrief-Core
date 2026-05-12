from __future__ import annotations

from typing import Any


def enforce_nonempty_required_hardpages(
    *,
    page_rows: list[dict[str, Any]],
    schema_required_types: list[str],
) -> list[str]:
    present = {str(row.get("sheet_type", "")) for row in page_rows}
    required = [sheet_type for sheet_type in schema_required_types if sheet_type in present]
    return required
