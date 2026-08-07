"""The site panel must read the canonical roster, not rebuild it.

`envelope.py` resolves every site once into `site_readiness` — name, address,
readiness score. The panel used to re-derive its own list from `site_reality`
clusters, so a 437-site Clayton rollout rendered as **3 entries named "hc 1023"**
while `site_readiness` sat beside it in the same document with all 437 populated.

Same duplicated-consumer bug f257ba4 removed seven of. Read the roster.
"""

from orbitbrief_core.pm_handoff.builder import _build_site_summaries


def _roster(n: int) -> list[dict]:
    return [
        {
            "site_slug": f"site:hc_{100 + i}",
            "name": f"Clayton Homes of Town {i}",
            "address": f"{i} Main St",
            "readiness_score": 0.2,
            "band": "amber",
            "atom_count": 3,
        }
        for i in range(n)
    ]


def test_panel_matches_the_roster_exactly():
    sites = _build_site_summaries({"site_readiness": _roster(437)})
    assert len(sites) == 437


def test_roster_wins_over_cluster_derivation():
    """The clusterer's 3 must not override the roster's 437."""
    report = {
        "site_readiness": _roster(437),
        "site_reality": {
            "clusters": [
                {"canonical_name": "hc 1023", "member_atom_ids": list("abcd"), "artifact_ids": list("xyz")}
            ]
        },
    }
    sites = _build_site_summaries(report)
    assert len(sites) == 437
    assert not any(s.name == "hc 1023" for s in sites)


def test_real_names_survive():
    sites = _build_site_summaries({"site_readiness": _roster(5)})
    assert all(s.name.startswith("Clayton Homes of Town") for s in sites)


def test_row_without_a_name_falls_back_to_its_slug():
    """A nameless roster row is still a real site — do not drop it."""
    sites = _build_site_summaries(
        {"site_readiness": [{"site_slug": "site:hc_900", "atom_count": 1}]}
    )
    assert len(sites) == 1
    assert "hc 900" in sites[0].name


def test_duplicate_slugs_collapse():
    rows = _roster(3) + _roster(3)
    assert len(_build_site_summaries({"site_readiness": rows})) == 3


def test_falls_back_to_clusters_when_no_roster():
    """Briefs built before site_readiness existed must still render."""
    report = {
        "atoms": [],
        "site_reality": {
            "clusters": [
                {
                    "canonical_name": "Duracraft Solutions",
                    "member_atom_ids": list("abcdef"),
                    "artifact_ids": list("xyz"),
                }
            ]
        },
    }
    assert isinstance(_build_site_summaries(report), list)
