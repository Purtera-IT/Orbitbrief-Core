from __future__ import annotations

from orbitbrief_core.parser.site_schematic.models import SiteSchematicRegion


def region_level_output(regions: tuple[SiteSchematicRegion, ...]) -> list[dict]:
    return [region.to_dict() for region in regions]
