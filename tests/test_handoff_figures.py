"""A runbook should be able to SHOW the picture, not only describe it.

Until now a figure only reached the brief attached to a gap citation, so an
image had to be DISPUTED to be visible. The figures worth putting next to
"mount the bracket as shown" are the ordinary ones the parser read fine.
"""

from __future__ import annotations

from orbitbrief_core.pm_handoff.builder import (
    _MAX_FIGURES,
    _MAX_FIGURE_CAPTION_CHARS,
    _figure_id,
    _figures,
)

PIXELS = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="
OTHER_PIXELS = "data:image/jpeg;base64,/9j/4AAQSkZJRh=="


def figure_atom(atom_id, thumb=PIXELS, region="page0/vector4", text="A sensor interface box."):
    return {
        "id": atom_id,
        "artifact_id": "art-1",
        "text": text,
        "locator": {"page": 1},
        "structured": {
            "fact_kind": "image_description",
            "image_kind": "diagram",
            "region_ref": region,
            "thumb": thumb,
        },
    }


def report_with(atoms, filename="UTM Install Guide.pdf"):
    return {"artifacts": [{"artifact_id": "art-1", "filename": filename, "atoms": atoms}]}


def test_a_described_figure_comes_through_with_its_picture():
    figs = _figures(report_with([figure_atom("atm-1")]), {})
    assert len(figs) == 1
    assert figs[0]["thumb"] == PIXELS
    assert figs[0]["caption"] == "A sensor interface box."
    assert figs[0]["kind"] == "diagram"
    assert figs[0]["filename"] == "UTM Install Guide.pdf"
    assert figs[0]["region_ref"] == "page0/vector4"


def test_a_description_with_no_picture_is_not_a_figure():
    """Nothing to show. A caption on its own is already in the atom text."""
    atom = figure_atom("atm-1")
    atom["structured"].pop("thumb")
    assert _figures(report_with([atom]), {}) == []


def test_a_picture_that_is_not_a_description_is_not_a_figure():
    """Only what parser-os stamped as an image description. Anything else
    carrying pixels has not been read, so there is no caption to pick it by."""
    atom = figure_atom("atm-1")
    atom["structured"]["fact_kind"] = "site_roster"
    assert _figures(report_with([atom]), {}) == []


def test_the_same_picture_twice_is_one_figure():
    """The same diagram lifted from two pages is one figure to a person holding
    the runbook. Identity is the bytes, not the id."""
    figs = _figures(
        report_with([
            figure_atom("atm-1", region="page0/vector4"),
            figure_atom("atm-2", region="page3/vector1"),
        ]),
        {},
    )
    assert len(figs) == 1


def test_different_pictures_are_different_figures():
    figs = _figures(
        report_with([
            figure_atom("atm-1", thumb=PIXELS),
            figure_atom("atm-2", thumb=OTHER_PIXELS, region="page1/image7"),
        ]),
        {},
    )
    assert [f["region_ref"] for f in figs] == ["page0/vector4", "page1/image7"]


def test_a_long_caption_is_trimmed():
    """A caption is what a model picks a figure BY. Past a couple of lines it
    stops being a label and becomes the description the step already holds."""
    atom = figure_atom("atm-1", text="x" * 900)
    figs = _figures(report_with([atom]), {})
    assert len(figs[0]["caption"]) <= _MAX_FIGURE_CAPTION_CHARS


def test_the_list_is_capped():
    """A runbook citing forty pictures is a document nobody carries, and the
    cap matches the renderer's so the brief never offers one it would drop."""
    atoms = [
        figure_atom(f"atm-{i}", thumb=f"data:image/jpeg;base64,AAA{i}", region=f"page{i}/v1")
        for i in range(_MAX_FIGURES + 8)
    ]
    assert len(_figures(report_with(atoms), {})) == _MAX_FIGURES


def test_a_url_never_becomes_a_figure():
    """A payload field that became a URL would turn into a fetch the brief
    performs on content the parser chose."""
    atom = figure_atom("atm-1", thumb="https://example.com/diagram.png")
    assert _figures(report_with([atom]), {}) == []


def test_the_id_says_which_document_and_where():
    """`atm_37c684dd4c708560` is unique and says nothing. A model asked to pick
    a figure by id can do it from the filename and the region."""
    assert _figure_id("UTM Install Guide.pdf", "page0/vector4", "atm-1") == (
        "UTM-Install-Guide.pdf#page0/vector4"
    )
    assert _figure_id("/deals/x/y/Rack Elevations.pdf", "page2/image1", "atm-2") == (
        "Rack-Elevations.pdf#page2/image1"
    )


def test_the_id_falls_back_when_there_is_no_region():
    assert _figure_id("", "", "atm-9") == "atm-9"


def test_a_missing_filename_is_recovered_from_the_artifact_index():
    report = {"artifacts": [{"artifact_id": "art-1", "atoms": [figure_atom("atm-1")]}]}
    figs = _figures(report, {"art-1": {"filename": "Recovered.pdf"}})
    assert figs[0]["filename"] == "Recovered.pdf"


def test_a_report_with_no_artifacts_is_not_an_error():
    assert _figures({}, {}) == []
    assert _figures({"artifacts": None}, {}) == []
    assert _figures({"artifacts": [None, {"atoms": None}]}, {}) == []
