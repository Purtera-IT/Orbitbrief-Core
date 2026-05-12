from orbitbrief_core.parser.site_schematic.family_coverage_truth import compute_family_coverage_truth
from orbitbrief_core.parser.site_schematic.grounded_family_derivation import derive_grounded_family
from orbitbrief_core.parser.site_schematic.hardpage_requirement_repair import derive_required_hardpages
from orbitbrief_core.parser.site_schematic.hardpage_semantic_gate_v2_5 import enforce_v2_5_hardpage_gate
from orbitbrief_core.parser.site_schematic.packet_expected_family_deriver import derive_expected_families_from_packet_local_text


def test_expected_family_deriver() -> None:
    families = derive_expected_families_from_packet_local_text(
        legend_texts=["WAP", "PATCH PANEL", "LADDER RACK"],
        outlet_definition_texts=["wireless access point"],
        abbreviation_texts=[],
        page_titles=["TELECOMM RISER DIAGRAM"],
        domain_default_families=["wireless_access_point", "patch_panel_row", "ladder_rack_cable_runway", "riser_endpoint"],
    )
    assert "wireless_access_point" in families


def test_required_hardpages() -> None:
    required = derive_required_hardpages(
        page_rows=[{"sheet_type": "legend_symbol"}, {"sheet_type": "riser_diagram"}],
        schema_required_types=["legend_symbol", "riser_diagram", "floorplan_overall"],
    )
    assert required == ["legend_symbol", "riser_diagram"]


def test_family_coverage_truth() -> None:
    coverage = compute_family_coverage_truth(
        packet_expected_families=["a", "b", "c"],
        grounded_families=["a", "b"],
        hardpage_expected_families=["a", "b"],
        hardpage_grounded_families=["a"],
    )
    assert coverage.expected_family_grounded_coverage_rate == 2 / 3
    assert coverage.hardpage_family_grounded_coverage_rate == 1 / 2


def test_grounded_family_derivation() -> None:
    family = derive_grounded_family(
        legend_text="WAP",
        page_type="riser_diagram",
        connector_context_score=0.6,
        allowed_families=["wireless_access_point", "riser_endpoint"],
    )
    assert family in {"wireless_access_point", "riser_endpoint"}


def test_hardpage_gate() -> None:
    gate = enforce_v2_5_hardpage_gate(
        required_page_types=["legend_symbol", "riser_diagram"],
        hardpage_grounded_symbol_yield_rate=0.8,
        hardpage_family_grounded_coverage_rate=0.9,
    )
    assert gate.ok is True
