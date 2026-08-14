"""A deal must not be named after the folder it was built in.

Every compile runs in /tmp/ob-core-<rand>/out, so case_dir.name is literally
"out". The skip list covered "_", "tmp", "temp", "ob-" and "audit" — "out"
passed all of them and became a deal's display label on a live brief:

    out: Managed services / NOC / SOC, Structured cabling, ... at ...

A headline that opens with "out:" reads as a broken record, not a deal.
"""
from __future__ import annotations

import pytest

from orbitbrief_core.pm_handoff.fact_quality import display_case_label


@pytest.mark.parametrize("folder", [
    "out", "output", "work", "data", "latest", "artifacts", "run", "build",
    "results", "staging", "input", "OUT", "Output",
])
def test_generic_folder_names_are_never_a_deal_label(folder):
    assert display_case_label("9f2c-uuid", case_dir_name=folder) == "This engagement"


def test_a_numbered_source_file_still_wins():
    out = display_case_label(
        "9f2c-uuid",
        report={"artifacts": [{"filename": "010072-hs-note-123.txt"}]},
        case_dir_name="out",
    )
    assert out == "010072"


def test_an_explicit_case_label_still_wins():
    out = display_case_label("9f2c", sow={"case_label": "000113"}, case_dir_name="out")
    assert out == "000113"


def test_a_real_folder_name_is_still_usable():
    assert display_case_label("9f2c", case_dir_name="Clayton-Homes") == "Clayton-Homes"


def test_temp_folder_names_remain_excluded():
    for f in ("tmp-1234", "ob-core-abc", "audit-run", "_scratch"):
        assert display_case_label("9f2c", case_dir_name=f) == "This engagement"
