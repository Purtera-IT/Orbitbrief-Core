"""The procedure a technician follows has to reach the brief.

``site_implementation_note`` atoms already routed to the "sites" fact
category, where twelve slots are shared with the whole of site planning. On
deal 000043 that meant 209 of them competed with 439 site rows and every one
lost: `ecobee` appears 45 times in the envelope and 0 times in the brief,
`thermostat` 60 and 0, "90 seconds to connect" 3 and 0.

Invisible while the brief's only readers were commercial. Disqualifying the
moment one of them became the runbook generator, which is asked to write a
field procedure from a brief that contains no field procedure.
"""

from __future__ import annotations

from orbitbrief_core.pm_handoff.builder import (
    _MAX_NOTE_CHARS,
    _MAX_NOTES_PER_PROCEDURE,
    _MAX_PROCEDURES,
    _implementation_notes,
    _is_lead_in,
    _note_medium,
    _procedure_name,
)


def note(text, procedure="Connecting Smart TVs to 'HC-Other' SSID", **locator):
    return {
        "id": f"atm-{abs(hash(text)) % 10**8}",
        "atom_type": "site_implementation_note",
        "text": text,
        "section_path": [procedure] if procedure else [],
        "locator": locator,
    }


def report(atoms, filename="Clayton OnSite Inventory Runbook.docx"):
    return {"artifacts": [{"artifact_id": "art-1", "filename": filename, "atoms": atoms}]}


def test_a_procedure_comes_through_grouped_by_its_own_heading():
    """The grouping is the author's, not one we imposed -- parser-os already
    records the document outline on every atom."""
    groups = _implementation_notes(
        report([
            note("On the Samsung TV remote, press the Home button.", paragraph_index=1),
            note("Select the Network option.", paragraph_index=2),
        ])
    )
    assert len(groups) == 1
    assert groups[0]["procedure"] == "Connecting Smart TVs to 'HC-Other' SSID"
    assert groups[0]["source"] == "Clayton OnSite Inventory Runbook.docx"
    assert [n["text"] for n in groups[0]["notes"]] == [
        "On the Samsung TV remote, press the Home button.",
        "Select the Network option.",
    ]


def test_steps_are_put_back_in_document_order():
    """Envelope order is not document order. The real Samsung procedure arrives
    with "select Open Network Settings" BEFORE "press the Home button", and
    steps in the wrong order are worse than no steps."""
    groups = _implementation_notes(
        report([
            note("On the Connections menu, select Open Network Settings.", paragraph_index=7),
            note("On the Samsung TV remote, press the Home button.", paragraph_index=4),
            note("Navigate to Settings.", paragraph_index=5),
        ])
    )
    assert [n["text"][:20] for n in groups[0]["notes"]] == [
        "On the Samsung TV re",
        "Navigate to Settings",
        "On the Connections m",
    ]


def test_a_note_with_no_ordinal_sorts_last_not_into_the_middle():
    groups = _implementation_notes(
        report([
            note("Unplaceable.", ),
            note("First.", paragraph_index=1),
            note("Second.", paragraph_index=2),
        ])
    )
    assert [n["text"] for n in groups[0]["notes"]] == ["First.", "Second.", "Unplaceable."]


def test_page_beats_paragraph_index():
    groups = _implementation_notes(
        report([
            note("Page two, first block.", page=2, block_index=1),
            note("Page one, later block.", page=1, block_index=9),
        ])
    )
    assert groups[0]["notes"][0]["text"] == "Page one, later block."


def test_a_note_with_no_heading_is_dropped():
    """A step with no procedure is a sentence a technician cannot place. On
    deal 000043 that is 63 of 209 notes -- contract boilerplate, not steps."""
    assert _implementation_notes(report([note("Supplier shall comply.", procedure="")])) == []


