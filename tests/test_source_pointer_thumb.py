"""Evidence that came out of a figure should be able to show the figure.

parser-os stamps an inline JPEG on a description atom for an image it could
read. Without carrying it here, the brief shows a claim about a picture with no
picture -- something a person cannot check, and a question about a component
that cannot be answered next to the component.
"""

from __future__ import annotations

from orbitbrief_core.pm_handoff.builder import _atom_thumb
from orbitbrief_core.pm_handoff.models import SourcePointer

PIXELS = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="


def test_a_figure_atom_carries_its_picture():
    assert _atom_thumb({"structured": {"thumb": PIXELS}}) == PIXELS


def test_a_text_atom_carries_nothing():
    assert _atom_thumb({"structured": {"region_ref": "page0/vector5"}}) == ""


def test_an_atom_with_no_structured_block_carries_nothing():
    assert _atom_thumb({}) == ""
    assert _atom_thumb({"structured": None}) == ""


def test_a_url_is_refused():
    """A payload field that became a URL would turn into a fetch the brief
    performs on content the parser chose."""
    assert _atom_thumb({"structured": {"thumb": "https://example.com/x.png"}}) == ""


def test_a_non_string_is_refused():
    assert _atom_thumb({"structured": {"thumb": 42}}) == ""


def test_the_pointer_defaults_to_no_picture():
    p = SourcePointer(filename="guide.pdf", locator="Page 1")
    assert p.thumb == ""
    assert p.display() == "guide.pdf — Page 1"
