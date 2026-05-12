from __future__ import annotations

from orbitbrief_core.parser.site_schematic.models import SiteSchematicObservation


def observation_node_label(observation: SiteSchematicObservation) -> str:
    return f"{observation.kind}: {observation.text[:80]}"
