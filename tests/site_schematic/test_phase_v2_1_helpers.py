from orbitbrief_core.parser.site_schematic.connector_grounding_refinement import refine_with_connector_context
from orbitbrief_core.parser.site_schematic.grounding_state_policy import choose_grounding_state
from orbitbrief_core.parser.site_schematic.legend_text_association import score_legend_text_association
from orbitbrief_core.parser.site_schematic.packet_hardpage_semantics import build_packet_hardpage_summary


def test_grounding_state_policy() -> None:
    out = choose_grounding_state(
        legend_match_score=0.9,
        text_association_score=0.8,
        connector_score=0.8,
        room_device_score=0.8,
        page_type_compatibility=0.9,
    )
    assert out.state == "grounded"


def test_connector_refinement() -> None:
    out = refine_with_connector_context(
        base_score=0.5,
        has_connector_candidate=True,
        has_leader_attachment=True,
        riser_context=True,
        rack_pathway_context=False,
    )
    assert out.adjusted_score > 0.5


def test_legend_text_association() -> None:
    score = score_legend_text_association(
        legend_text="WAP",
        nearby_note_text="Provide wireless access point cabling",
        outlet_definition_text="AP location",
        abbreviation_text="WAP - wireless access point",
    )
    assert score > 0.0


def test_packet_hardpage_summary() -> None:
    rows = [
        {"sheet_type": "legend_symbol", "legend_grounding_ok": True, "connector_required": False},
        {"sheet_type": "riser_diagram", "legend_grounding_ok": True, "connector_required": True, "connector_grounding_ok": True},
    ]
    summary = build_packet_hardpage_summary("packet", rows)
    assert summary.rate == 1.0
