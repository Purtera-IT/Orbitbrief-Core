from __future__ import annotations

from typing import Dict, Iterable, List


def derive_required_hardpages(
    *,
    page_rows: Iterable[Dict[str, object]],
    schema_required_types: Iterable[str],
) -> List[str]:
    present = {str(r.get("sheet_type", "")) for r in page_rows}
    schema_required_types = list(schema_required_types)
    return [t for t in schema_required_types if t in present]
