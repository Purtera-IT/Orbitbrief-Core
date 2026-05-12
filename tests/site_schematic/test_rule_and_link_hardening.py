from __future__ import annotations

from orbitbrief_core.parser.site_schematic.extractors.common import build_structured_rule_sets, extract_note_clauses
from orbitbrief_core.parser.site_schematic.models import SiteSchematicLegendEntry, SiteSchematicSymbolInstance
from orbitbrief_core.parser.site_schematic.symbols.linker import link_symbol_instances


def test_extract_note_clauses_keeps_color_cable_lines() -> None:
    text = """
BLUE ALL DATA SYSTEM CABLE.
GRAY GUESTROOM VOICE CABLE.
YELLOW WIRELESS NODE CABLE.
""".strip()
    clauses = extract_note_clauses(text)
    assert any("blue" in row.lower() and "data" in row.lower() for row in clauses)
    assert any("gray" in row.lower() and "guestroom voice" in row.lower() for row in clauses)
    assert any("yellow" in row.lower() and "wireless node" in row.lower() for row in clauses)
    rules = build_structured_rule_sets(page_index=2, clauses=clauses)
    meanings = " ".join(row.meaning.lower() for row in rules["color_conventions"])
    assert "all data system cable" in meanings
    assert "guestroom voice cable" in meanings
    assert "wireless node cable" in meanings


def test_ap_link_includes_patch_panel_note_when_present() -> None:
    symbol = SiteSchematicSymbolInstance(
        instance_id="symbol:p1:1",
        page_index=1,
        token="AP",
        primitive_kind="wireless_access_point",
        text="AP",
        confidence=0.9,
        overlay_tags=("wireless",),
        source_mode="heuristic",
    )
    legend = SiteSchematicLegendEntry(
        entry_id="legend:p1:1",
        page_index=1,
        section="wireless",
        label="WIRELESS ACCESS POINT",
        description="WIRELESS ACCESS POINT OUTLET",
        primitive_kind="wireless_access_point",
        symbol_token="AP",
        overlay_tags=("wireless",),
        confidence=0.9,
    )
    links = link_symbol_instances(
        symbol_instances=(symbol,),
        legend_entries=(legend,),
        note_clauses=(
            "PROVIDE 20 FEET OF CABLE SLACK FOR WIRELESS ACCESS POINTS.",
            "TERMINATE WAP CABLES ON DEDICATED PATCH PANEL.",
        ),
        room_labels=(),
    )
    assert links and links[0].status == "linked"
    combined = " ".join(links[0].related_note_clauses).lower()
    assert "slack" in combined
    assert "patch panel" in combined


def test_extract_note_clauses_rejoins_wireless_split_lines() -> None:
    text = """
PROVIDE 20' OF CABLE SLACK FOR WIRELESS ACCESS POINTS.
TERMINATE WAP CABLES ON
DEDICATED PATCH PANEL.
FOR WIRELESS ACCESS POINTS, TC TO MOUNT WAP BRACKET AND WAP (BOTH OWNER
PROVIDED).
""".strip()
    clauses = extract_note_clauses(text)
    joined = " ".join(clauses).lower()
    assert "terminate wap cables on dedicated patch panel" in joined
    assert "owner provided" in joined or "both owner provided" in joined
