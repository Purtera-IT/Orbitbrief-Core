from orbitbrief_core.pm_handoff import c3_brief as c

ENV = {
    "atoms": [{"id": "atm_a", "artifact_id": "art_1", "text": "Can you confirm the camera count?",
               "locator": {"kind": "email_body"}}],
    "documents": [{"artifact_id": "art_1", "filename": "deal.eml"}],
    "c3_brief": {"version": 2, "service": {"value": "security_camera"},
                 "written": {"summary": "Install three cameras [atm_a].",
                             "sections": {"scope": [{"text": "Mount cameras [atm_a].", "cites": ["atm_a"]}]},
                             "open_questions": [{"question": "Can you confirm the camera count?",
                                                 "owner": "project_manager", "cites": ["[atm_a]"]}],
                             "catalog_questions": [
                                 {"id": "q:low", "question": "Low?", "family": "x", "p": 0.4, "cites": []},
                                 {"id": "q:coi", "question": "What COI limits apply?",
                                  "family": "commercial_terms", "p": 0.9, "cites": ["atm_a"]}],
                             "answered_in_deal": [{"id": "q:pay", "answered_by": ["atm_a"]}]}},
}


def test_off_unless_switched(monkeypatch):
    monkeypatch.delenv("ORBITBRIEF_C3_BRIEF", raising=False)
    assert not c.enabled()
    monkeypatch.setenv("ORBITBRIEF_C3_BRIEF", "on")
    assert c.enabled()


def test_questions_deal_first_then_catalog_by_p():
    qs = c.questions(ENV)
    assert [q.rule_id for q in qs] == ["c3:deal:0", "c3:q:coi", "c3:q:low"]
    assert all(q.severity == "warning" for q in qs)
    assert qs[0].sources[0]["filename"] == "deal.eml"
    assert qs[1].domain_label == "Commercial terms"


def test_view_strips_citations():
    v = c.view(ENV)
    assert v["summary"] == "Install three cameras."
    assert v["sections"]["scope"][0] == {"text": "Mount cameras.", "cites": ["atm_a"]}
    assert len(v["answered_in_deal"]) == 1


def test_no_brief_means_none():
    assert c.written({"atoms": []}) is None


def test_handoff_takes_the_heads_brief(tmp_path, monkeypatch):
    import json

    from orbitbrief_core.pm_handoff import build_pm_handoff

    case = tmp_path / "CASE_C3"
    case.mkdir()
    (case / "inspection_report.json").write_text(json.dumps({"project_id": "CASE_C3", "artifacts": [],
                                                             "atom_lineage": [], "packets": []}))
    (case / "00_envelope.json").write_text(json.dumps(ENV))
    monkeypatch.setenv("ORBITBRIEF_C3_BRIEF", "on")
    on = build_pm_handoff(case)
    assert [q.rule_id for q in on.customer_questions][:1] == ["c3:deal:0"]
    assert on.one_line_summary == "Install three cameras."
    assert on.c3_brief["sections"]["scope"]
    assert on.metrics["customer_question_engine"]["source"] == "c3_brief"
    monkeypatch.delenv("ORBITBRIEF_C3_BRIEF")
    off = build_pm_handoff(case)
    assert not off.c3_brief and not any(q.rule_id.startswith("c3:") for q in off.customer_questions)