def test_a_paragraph_lead_in_is_not_a_heading():
    """A document with no outline gives parser-os a lead-in to record, and it
    arrives looking exactly like a heading. A real heading is ABOUT its notes;
    a lead-in IS one."""
    text = "These devices require a password to connect, which will be provided by the Service Desk."
    assert _is_lead_in("These devices require a password to connect, which will be", text)
    assert not _is_lead_in("Connecting iPads to 'HC-Other' SSID", text)
    assert _implementation_notes(
        report([note(text, procedure="These devices require a password to connect, which will be")])
    ) == []


def test_a_sentence_is_too_long_to_be_a_heading():
    long_heading = "All personal devices including BYOD laptops and mobile phones may only connect to Guest"
    assert len(long_heading) > 80
    assert _implementation_notes(report([note("Connect it.", procedure=long_heading)])) == []


def test_the_medium_is_read_from_the_locator_not_the_file_extension():
    """All three arrive typed site_implementation_note, and only one is a
    procedure."""
    assert _note_medium({"paragraph_index": 4}) == "prose"
    assert _note_medium({"sheet": "Territory_Needs", "row": 12}) == "table"
    assert _note_medium({"speaker": "Gillison, Jeff", "utterance_index": 88}) == "discussion"


def test_a_spreadsheet_tab_is_not_a_procedure():
    """Its tab name is not a heading and its rows are records. Thirty rows of a
    territory-planning tab are not thirty steps."""
    groups = _implementation_notes(
        report(
            [note(f"Market {i} needs 3 techs.", procedure="Territory_Needs", sheet="Territory_Needs", row=i)
             for i in range(4)],
            filename="Clayton_Dispatch_Readiness.xlsx",
        )
    )
    assert groups[0]["kind"] == "table"


def test_a_transcript_speaker_is_not_a_procedure():
    """Its "heading" is whoever was speaking, which is why "Gillison, Jeff"
    turns up looking like one."""
    groups = _implementation_notes(
        report(
            [note("We should start with the pilot.", procedure="Gillison, Jeff",
                  speaker="Gillison, Jeff", utterance_index=i) for i in range(3)],
            filename="Kickoff call.txt",
        )
    )
    assert groups[0]["kind"] == "discussion"


def test_a_real_procedure_outranks_a_tab_for_the_cap():
    """The failure this ordering prevents: the smart-TV procedure falling off
    the end so a territory-planning tab can be in the brief instead."""
    atoms = []
    for i in range(_MAX_PROCEDURES + 4):
        atoms += [note(f"Row {i}.{j}", procedure=f"Tab_{i}", sheet=f"Tab_{i}", row=j) for j in range(3)]
    atoms += [note("Press the Home button.", paragraph_index=1)]
    groups = _implementation_notes(report(atoms))
    assert len(groups) == _MAX_PROCEDURES
    assert groups[0]["procedure"] == "Connecting Smart TVs to 'HC-Other' SSID"
    assert groups[0]["kind"] == "prose"


def test_the_same_instruction_twice_is_one_step():
    groups = _implementation_notes(
        report([
            note("Enter the wi-fi password provided to you.", paragraph_index=3),
            note("Enter the wi-fi password provided to you.", paragraph_index=9),
        ])
    )
    assert len(groups[0]["notes"]) == 1


def test_a_procedure_is_capped():
    groups = _implementation_notes(
        report([note(f"Step {i}.", paragraph_index=i) for i in range(_MAX_NOTES_PER_PROCEDURE + 15)])
    )
    assert len(groups[0]["notes"]) == _MAX_NOTES_PER_PROCEDURE


def test_the_last_heading_is_the_specific_one():
    """A note under ['Services Proposal', 'Project Scope', 'Customer
    Responsibilities'] is about customer responsibilities; the first element
    only says which document."""
    assert _procedure_name(
        {"section_path": ["Services Proposal", "Project Scope", "Customer Responsibilities"]}
    ) == "Customer Responsibilities"


