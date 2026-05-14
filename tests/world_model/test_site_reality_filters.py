"""Regression tests for the site-reality server-side hygiene filter.

PR4 adds ``_is_physical_site_candidate`` to drop ``site:*`` entities
whose evidence blob is dominated by product / framework / SaaS terms.
"""
from __future__ import annotations

from orbitbrief_core.world_model.site_reality.cluster import (
    _entity_evidence_blob,
    _is_physical_site_candidate,
)


def _envelope_with_atoms(site_key: str, atom_texts: list[str]) -> dict:
    atoms = []
    by_key: dict[str, list[str]] = {site_key: []}
    for i, text in enumerate(atom_texts):
        atom_id = f"atm_{i}"
        atoms.append({"id": atom_id, "raw_text": text, "normalized_text": text.lower()})
        by_key[site_key].append(atom_id)
    return {
        "atoms": atoms,
        "indexes": {"atoms_by_entity_key": by_key},
    }


def test_real_school_site_survives():
    site_key = "site:banks_high_school"
    ent = {"canonical_key": site_key, "canonical_name": "Banks High School"}
    env = _envelope_with_atoms(
        site_key,
        [
            "Banks High School / District Core at 13050 NW Main St",
            "After-hours MDF access required for AP refresh",
        ],
    )
    assert _is_physical_site_candidate(site_key, ent, env) is True


def test_belden_cat6_does_not_become_site():
    site_key = "site:belden_cat6_cmp"
    ent = {"canonical_key": site_key, "canonical_name": "Belden Cat6 CMP"}
    env = _envelope_with_atoms(
        site_key,
        ["Quote includes 186 Belden Cat6 CMP drops with RJ45 termination."],
    )
    assert _is_physical_site_candidate(site_key, ent, env) is False


def test_cisa_vulnerability_playbook_does_not_become_site():
    site_key = "site:cisa_vulnerability_playbook"
    ent = {"canonical_key": site_key, "canonical_name": "CISA Vulnerability Playbook"}
    env = _envelope_with_atoms(
        site_key,
        ["Operations follow CISA vulnerability playbook for incident triage."],
    )
    assert _is_physical_site_candidate(site_key, ent, env) is False


def test_servicenow_does_not_become_site():
    site_key = "site:servicenow"
    ent = {"canonical_key": site_key, "canonical_name": "ServiceNow"}
    env = _envelope_with_atoms(
        site_key, ["Tickets logged in ServiceNow with PagerDuty alert routing."]
    )
    assert _is_physical_site_candidate(site_key, ent, env) is False


def test_genetec_synergis_does_not_become_site():
    site_key = "site:genetec_synergis"
    ent = {"canonical_key": site_key, "canonical_name": "Genetec Synergis"}
    env = _envelope_with_atoms(
        site_key, ["Install Genetec Synergis door controller with HID readers."]
    )
    assert _is_physical_site_candidate(site_key, ent, env) is False


def test_real_address_survives_even_with_some_product_words():
    """A real address with both site-positive and a few negative
    terms still survives because the positive words are present."""
    site_key = "site:13050_nw_main_st"
    ent = {"canonical_key": site_key, "canonical_name": "13050 NW Main St Building"}
    env = _envelope_with_atoms(
        site_key,
        [
            "Building at 13050 NW Main St requires a Cisco Meraki AP refresh in MDF closet.",
        ],
    )
    assert _is_physical_site_candidate(site_key, ent, env) is True


def test_evidence_blob_pulls_atom_text():
    site_key = "site:foo"
    ent = {"canonical_key": site_key, "canonical_name": "Foo"}
    env = _envelope_with_atoms(site_key, ["bar baz"])
    blob = _entity_evidence_blob(site_key, ent, env)
    assert "Foo" in blob
    assert "bar baz" in blob
