from __future__ import annotations

from orbitbrief_core.parser.site_schematic.models import SiteSchematicLegendEntry


def low_voltage_legend_entries(entries: tuple[SiteSchematicLegendEntry, ...]) -> tuple[SiteSchematicLegendEntry, ...]:
    return tuple(entry for entry in entries if "low_voltage" in entry.overlay_tags or any(term in entry.description.lower() for term in ("patch panel", "conduit", "ground", "fiber", "cat6", "voice", "data")))
