"""A rollout must not be mistaken for address-line noise.

Live case: a 426-dealership Clayton Homes rollout shipped as **3 sites named
"hc 1023"**. parser-os had resolved all 437 physical_site atoms correctly, each
with a site_id and a facility name. Three separate bugs in this module threw
that away:

1. the micro-cluster guard dropped every cluster of <=2 atoms — which is every
   site in a rollout, where each dealership appears in one or two documents;
2. the structured-atom merge that would have recovered them was gated on
   ``if not out``, and clustering had left 3 survivors, so it never ran;
3. cluster names came from ``canonical_name``, which normalises "HC-1023" to
   "hc 1023" and drops the facility name the atom already carried.
"""

from orbitbrief_core.pm_handoff.builder import (
    _ROLLOUT_SITE_FLOOR,
    _build_site_summaries,
    _prefer_structured_site_name,
    _slugs_compatible,
)
from orbitbrief_core.pm_handoff.models import SiteSummary


def _site_atom(site_id: str, name: str, city: str = "Maryville", state: str = "TN") -> dict:
    return {
        "id": f"atm_{site_id.lower().replace('-', '')}",
        "atom_type": "physical_site",
        "confidence": 0.85,
        "entity_keys": [f"site:{name.lower().replace(' ', '_')}"],
        "value": {
            "kind": "physical_site",
            "id": site_id,
            "site_id": site_id,
            "name": name,
            "facility_name": name,
            "city": city,
            "state": state,
        },
    }


def _rollout(n: int) -> list[dict]:
    return [_site_atom(f"HC-{100 + i}", f"Clayton Homes of Town {i}") for i in range(n)]


def test_rollout_sites_survive_the_micro_cluster_guard():
    """Each site appears once — the exact shape the guard was written to drop."""
    atoms = _rollout(40)
    sites = _build_site_summaries({"atoms": atoms})
    assert len(sites) >= 40, f"rollout collapsed to {len(sites)} sites"


def test_structured_sites_merge_even_when_clustering_kept_some():
    """The recovery must not be gated on an empty result — 3 survivors is truthy."""
    atoms = _rollout(30)
    report = {
        "atoms": atoms,
        "site_reality": {
            "clusters": [
                {
                    "canonical_name": "hc 1023",
                    "member_atom_ids": ["a", "b", "c", "d"],
                    "artifact_ids": ["x", "y", "z"],
                }
            ]
        },
    }
    sites = _build_site_summaries(report)
    # Without the ungating this returns ~1 site; the 30 structured ones are lost.
    assert len(sites) >= 30, f"only {len(sites)} sites — structured merge did not run"


def test_bare_site_code_is_replaced_by_the_resolved_facility_name():
    structured = {"hc_1023": SiteSummary(name="Clayton Homes of Moncks Corner", kind="physical_site", publishable=True)}
    assert _prefer_structured_site_name("hc 1023", structured) == "Clayton Homes of Moncks Corner"
    assert _prefer_structured_site_name("HC-1023", structured) == "Clayton Homes of Moncks Corner"


def test_a_real_name_is_never_overwritten():
    structured = {"hc_1023": SiteSummary(name="Clayton Homes of Moncks Corner", kind="physical_site", publishable=True)}
    assert _prefer_structured_site_name("Duracraft Solutions", structured) == "Duracraft Solutions"


def test_code_with_no_resolved_name_is_left_alone():
    """Nothing to recover is not a licence to invent one."""
    assert _prefer_structured_site_name("hc 9999", {}) == "hc 9999"


def test_small_deal_still_drops_address_line_noise():
    """The guard must keep working below the rollout floor."""
    assert _ROLLOUT_SITE_FLOOR > 3
    report = {
        "atoms": [],
        "site_reality": {
            "clusters": [
                {"canonical_name": "Building C", "member_atom_ids": ["a"], "artifact_ids": ["x"]}
            ]
        },
    }
    assert _build_site_summaries(report) == []


def test_slug_containment_does_not_double_count_one_site():
    assert _slugs_compatible("clayton_homes_of_marion", "clayton_homes_of_marion_sc")
    assert not _slugs_compatible("clayton_homes_of_marion", "duracraft_solutions")
    assert not _slugs_compatible("", "clayton_homes_of_marion")


def test_slug_containment_respects_token_boundaries():
    """"..._town_1" must not swallow "..._town_10"; that under-counts rollouts."""
    assert not _slugs_compatible("clayton_homes_of_town_1", "clayton_homes_of_town_10")
    assert not _slugs_compatible("hc_1", "hc_10")
    assert _slugs_compatible("hc_1", "hc_1")
