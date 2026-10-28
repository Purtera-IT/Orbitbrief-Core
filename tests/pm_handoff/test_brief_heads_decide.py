"""ORBITBRIEF_C3_BRIEF=on: the super heads decide every PM panel.

Each test pins one fix from the 2026-10-27 override audit
(c3-local/runE/recovery/AUDIT_overrides_orbitbrief.md)."""
from __future__ import annotations

import copy
import json

import pytest

from orbitbrief_core.pm_handoff import build_pm_handoff
from orbitbrief_core.pm_handoff import c3_brief as c
from orbitbrief_core.pm_handoff.models import GapCard

KEPT_EXCL = "atm_excl"      # head: out_of_scope
DROPPED = "atm_dropped"     # head left it out; regex would call it an exclusion
CUST = "atm_cust"
PROV = "atm_prov"
RISK_DROPPED = "atm_risk"   # a risk line the heads left out

ATOMS = [
    {"id": KEPT_EXCL, "artifact_id": "art_1", "atom_type": "exclusion",
     "text": "Exterior antenna mounts are not part of this job."},
    {"id": DROPPED, "artifact_id": "art_1", "atom_type": "scope_item",
     "text": "One compatible 66 block and bridge clips are not included in the quote."},
    {"id": CUST, "artifact_id": "art_1", "atom_type": "dependency",
     "text": "Provide escort and badge access for the technician."},
    {"id": PROV, "artifact_id": "art_1", "atom_type": "task",
     "text": "Provide Customer with engineer name and contact information."},
    {"id": RISK_DROPPED, "artifact_id": "art_1", "atom_type": "risk",
     "text": "Risk: the landlord may refuse ceiling access, delaying the install."},
]

SECTIONS = {
    "out_of_scope": [{"id": KEPT_EXCL, "type": "exclusion", "text": ATOMS[0]["text"]}],
    "customer_responsibilities": [{"id": CUST, "type": "dependency", "text": ATOMS[2]["text"],
                                   "supplier": ["customer", 0.8]}],
    "provider_responsibilities": [{"id": PROV, "type": "task", "text": ATOMS[3]["text"]}],
}

WRITTEN = {
    "summary": "Run cabling at two sites [atm_prov].",
    "sections": {"scope": [{"text": "Run cabling [atm_prov].", "cites": ["atm_prov"]}]},
    "open_questions": [
        {"question": "Is weekend work allowed?", "owner": "project_manager", "cites": [CUST], "kind": "deal"},
        {"question": "Who stages the equipment?", "owner": "project_manager", "cites": [PROV], "kind": "pricing"},
    ],
    "catalog_questions": [],
}


def _env(**brief):
    b = {"version": 2, "service": {"value": "low_voltage_cabling", "p": 0.93, "by": "base:deal:primary_service"},
         "sections": copy.deepcopy(SECTIONS), "also_mentioned": [],
         "questions": [{"id": CUST, "text": "Is weekend work allowed?", "owner": "project_manager"}],
         "written": copy.deepcopy(WRITTEN)}
    b.update(brief)
    return {"project_id": "DEAL_H", "atoms": copy.deepcopy(ATOMS),
            "documents": [{"artifact_id": "art_1", "filename": "sow.pdf"}], "c3_brief": b}


def _case(tmp_path, env):
    case = tmp_path / "CASE_H"
    case.mkdir()
    report = {"project_id": "CASE_H", "atom_lineage": copy.deepcopy(env.get("atoms") or []), "packets": [],
              "artifacts": [{"artifact_id": "art_1", "filename": "sow.pdf", "atoms": []}]}
    (case / "inspection_report.json").write_text(json.dumps(report))
    (case / "00_envelope.json").write_text(json.dumps(env))
    return case


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("ORBITBRIEF_C3_BRIEF", "on")
    monkeypatch.delenv("ORBITBRIEF_ROUTER_MODEL", raising=False)
    monkeypatch.delenv("ORBITBRIEF_QUESTION_FEEDBACK_PATH", raising=False)


