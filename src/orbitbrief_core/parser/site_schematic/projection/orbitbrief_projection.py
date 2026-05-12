from __future__ import annotations

from orbitbrief_core.parser.site_schematic.models import SiteSchematicBundle


def build_orbitbrief_projection(bundle: SiteSchematicBundle) -> dict:
    linked_wireless = [link.to_dict() for link in bundle.symbol_links if link.status != "unresolved" and link.symbol_token.upper() in {"AP", "WAP", "CM", "WM", "EXT"}]
    return {
        "wireless_access_points": linked_wireless,
        "network_room_mentions": [page.room_labels for page in bundle.pages if any(room.startswith(("MDF", "IDF", "TR")) for room in page.room_labels)],
        "summary": bundle.summary(),
    }
