"""Two claims the brief made that the evidence disagreed with.

Audited 2026-09-04 on live 010300, a Yealink phone rollout:

    "010301: Staff augmentation at 2970 Brandywine RD STE 200 - 2970
     Brandywine Rd · access points, controllers, firewalls and more"

Wrong twice in one line. The equipment is from a March 2025 NewBold/CDW
statement of work that the envelope marks ``third_party_terms: true`` — a
different programme for a different customer. And the site is printed as its
own address twice, which then appeared in four of the twelve questions the PM
was asked to answer.

Both were already answerable from the envelope: ``scope_truth`` had adjudicated
the equipment, and the site row carried "HQ" beside its street.
"""
from __future__ import annotations

from orbitbrief_core.pm_handoff.builder import (
    _adjudicated_devices,
    _build_one_line_summary,
    _display_name_from_aliases,
)

# The envelope's own answer to "what are we installing", authority already
# applied, so a third party's contract cannot outvote our scope.
YEALINK_SCOPE_TRUTH = {
    "scope_truth": {
        "devices": [
            {"device": "device:mp38_whe2_teams", "canonical_quantity": 1},
            {"device": "device:mps2_e2_teams", "canonical_quantity": 1},
            {"device": "device:mps6_e2_teams", "canonical_quantity": 1},
        ]
    }
}
# What the rollup union sees: every device key on the deal, ours and theirs.
THIRD_PARTY_ROLLUPS = [
    {"site_key": "s1", "devices": ["access point", "controller", "firewall", "camera"]}
]


def test_the_headline_names_what_this_deal_installs() -> None:
    devices = _adjudicated_devices(YEALINK_SCOPE_TRUTH)
    assert devices == ["MP38 WHE2 Teams", "MPS2 E2 Teams", "MPS6 E2 Teams"]
    line = _build_one_line_summary(
        "010301", [], [], [], project_mode="staff_aug",
        site_rollups=THIRD_PARTY_ROLLUPS, scope_devices=devices,
    )
    assert "MP38 WHE2 Teams" in line
    for theirs in ("access point", "controller", "firewall"):
        assert theirs not in line, "a third party's equipment is not our headline"


def test_without_an_adjudicated_scope_the_rollup_still_answers() -> None:
    """Deals whose scope truth is empty must not lose their headline."""
    line = _build_one_line_summary(
        "010301", [], [], [], project_mode="staff_aug",
        site_rollups=THIRD_PARTY_ROLLUPS, scope_devices=[],
    )
    assert "access points" in line


def test_an_envelope_with_no_scope_truth_yields_no_devices() -> None:
    assert _adjudicated_devices({}) == []
    assert _adjudicated_devices({"scope_truth": {"devices": []}}) == []


def test_a_site_is_named_once_not_twice() -> None:
    """Live aliases from 010300. "HQ" was rejected for being upper-case, so the
    label fell through to code-plus-address and printed the street twice."""
    label = _display_name_from_aliases(
        ["2970-BRANDYWINE-RD-STE-200", "HQ", "2970 Brandywine Rd"]
    )
    assert label == "HQ - 2970 Brandywine Rd"


def test_a_code_that_only_repeats_its_address_is_dropped() -> None:
    """Clayton printed "5000 Clayton RD Maryville TN 37804 - 5000 Clayton Rd,
    Maryville, TN 37804" — one place, spelled twice."""
    label = _display_name_from_aliases(
        ["5000-CLAYTON-RD", "5000 Clayton Rd, Maryville, TN 37804"]
    )
    assert label == "5000 Clayton Rd, Maryville, TN 37804"


def test_a_real_facility_name_still_wins() -> None:
    assert (
        _display_name_from_aliases(
            ["HC-100", "Clayton Homes of Laurinburg", "12021 Andrew Jackson Highway"]
        )
        == "Clayton Homes of Laurinburg"
    )


def test_a_code_that_adds_information_keeps_its_address() -> None:
    assert (
        _display_name_from_aliases(["MARICOPA-COUNTY", "615 N 48th St, Phoenix, AZ 85008"])
        == "Maricopa County - 615 N 48th St, Phoenix, AZ 85008"
    )


def test_a_short_name_with_no_street_stands_alone() -> None:
    assert _display_name_from_aliases(["NOC"]) == "NOC"


def test_a_slug_is_still_the_last_resort() -> None:
    assert _display_name_from_aliases(["site_palo_alto_ca_94304"]) == "Site Palo Alto CA 94304"


def test_the_devices_are_read_from_the_envelope_not_the_inspection_report() -> None:
    """`report` in build_pm_handoff is the inspection report, which does not
    carry scope_truth. The first cut of this read it there, found nothing every
    time, and the headline went on naming a third party's equipment even after
    the fix shipped."""
    import inspect

    from orbitbrief_core.pm_handoff import builder

    src = inspect.getsource(builder.build_pm_handoff)
    assert "scope_devices=_adjudicated_devices(full_envelope or report)" in src

    assert _adjudicated_devices({"artifacts": []}) == []
    assert _adjudicated_devices(YEALINK_SCOPE_TRUTH) == [
        "MP38 WHE2 Teams",
        "MPS2 E2 Teams",
        "MPS6 E2 Teams",
    ]