def test_report_keeps_only_head_kept_lines_with_head_type():
    rows = [{"id": KEPT_EXCL, "atom_type": "scope_item"}, {"id": DROPPED, "atom_type": "scope_item"}]
    report = {"artifacts": [{"artifact_id": "art_1", "atoms": rows}], "atom_lineage": rows, "atoms": rows,
              "envelope": {"atoms": rows}}
    out = c.heads_report(report, c.kept_lines(_env()))
    for got in (out["artifacts"][0]["atoms"], out["atom_lineage"], out["atoms"], out["envelope"]["atoms"]):
        assert [(a["id"], a["atom_type"]) for a in got] == [(KEPT_EXCL, "exclusion")]


def test_panels_follow_the_heads(tmp_path, on):
    h = build_pm_handoff(_case(tmp_path, _env()))
    # 1+2: exclusions are the head's out_of_scope lines only; the regex no
    # longer moves a dropped "not included" scope line into exclusions.
    assert [e["text"] for e in h.exclusions] == [ATOMS[0]["text"]]
    # 3: responsibilities from the heads' sections, with the supplier answer.
    assert {(r["party"], r["text"]) for r in h.responsibilities} == {
        ("customer", ATOMS[2]["text"]), ("provider", ATOMS[3]["text"])}
    # 1: a line the heads left out reaches no panel.
    blob = json.dumps(h.to_dict() if hasattr(h, "to_dict") else h.__dict__, default=str)
    assert "66 block" not in blob and "landlord may refuse" not in blob


def test_off_keeps_the_regex_panels(tmp_path, monkeypatch):
    monkeypatch.delenv("ORBITBRIEF_C3_BRIEF", raising=False)
    h = build_pm_handoff(_case(tmp_path, _env()))
    assert any("66 block" in e["text"] for e in h.exclusions)
    assert "landlord may refuse" in json.dumps(h.facts_by_category, default=str)
    assert not h.c3_brief


def test_service_head_decides_and_router_is_not_called(tmp_path, on, monkeypatch):
    from orbitbrief_core.pm_handoff import builder

    monkeypatch.setattr(builder, "_router_chat", lambda: (_ for _ in ()).throw(AssertionError("router called")))
    env = _env()
    routing = builder._resolve_service_routing(env, tmp_path)
    assert routing == {"primary": "low_voltage_cabling", "confidence": 0.93, "source": "c3_brief",
                       "by": "base:deal:primary_service"}


@pytest.mark.parametrize("svc", [
    {"value": "low_voltage_cabling", "p": 0.5, "by": "base:deal:primary_service"},
    {"value": "imac", "p": 0.9, "by": "base:deal:primary_service", "unsure": True},
    {"value": "wireless", "by": "rule:domain_pack"},
])
def test_unsure_service_falls_to_router_marked(tmp_path, on, svc):
    env = _env(service=svc)
    env["service_routing"] = {"primary": "staff_augmentation", "confidence": 0.9}
    assert c.service_routing(env) is None
    h = build_pm_handoff(_case(tmp_path, env))
    assert h.c3_brief["service_decided_by"] == "core_router"


def test_core_question_pipeline_and_gap_packs_skipped(tmp_path, on, monkeypatch):
    from orbitbrief_core.pm_handoff import builder

    monkeypatch.setattr(builder, "build_customer_questions",
                        lambda **k: (_ for _ in ()).throw(AssertionError("Core question pipeline ran")))
    h = build_pm_handoff(_case(tmp_path, _env()))
    assert h.gaps == []
    assert [q.suggested_open_question for q in h.customer_questions] == [
        "Is weekend work allowed?", "Who stages the equipment?"]
    assert h.metrics["customer_question_engine"]["core_question_pipeline"] == "skipped"
    assert all(q.severity == "warning" for q in h.customer_questions)


