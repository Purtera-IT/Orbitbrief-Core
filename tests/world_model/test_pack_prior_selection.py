"""Regression tests for ``PackPrior._select_pack_ids`` and the
richer ``_atom_text_stream`` reader.

These guard PR5: the orchestrator should run brains for the top pack
PLUS any secondary pack with strong absolute, fractional, or boosted
evidence — instead of only honoring the softmax winner.
"""
from __future__ import annotations

from orbitbrief_core.world_model.pack_prior.router import (
    PackPrior,
    _atom_text_stream,
)
from orbitbrief_core.world_model.pack_prior.state import PackScore


def _score(pack_id: str, raw: int, conf: float = 0.0, boosted_hits: int = 0) -> PackScore:
    matched = tuple(f"!kw{i}" for i in range(boosted_hits))
    return PackScore(
        pack_id=pack_id,
        display_name=pack_id,
        raw_score=raw,
        confidence=conf,
        matched_keywords=matched,
    )


def test_select_pack_ids_keeps_top_only_when_only_one_signal():
    selected = PackPrior._select_pack_ids([_score("wireless", 120, 0.8), _score("other", 0)])
    assert selected == ["wireless"]


def test_select_pack_ids_keeps_strong_secondary_by_absolute_score():
    """A pack with raw_score >= 60 always survives even if the top
    has many more hits."""
    selected = PackPrior._select_pack_ids(
        [_score("wireless", 600, 0.95), _score("security_access", 80, 0.05)]
    )
    assert "wireless" in selected
    assert "security_access" in selected


def test_select_pack_ids_keeps_strong_secondary_by_fraction():
    """raw_score >= 20% of the top survives even if it's well below 60."""
    selected = PackPrior._select_pack_ids(
        [_score("wireless", 50, 0.7), _score("security_access", 12, 0.05)]
    )
    assert "wireless" in selected
    assert "security_access" in selected


def test_select_pack_ids_keeps_secondary_with_two_boosted_hits():
    selected = PackPrior._select_pack_ids(
        [
            _score("wireless", 200, 0.9, boosted_hits=4),
            _score("paging_mass_notification", 8, 0.02, boosted_hits=2),
        ]
    )
    assert "paging_mass_notification" in selected


def test_select_pack_ids_caps_at_eight():
    """Cap raised from 4 to 6 + boosted-sweep cap of 8 (post-v3)
    so packs with strong boosted_keyword signal don't get squeezed
    out by a few high-raw-score generic packs."""
    scores = [_score("wireless", 100, 0.5)] + [
        _score(f"p{i}", 60, 0.05) for i in range(10)
    ]
    selected = PackPrior._select_pack_ids(scores)
    # First 6 win on raw_score; no boosted hits in the synthetic
    # fixture so the boosted sweep adds nothing.
    assert len(selected) == 6
    assert selected[0] == "wireless"


def test_select_pack_ids_boosted_sweep_includes_specialized_pack():
    """A pack with raw_score below the cap-6 threshold but >= 2
    boosted-keyword hits gets included via the boosted sweep."""
    scores = [
        _score("wireless", 1000, 0.6),
    ] + [_score(f"generic_{i}", 200, 0.1) for i in range(6)] + [
        _score(
            "paging_mass_notification",
            50,  # well below cap-6 threshold
            0.05,
            boosted_hits=3,
        ),
    ]
    selected = PackPrior._select_pack_ids(scores)
    assert "paging_mass_notification" in selected, selected


def test_atom_text_stream_reads_raw_text_value_entity_keys_and_locator():
    atom = {
        "raw_text": "Install Genetec Synergis",
        "value": {"vendor": "Genetec", "qty": 12},
        "entity_keys": ["vendor:genetec", "site:banks_high_school"],
        "source_refs": [
            {
                "filename": "site_list.xlsx",
                "locator": {"sheet": "Sites", "section_path": ["Access"], "page": 3},
            }
        ],
    }
    stream = _atom_text_stream(atom)
    assert "Install Genetec Synergis" in stream
    assert "Genetec" in stream
    assert "12" in stream
    assert "vendor genetec" in stream
    assert "banks_high_school".replace("_", " ") in stream
    assert "site_list.xlsx" in stream
    assert "Access" in stream
    assert "Sites" in stream


def test_atom_text_stream_handles_missing_fields():
    assert _atom_text_stream({}) == ""
    assert _atom_text_stream({"text": ""}) == ""
