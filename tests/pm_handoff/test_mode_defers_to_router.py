"""The router decides the workstream; the lexicon must not overrule it.

`project_mode` drives which questions the PM asks the customer, which gaps are
shown, and which domains survive filtering. It was being decided twice: once by
the router, and again by a cascade of keyword checks that ran first and won.

Measured over 20 live deals with DeepSeek gold labels:

    today (cascade wins)                     5/20   25%
    defer to the router, veto on dense AV   15/20   75%
    defer to the router, no AV veto         19/20   95%

Clayton is the case that motivated it: a 437-store dispatch job labelled
`staff_augmentation`, routed to `wireless` by a head measured at 0.529, and
consequently asked for an AP count, a channel plan and a wireless design owner.
"""
from __future__ import annotations

from orbitbrief_core.pm_handoff.question_engine import (
    MODE_AV,
    MODE_CABLING,
    MODE_NETWORK_EDGE_INSTALL,
    MODE_STAFF_AUG,
    MODE_WIRELESS_CONFIG,
    MODE_WIRELESS_INSTALL,
    detect_project_mode,
)

CLAYTON_ISH = (
    "Retail onsite support across 437 stores. Collect the store SSID and "
    "wifi credentials from the manager on arrival. Technician dispatch per "
    "site with a weekend rate."
)


def test_router_pack_decides_the_mode():
    """The words say wifi; the work is dispatch. The router knows which."""
    assert detect_project_mode(
        service_routing={"primary": "staff_augmentation", "confidence": 0.9},
        blob=CLAYTON_ISH,
    ) == MODE_STAFF_AUG


def test_wifi_vocabulary_does_not_hijack_a_dispatch_deal():
    """Before this change, a bare SSID mention was enough to return
    wireless_install and hand the PM seven wireless questions."""
    mode = detect_project_mode(
        service_routing={"primary": "staff_augmentation"}, blob=CLAYTON_ISH
    )
    assert mode != MODE_WIRELESS_INSTALL


def test_dense_av_vocabulary_does_not_override_the_router():
    """A cabling job that mentions displays is still a cabling job. This veto
    was wrong on four of twenty live deals, which is why it is gone."""
    blob = (
        "Pull cat6 to 40 drops and terminate at the patch panel. Displays, "
        "projector and video conferencing screens are being installed by "
        "others in the same rooms; coordinate with the AV vendor on the "
        "display mounts and the projector screen locations."
    )
    assert detect_project_mode(
        service_routing={"primary": "low_voltage_cabling"}, blob=blob
    ) == MODE_CABLING


def test_av_deals_still_route_to_av():
    assert detect_project_mode(
        service_routing={"primary": "audio_visual"},
        blob="Install Neat Bar and Yealink codec in twelve conference rooms.",
    ) == MODE_AV


def test_sub_type_refinements_survive():
    """Two things the router cannot express, because both are a sub-type of the
    pack it already picked rather than a different pack."""
    assert detect_project_mode(
        service_routing={"primary": "wireless"},
        blob="Configuration only: no physical install, remote AP config only.",
    ) == MODE_WIRELESS_CONFIG
    assert detect_project_mode(
        service_routing={"primary": "network_maintenance"},
        blob="Deploy Meraki MX at 30 branches with SD-WAN cutover.",
    ) == MODE_NETWORK_EDGE_INSTALL


def test_an_abstaining_router_falls_back_to_evidence():
    """The head abstains on most packs by design; the lexicon still has to work
    when it does."""
    mode = detect_project_mode(
        service_routing={"primary": "wireless", "abstained": True},
        blob="Install 40 access points and run a wireless heatmap survey.",
    )
    assert mode == MODE_WIRELESS_INSTALL


def test_an_unmapped_pack_falls_through():
    """Packs with no dedicated question set must not swallow the cascade."""
    mode = detect_project_mode(
        service_routing={"primary": "procurement_finance"},
        blob="Install 40 access points and run a wireless heatmap survey.",
    )
    assert mode == MODE_WIRELESS_INSTALL