def test_head_question_never_promoted_by_a_core_gap():
    from orbitbrief_core.pm_handoff.builder import _suppress_gaps_covered_by_questions

    q = GapCard(rule_id="c3:deal:abc", domain_id="deal", domain_label="", label="", severity="warning",
                message="", suggested_open_question="Is weekend work allowed?")
    g = GapCard(rule_id="pack.weekend", domain_id="x", domain_label="", label="", severity="blocker",
                message="", suggested_open_question="Is weekend work allowed?")
    qs = [q]
    _suppress_gaps_covered_by_questions([g], qs)
    assert qs[0].severity == "warning"


class _RewordingChat:
    """A chat client that rewrites anything it is sent."""

    def complete(self, messages, **k):
        import re as _re

        keys = _re.findall(r'key: "([^"]+)"', messages[-1].content)
        return json.dumps({"items": [{"key": key, "polished": "REWORDED"} for key in keys]})


def test_polish_never_drops_or_rewords_a_head_question(tmp_path, on):
    from orbitbrief_core.pm_handoff.polish import polish_pm_handoff
    from orbitbrief_core.pm_handoff.question_engine import _is_customer_facing_question

    # The wording filter drops "weekend" asks; a head question must survive it.
    assert not _is_customer_facing_question("Is weekend work allowed?")
    h = build_pm_handoff(_case(tmp_path, _env()))
    polished, _ = polish_pm_handoff(h, chat_client=_RewordingChat(), model="m",
                                    cache_path=tmp_path / "cache.jsonl")
    assert [q.rule_id for q in polished.customer_questions] == [q.rule_id for q in h.customer_questions]
    assert polished.customer_answer_slots == h.customer_answer_slots


def test_question_ids_follow_content_not_position():
    a = c.questions(_env())
    env = _env()
    env["c3_brief"]["written"]["open_questions"].reverse()
    b = c.questions(env)
    assert {q.suggested_open_question: q.rule_id for q in a} == {q.suggested_open_question: q.rule_id for q in b}


def test_pm_dismissed_or_answered_head_question_stays_gone(tmp_path, on, monkeypatch):
    first = c.questions(_env())
    fb = tmp_path / "fb.jsonl"
    fb.write_text(json.dumps({"action": "dismiss", "rule_id": first[0].rule_id, "deal_id": "DEAL_H",
                              "question_text": first[0].suggested_open_question}) + "\n"
                  + json.dumps({"action": "answered", "rule_id": "c3:pricing:old", "deal_id": "DEAL_H",
                                "question_text": "Who stages the equipment?", "edited_text": "We do."}) + "\n")
    monkeypatch.setenv("ORBITBRIEF_QUESTION_FEEDBACK_PATH", str(fb))
    h = build_pm_handoff(_case(tmp_path, _env()))
    assert h.customer_questions == []
    assert h.metrics["customer_question_engine"]["settled_by_pm"] == 2


def test_missing_heads_brief_is_loud(tmp_path, on):
    env = _env()
    env.pop("c3_brief")
    h = build_pm_handoff(_case(tmp_path, env))
    assert h.c3_brief["state"] == "missing" and "Heads unavailable" in h.c3_brief["banner"]
    assert h.metrics["customer_question_engine"]["source"] == "core_fallback"
    assert h.executive_summary["overview"].startswith("**Heads unavailable")
    assert h.executive_summary["c3_state"] == "missing"


def test_unwritten_heads_brief_still_decides(tmp_path, on, monkeypatch):
    from orbitbrief_core.pm_handoff import builder

    env = _env(written={"error": "TimeoutError"})
    called = []
    monkeypatch.setattr(builder, "build_customer_questions", lambda **k: called.append(1) or ([], {}))
    h = build_pm_handoff(_case(tmp_path, env))
    assert not called
    assert h.c3_brief["state"] == "unwritten" and h.c3_brief["banner"]
    assert h.c3_brief["sections"]["out_of_scope"][0]["text"] == ATOMS[0]["text"]
    assert [q.suggested_open_question for q in h.customer_questions] == ["Is weekend work allowed?"]
    assert [e["text"] for e in h.exclusions] == [ATOMS[0]["text"]]
    assert h.executive_summary["source"] == "c3_brief"
