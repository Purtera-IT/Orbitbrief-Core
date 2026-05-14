"""Smoke tests for tools/orbitbrief_regression_gate.py."""
from __future__ import annotations

import json
import sys
from pathlib import Path


# Make tools/ importable for the test runner.
_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "tools"))

import orbitbrief_regression_gate as gate  # noqa: E402


def test_passes_on_clean_results(tmp_path: Path):
    case = tmp_path / "CASE_OK"
    case.mkdir()
    (case / "site_reality.json").write_text(
        json.dumps({"clusters": [{"canonical_name": "Banks High School"}]}),
        encoding="utf-8",
    )
    (case / "pack_prior.json").write_text(
        json.dumps({"top_pack_id": "wireless", "selected_pack_ids": ["wireless"]}),
        encoding="utf-8",
    )
    failures = gate.check_orbit_results(tmp_path)
    assert failures == []


def test_fails_on_fake_site_cluster(tmp_path: Path):
    case = tmp_path / "CASE_BAD_SITE"
    case.mkdir()
    (case / "site_reality.json").write_text(
        json.dumps({"clusters": [{"canonical_name": "Belden Cat6 CMP"}]}),
        encoding="utf-8",
    )
    failures = gate.check_orbit_results(tmp_path)
    assert any("fake site cluster" in f for f in failures)


def test_fails_on_pure_other_routing(tmp_path: Path):
    case = tmp_path / "CASE_OTHER"
    case.mkdir()
    (case / "pack_prior.json").write_text(
        json.dumps({"top_pack_id": "other", "selected_pack_ids": []}),
        encoding="utf-8",
    )
    failures = gate.check_orbit_results(tmp_path)
    assert any("routed only to other" in f for f in failures)


def test_passes_when_other_has_secondaries(tmp_path: Path):
    case = tmp_path / "CASE_MIXED"
    case.mkdir()
    (case / "pack_prior.json").write_text(
        json.dumps(
            {"top_pack_id": "other", "selected_pack_ids": ["other", "wireless"]}
        ),
        encoding="utf-8",
    )
    failures = gate.check_orbit_results(tmp_path)
    assert failures == []