def test_a_stringified_section_path_is_parsed_back():
    """Some envelopes stringify the list, and "['A', 'B']" is not a heading."""
    assert _procedure_name({"section_path": "['1.1 PURPOSE', 'Per-site instructions']"}) == (
        "Per-site instructions"
    )
    assert _procedure_name({"section_path": "Device Information Required"}) == (
        "Device Information Required"
    )
    assert _procedure_name({"section_path": None}) == ""


def test_each_note_keeps_a_pointer_back_to_the_document():
    """A step a PM cannot trace is a step they cannot check."""
    groups = _implementation_notes(report([note("Press the Home button.", page=7, paragraph_index=2)]))
    n = groups[0]["notes"][0]
    assert n["filename"] == "Clayton OnSite Inventory Runbook.docx"
    assert n["atom_id"]
    assert "7" in n["locator"]


def test_a_report_with_nothing_in_it_is_not_an_error():
    assert _implementation_notes({}) == []
    assert _implementation_notes({"artifacts": None}) == []
    assert _implementation_notes({"artifacts": [None, {"atoms": None}]}) == []
    assert _implementation_notes(report([{"atom_type": "scope_item", "text": "x"}])) == []


def test_a_sentence_heading_steps_over_to_its_parent_instead_of_losing_the_note():
    """The first version dropped the note. It lost "On iPad go to Settings > tap
    General > then tap About" because its heading was an 86-character sentence
    -- while a perfectly good heading sat right above it."""
    atom = {
        "id": "atm-ipad",
        "atom_type": "site_implementation_note",
        "text": "On iPad go to Settings > tap General > then tap About.",
        "section_path": [
            "Obtaining Information from iPads",
            "For the iPad, you can view the information from the device by following the steps below",
        ],
        "locator": {"paragraph_index": 3},
    }
    groups = _implementation_notes(report([atom]))
    assert [g["procedure"] for g in groups] == ["Obtaining Information from iPads"]


def test_a_branch_is_folded_into_its_procedure_in_document_order():
    """The notes a technician most needs on deal 000043 -- radio Enabled, the
    network, the 90-second wait -- sat under "Depending on your device model".
    As their own group they named no device, and a runbook cited none of them."""
    ecobee = "Connecting ecobee thermostats to 'HC-Other' SSID"

    def at(text, path, i):
        return {"id": f"a{i}", "atom_type": "site_implementation_note", "text": text,
                "section_path": path, "locator": {"paragraph_index": i}}

    groups = _implementation_notes(report([
        at("Touch the main menu icon.", [ecobee], 1),
        at("Set Wi-Fi radio to Enabled.", [ecobee, "Depending on your device model"], 3),
        at("The thermostat can take up to 90 seconds to connect.", [ecobee, "Depending on your device model"], 4),
        at("Now you will see a list of menus.", [ecobee], 2),
    ]))
    assert len(groups) == 1
    assert groups[0]["procedure"] == ecobee
    assert [n["text"][:12] for n in groups[0]["notes"]] == [
        "Touch the ma", "Now you will", "Set Wi-Fi ra", "The thermost",
    ]


def test_a_chapter_does_not_swallow_its_procedures():
    """A title with several procedures under it is a chapter. Folding children
    into it would turn the whole runbook into one procedure named after the
    document."""
    title = "Retail Network Segmentation"

    def at(text, path, i):
        return {"id": f"c{i}", "atom_type": "site_implementation_note", "text": text,
                "section_path": path, "locator": {"paragraph_index": i}}

    groups = _implementation_notes(report([
        at("This guide covers device inventory.", [title], 0),
        at("Press Home.", [title, "Connecting Smart TVs"], 1),
        at("Open Settings.", [title, "Connecting iPads"], 2),
        at("Touch the menu icon.", [title, "Connecting ecobee thermostats"], 3),
    ]))
    assert sorted(g["procedure"] for g in groups) == sorted(
        [title, "Connecting Smart TVs", "Connecting iPads", "Connecting ecobee thermostats"]
    )


