from __future__ import annotations

from orbitbrief_core.parser.site_schematic.models import SiteSchematicSymbolLink


def wireless_symbol_links(symbol_links: tuple[SiteSchematicSymbolLink, ...]) -> tuple[SiteSchematicSymbolLink, ...]:
    return tuple(link for link in symbol_links if link.symbol_token.upper() in {"AP", "WAP", "CM", "WM", "EXT", "CCTV"} or "wireless" in (link.legend_label or "").lower())
