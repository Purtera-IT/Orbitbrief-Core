from __future__ import annotations

from typing import Any


def derive_required_hardpages(
    *,
    page_rows: list[dict[str, Any]],
    schema_required_types: list[str],
) -> list[str]:
    present = {str(row.get("sheet_type", "")) for row in page_rows}
    return [page_type for page_type in schema_required_types if page_type in present]