# --- the live pipeline --------------------------------------------------------
#
# Every test above built `report` straight from atoms that carry section_path at
# the top level. The live pipeline does not: _untruncate_report_atoms backfills
# envelope atoms into the report, and it copied every field except
# section_path. Deal 000043's first brief on this code shipped
# `implementation_notes: []`. These go through that path.

from orbitbrief_core.pm_handoff.builder import _untruncate_report_atoms


def _envelope_note(atom_id, text, path, i, *, in_locator_only=False):
    atom = {
        "id": atom_id,
        "artifact_id": "art-rb",
        "atom_type": "site_implementation_note",
        "text": text,
        "locator": {"paragraph_index": i, "section_path": list(path)},
    }
    if not in_locator_only:
        atom["section_path"] = list(path)
    return atom


def test_a_note_backfilled_from_the_envelope_keeps_its_heading():
    ecobee = "Connecting ecobee thermostats to 'HC-Other' SSID"
    envelope = {"atoms": [
        _envelope_note("n1", "Touch the main menu icon.", [ecobee], 1),
        _envelope_note("n2", "The thermostat can take up to 90 seconds to connect.",
                       [ecobee, "Depending on your device model"], 2),
    ]}
    # The report knows the artifact but, as in the live pipeline, not these atoms.
    report = {"artifacts": [{"artifact_id": "art-rb", "filename": "OnSite Runbook.docx", "atoms": []}]}
    report = _untruncate_report_atoms(report, envelope)

    backfilled = report["artifacts"][0]["atoms"]
    assert all(row.get("section_path") for row in backfilled), "backfill dropped the outline"

    groups = _implementation_notes(report)
    assert [g["procedure"] for g in groups] == [ecobee]
    assert "90 seconds" in " ".join(n["text"] for n in groups[0]["notes"])


def test_a_heading_only_on_the_locator_still_places_the_note():
    """A row that lost its top-level section_path still has the one parser-os
    stamped on the locator -- and on deal 000043 that is 126 of the 140 notes
    that have a heading at all."""
    atom = _envelope_note("n3", "Select HC-Other.", ["Connecting iPads to 'HC-Other' SSID"], 1, in_locator_only=True)
    assert "section_path" not in atom
    groups = _implementation_notes({"artifacts": [{"artifact_id": "art-rb", "filename": "r.docx", "atoms": [atom]}]})
    assert [g["procedure"] for g in groups] == ["Connecting iPads to 'HC-Other' SSID"]


def test_an_empty_top_level_path_falls_through_to_the_locator():
    atom = _envelope_note("n4", "Press Home.", ["Connecting Smart TVs"], 1)
    atom["section_path"] = []
    groups = _implementation_notes({"artifacts": [{"artifact_id": "art-rb", "filename": "r.docx", "atoms": [atom]}]})
    assert [g["procedure"] for g in groups] == ["Connecting Smart TVs"]


# The workstation note on deal 000043, in full (479 characters).
WORKSTATIONS = (
    "For all workstations, please provide make and model. As shown below, this can be found by going to "
    "your ‘Settings’, then ‘System’, and then ‘About’ (ex: Dell Latitude 5540). We would also require the "
    "service tag/serial number (these are typically listed on a sticker under the laptop (as shown below), "
    "ex: ST = G92KFY3). The computers are the only devices that will be automatically connected to their "
    "new networks by our Engineers, all others will need to be manually connected."
)


def _only_note(text):
    groups = _implementation_notes(report([note(text, procedure="Obtaining Information from Workstations", paragraph_index=1)]))
    return groups[0]["notes"][0]["text"]


def test_a_note_under_the_cap_arrives_whole():
    """Cut at 400 characters it ended "automatically connected to the…", and the
    runbook could not say which devices the technician has to connect."""
    assert _only_note(WORKSTATIONS) == WORKSTATIONS


def test_a_long_note_is_cut_at_its_last_whole_sentence():
    text = " ".join(f"Sentence {i} says one thing a technician does at the site." for i in range(40))
    out = _only_note(text)
    assert len(out) <= _MAX_NOTE_CHARS
    assert out.endswith("at the site.")
    assert "…" not in out


