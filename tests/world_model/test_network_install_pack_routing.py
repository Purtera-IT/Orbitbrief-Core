"""Pack-prior: SD-WAN / Meraki install must not select staff_aug/ALM/commercial."""

from __future__ import annotations

from orbitbrief_core.world_model.pack_prior.router import (
    PackPrior,
    _NETWORK_INSTALL_EVIDENCE_RE,
)


def test_network_install_routing_boosts_network_demotes_staff_alm_commercial():
    raw = {
        "staff_augmentation": 40,
        "alm": 35,
        "commercial": 20,
        "network_maintenance": 5,
        "other": 2,
    }
    matched: dict[str, set[str]] = {k: set() for k in raw}
    corpus = (
        "Remote Hands for 13 offices Transitioning from MPLS to SDWAN "
        "Meraki MX devices turning on circuits at each location"
    )
    assert _NETWORK_INSTALL_EVIDENCE_RE.search(corpus)
    out = PackPrior._apply_network_install_routing(raw, matched, corpus)
    assert out["network_maintenance"] > out["staff_augmentation"]
    assert out["network_maintenance"] > out["alm"]
    assert out["network_maintenance"] > out["commercial"]
    assert out["staff_augmentation"] < raw["staff_augmentation"]
    assert "network_install_evidence" in matched["network_maintenance"]


def test_no_boost_without_network_evidence():
    raw = {"staff_augmentation": 40, "network_maintenance": 5}
    matched: dict[str, set[str]] = {k: set() for k in raw}
    out = PackPrior._apply_network_install_routing(
        raw, matched, "Need cleared badged resources for surge staffing"
    )
    assert out == raw
