"""The inspection report's atom rows carry the document outline.

pm_handoff builds the field procedure from those rows, grouped by the heading
each note sits under. The rows kept the locator but not section_path, and the
backfill from the envelope only adds atoms the report did not already list --
so a document of 60 atoms or fewer (deal 000043's OnSite Inventory Runbook has
58) reached the handoff with no heading on any note.
"""

from __future__ import annotations

from orbitbrief_core.orchestrator.inspection import _artifact_view
from orbitbrief_core.pm_handoff.builder import _implementation_notes, _untruncate_report_atoms

ECOBEE = "Connecting ecobee thermostats to 'HC-Other' SSID"


def _view(envelope):
    doc = envelope["documents"][0]
    ids = [a["id"] for a in envelope["atoms"] if a["artifact_id"] == doc["artifact_id"]]
    return _artifact_view(
        doc=doc, atom_ids=ids, envelope=envelope, atom_packets={},
        bundled_packet_ids=set(), brain_cited_atoms=set(), composed_packet_ids=set(),
    )


def _envelope():
    return {
        "documents": [{"artifact_id": "art-rb", "filename": "OnSite Inventory Runbook.docx"}],
        "atoms": [
            {"id": "a1", "artifact_id": "art-rb", "atom_type": "site_implementation_note",
             "text": "Touch the main menu icon.", "section_path": [ECOBEE],
             "locator": {"paragraph_index": 1}},
            {"id": "a2", "artifact_id": "art-rb", "atom_type": "site_implementation_note",
             "text": "The thermostat can take up to 90 seconds to connect.",
             "section_path": [ECOBEE, "Depending on your device model"],
             "locator": {"paragraph_index": 2}},
        ],
    }


def test_the_row_carries_section_path():
    rows = _view(_envelope())["atoms"]
    assert rows[0]["section_path"] == [ECOBEE]
    assert rows[1]["section_path"] == [ECOBEE, "Depending on your device model"]


def test_a_short_document_reaches_the_procedure_list_through_the_real_rows():
    """The live failure: every atom is already listed, the backfill adds
    nothing, and the heading lives only at the top level."""
    envelope = _envelope()
    report = {"artifacts": [_view(envelope)]}
    report = _untruncate_report_atoms(report, envelope)
    groups = _implementation_notes(report)
    assert [g["procedure"] for g in groups] == [ECOBEE]
    assert len(groups[0]["notes"]) == 2


def test_the_report_rows_carry_the_parsers_review_flags():
    """pm_handoff takes a line the parser flagged for review into its heading's
    procedure. A row without the flags makes that rule silently never fire."""
    envelope = _envelope()
    envelope["atoms"].append(
        {"id": "a3", "artifact_id": "art-rb", "atom_type": "scope_item", "text": "Device type",
         "section_path": [ECOBEE], "review_flags": ["low_confidence_needs_review"], "locator": {"paragraph_index": 3}}
    )
    rows = {r["id"]: r for r in _view(envelope)["atoms"]}
    assert rows["a3"]["review_flags"] == ["low_confidence_needs_review"]
    assert rows["a1"]["review_flags"] == []

    report = {"artifacts": [{"artifact_id": "art-rb", "filename": "OnSite Inventory Runbook.docx", "atoms": []}]}
    backfilled = {r["id"]: r for r in _untruncate_report_atoms(report, envelope)["artifacts"][0]["atoms"]}
    assert backfilled["a3"]["review_flags"] == ["low_confidence_needs_review"]