def test_one_sentence_past_the_cap_is_cut_at_a_word_and_marked():
    text = "word " * 400
    out = _only_note(text)
    assert len(out) <= _MAX_NOTE_CHARS
    assert out.endswith("word…")


# --- a line the parser doubted stays with its siblings -------------------------

INVENTORY = "Inventory & Data Capture Requirements"


def doubted(text, atom_type="scope_item", flags=("prose_fallback_capture", "low_confidence_needs_review"), procedure=INVENTORY, **locator):
    return {
        "id": f"atm-{abs(hash(text + atom_type)) % 10**8}",
        "atom_type": atom_type,
        "text": text,
        "section_path": ["Services Proposal", "Project Scope", procedure] if procedure else [],
        "review_flags": list(flags),
        "locator": locator,
    }


def _inventory_note(**locator):
    atom = note("Asset tag (if available)", procedure=INVENTORY, **locator)
    atom["section_path"] = ["Services Proposal", "Project Scope", INVENTORY]
    return atom


def test_a_line_the_parser_doubted_joins_the_procedure_its_heading_holds():
    """Deal 000043's SOW, second parse: one field note and three scope items the
    parser flagged for review. The three had fallen out of the procedure."""
    groups = _implementation_notes(
        report([
            doubted("Operating system", paragraph_index=24),
            _inventory_note(paragraph_index=21),
            doubted("Computer name", paragraph_index=22),
            doubted("Device type", paragraph_index=23),
        ], filename="Services Proposal.docx")
    )
    assert len(groups) == 1
    assert groups[0]["procedure"] == INVENTORY
    assert [n["text"] for n in groups[0]["notes"]] == ["Asset tag (if available)", "Computer name", "Device type", "Operating system"]


def test_a_line_labelled_with_confidence_stays_out():
    groups = _implementation_notes(
        report([_inventory_note(paragraph_index=21), doubted("Net 30 payment terms", atom_type="payment_term", flags=(), paragraph_index=22)])
    )
    assert [n["text"] for n in groups[0]["notes"]] == ["Asset tag (if available)"]


def test_a_doubted_line_does_not_make_a_procedure_of_its_own():
    assert _implementation_notes(report([doubted("Device type", paragraph_index=23)])) == []


def test_a_doubted_transcript_line_stays_out_of_the_procedure():
    groups = _implementation_notes(
        report([
            _inventory_note(paragraph_index=21),
            doubted("Is the SSID update going to happen same day?", atom_type="open_question", speaker="Chris Harp", utterance_index=4),
        ])
    )
    assert [n["text"] for n in groups[0]["notes"]] == ["Asset tag (if available)"]


def test_a_chapter_is_a_chapter_by_its_outline_not_by_which_headings_hold_field_notes():
    """Clayton's second parse: under "Project Scope", only two child headings held
    field notes; the other two held lines of other labels. Counted from field
    notes alone, "Project Scope" read as a procedure and swallowed its children."""
    def line(text, child, atom_type="site_implementation_note", **locator):
        atom = note(text, procedure=child, **locator)
        atom["atom_type"] = atom_type
        atom["section_path"] = ["Services Proposal", "Project Scope"] + ([child] if child else [])
        return atom

    groups = _implementation_notes(
        report([
            line("Provider will execute standardized activities at each site.", None, paragraph_index=10),
            line("Asset tag (if available)", "Inventory & Data Capture Requirements", paragraph_index=21),
            line("Sites not open will be scheduled later.", "Site Deployment & Execution Model", paragraph_index=14),
            line("This quote is valid for thirty days.", "Project Assumptions", atom_type="contract_term", paragraph_index=30),
            line("Stored in centralized repository", "Reporting Requirements", atom_type="scope_item", paragraph_index=35),
        ])
    )
    assert sorted(g["procedure"] for g in groups) == ["Inventory & Data Capture Requirements", "Project Scope", "Site Deployment & Execution Model"]

