"""Regression tests for the SiteCandidateKind classifier (PR 11)."""
from __future__ import annotations

from orbitbrief_core.world_model.site_reality.site_kind import (
    SiteCandidateKind as K,
    classify_site_candidate,
    is_publishable,
)


def _ent(name: str) -> dict:
    return {"canonical_name": name}


def test_real_school_is_physical_site():
    assert classify_site_candidate("site:banks_high_school", _ent("Banks High School")) == K.physical_site


def test_courtroom_is_physical_site():
    assert classify_site_candidate("site:flmd_courtroom_5d", _ent("FLMD Courtroom 5D")) == K.physical_site


def test_district_core_is_building():
    assert classify_site_candidate("site:district_core", _ent("District Core")) == K.building


def test_address_is_address():
    assert classify_site_candidate("site:13050_nw_main_st", _ent("13050 NW Main St")) == K.address


def test_mdf_is_room_or_closet():
    assert classify_site_candidate("site:mdf_2", _ent("MDF 2")) == K.room_or_closet


def test_role_drops():
    assert classify_site_candidate("site:customer_network_engineer", _ent("Customer Network Engineer")) == K.role_or_person


def test_director_drops():
    assert classify_site_candidate("site:customer_it_director", _ent("Customer IT Director")) == K.role_or_person


def test_powered_edge_drops():
    assert classify_site_candidate("site:poweredge_r760xd_vms", _ent("PowerEdge R760XD VMS")) == K.equipment_or_product


def test_servicenow_drops():
    assert classify_site_candidate("site:servicenow", _ent("ServiceNow")) == K.service_or_software


def test_genetec_security_center_drops():
    """Genetec is in both the equipment and service regex; either
    classification is fine — both are non-publishable."""
    k = classify_site_candidate("site:genetec_security_center", _ent("Genetec Security Center"))
    assert k in {K.service_or_software, K.equipment_or_product}, k
    assert not is_publishable(k)


def test_p2_high_drops():
    assert classify_site_candidate("site:p2_high", _ent("P2 High")) == K.risk_or_priority


def test_some_mdf_is_generic_phrase():
    assert classify_site_candidate("site:some_mdf", _ent("some MDF")) == K.generic_phrase


def test_each_mdf_is_generic_phrase():
    assert classify_site_candidate("site:each_mdf", _ent("each MDF")) == K.generic_phrase


def test_publishable_for_real_kinds():
    assert is_publishable(K.physical_site)
    assert is_publishable(K.building)
    assert is_publishable(K.address)


def test_room_only_publishable_with_parent():
    assert not is_publishable(K.room_or_closet)
    assert is_publishable(K.room_or_closet, parent_cluster_id="site_cluster::site:banks_high_school")


def test_other_kinds_not_publishable():
    for k in (K.role_or_person, K.equipment_or_product, K.service_or_software,
              K.risk_or_priority, K.generic_phrase, K.organization, K.unknown):
        assert not is_publishable(k), k
