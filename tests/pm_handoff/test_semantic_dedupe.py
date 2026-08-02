"""Semantic near-duplicate clustering for customer questions / gaps."""
from __future__ import annotations

from orbitbrief_core.pm_handoff.models import GapCard, SiteSummary
from orbitbrief_core.pm_handoff.question_engine import (
    MODE_AV,
    MODE_NETWORK_EDGE_INSTALL,
    QuestionCandidate,
    _candidates_from_evidence_atoms,
    build_customer_questions,
    rank_and_cap,
)
from orbitbrief_core.pm_handoff.question_feedback import (
    ACTION_DISMISS,
    QuestionFeedbackEvent,
    compile_feedback_policy,
    fingerprint_question,
)
from orbitbrief_core.pm_handoff.semantic_dedupe import (
    is_near_duplicate_of_any,
    pair_near_duplicate,
    resolve_question_embedder,
    semantic_dedupe,
    soft_containment,
)
from orbitbrief_core.pm_handoff.builder import _suppress_gaps_covered_by_questions


def test_subset_paraphrase_sop_approval_collapses():
    a = (
        "Request customer's SOP before first site; determine who owns revisions "
        "and approval authority for scope/change decisions."
    )
    b = (
        "Determine customer approval authority for scope/change decisions on "
        "this engagement; confirm with the customer."
    )
    assert soft_containment(a, b) >= 0.75
    emb = resolve_question_embedder()
    va, vb = emb.embed([a, b])
    is_dup, _, _ = pair_near_duplicate(a, b, va, vb)
    assert is_dup


def test_topology_paraphrases_collapse():
    a = "Confirm topology: one Meraki MX (or edge device) per site, or a shared/hub-and-spoke model?"
    b = "Confirm topology: one edge device per site, or a shared/hub model?"
    assert is_near_duplicate_of_any(a, [b])


def test_distinct_asks_do_not_collapse():
    a = "Which site is the first walkthrough / site survey, and who schedules customer access?"
    b = "Is the site survey a separate charge (per-site fee / NTE), or included in the install quote?"
    assert not is_near_duplicate_of_any(a, [b])


def test_rank_and_cap_keeps_one_canonical_per_cluster():
    cands = [
        QuestionCandidate(
            rule_id="mode.network_edge_install.topology_per_site",
            domain_id="network_edge_install",
            label="Edge topology",
            severity="blocker",
            message="open",
            suggested_open_question=(
                "Confirm topology: one Meraki MX (or edge device) per site, "
                "or a shared/hub-and-spoke model?"
            ),
            source="mode_template",
            score=0.95,
        ),
        QuestionCandidate(
            rule_id="evidence.open_question.once-we-know",
            domain_id="project",
            label="Open",
            severity="warning",
            message="Once we know is it going to be one device per site?",
            suggested_open_question="Confirm topology: one edge device per site, or a shared/hub model?",
            source="evidence",
            score=0.9,
        ),
        QuestionCandidate(
            rule_id="composite.sop_approval",
            domain_id="project",
            label="SOP",
            severity="warning",
            message="sop",
            suggested_open_question=(
                "Request customer's SOP before first site; determine who owns revisions "
                "and approval authority for scope/change decisions."
            ),
            source="evidence",
            score=0.88,
        ),
        QuestionCandidate(
            rule_id="evidence.approval",
            domain_id="project",
            label="Approval",
            severity="warning",
            message="approval",
            suggested_open_question=(
                "Determine customer approval authority for scope/change decisions on "
                "this engagement; confirm with the customer."
            ),
            source="evidence",
            score=0.85,
        ),
        QuestionCandidate(
            rule_id="mode.network_edge_install.circuit_ready",
            domain_id="network_edge_install",
            label="Circuits",
            severity="warning",
            message="circuits",
            suggested_open_question=(
                "Which sites have circuits turned up and ready for smart-hands install, "
                "and which are still waiting on the carrier?"
            ),
            source="mode_template",
            score=0.83,
        ),
    ]
    ranked, meta = rank_and_cap(cands, cap=8)
    texts = [c.suggested_open_question.lower() for c in ranked]
    assert meta["semantic_dedupe_merged_pairs"] >= 1
    # One topology (prefer blocker mode template)
    topo = [t for t in texts if "topology" in t or ("per site" in t and "hub" in t)]
    assert len(topo) == 1
    assert any(
        c.severity == "blocker"
        for c in ranked
        if "topology" in c.suggested_open_question.lower()
        or "hub" in c.suggested_open_question.lower()
    )
    # Circuits kept
    assert any("circuit" in t for t in texts)
    # Under hash embedder, subset containment may still fold approval⊂SOP composite;
    # under neural they stay distinct. Always keep ≥1 governance ask.
    approvalish = [t for t in texts if "approval" in t or "sop" in t]
    assert len(approvalish) >= 1
    assert len(ranked) >= 3


def test_rank_prefers_mode_template_over_evidence_risk_dump():
    """Curated AV replication ask must win over paraphrased evidence dump."""
    from orbitbrief_core.pm_handoff.question_engine import _candidate_rank_tuple

    mode = QuestionCandidate(
        rule_id="mode.av_install.replication_cable_path",
        domain_id="audio_visual",
        label="TV replication cable path",
        severity="blocker",
        message="Replication cable visibility / reroute is annotated on site photos.",
        suggested_open_question=(
            "Confirm replication cable TV1→TV2 must be rerouted/hidden behind the wall "
            "per photo annotations."
        ),
        source="mode_template",
        score=0.93,
    )
    evidence = QuestionCandidate(
        rule_id="evidence.risk.risks-replication-cable",
        domain_id="project",
        label="Risk needs owner answer",
        severity="blocker",
        message="Replication cable is visible across the wall.",
        suggested_open_question=(
            "Confirm replication cable path TV1 to TV2: must the visible wall cable "
            "be rerouted/hidden behind the wall?"
        ),
        source="evidence",
        score=0.72,
    )
    assert _candidate_rank_tuple(mode) > _candidate_rank_tuple(evidence)
    ranked, meta = rank_and_cap([evidence, mode], cap=4)
    assert meta["semantic_dedupe_merged_pairs"] >= 1
    assert len(ranked) == 1
    assert ranked[0].rule_id == "mode.av_install.replication_cable_path"


def test_evidence_drops_labeled_risks_prefix_dumps():
    atoms = [
        {
            "id": "r1",
            "atom_type": "risk",
            "text": "RISKS: Replication cable is visible across the wall.",
        },
        {
            "id": "r2",
            "atom_type": "open_question",
            "text": "Who owns drywall patch after display relocation?",
        },
    ]
    out = _candidates_from_evidence_atoms(atoms, project_mode=MODE_AV)
    assert all("RISKS:" not in (c.message or "") for c in out)
    assert any("drywall" in (c.suggested_open_question or "").lower() for c in out)


def test_dismiss_suppresses_semantic_neighbor():
    """Dismissing mode-template topology also drops evidence paraphrase."""
    dismiss = QuestionFeedbackEvent(
        deal_id="deal-1",
        action=ACTION_DISMISS,
        project_mode=MODE_NETWORK_EDGE_INSTALL,
        rule_id="mode.network_edge_install.topology_per_site",
        question_text=(
            "Confirm topology: one Meraki MX (or edge device) per site, "
            "or a shared/hub-and-spoke model?"
        ),
        fingerprint=fingerprint_question(
            "Confirm topology: one Meraki MX (or edge device) per site, "
            "or a shared/hub-and-spoke model?"
        ),
    )
    atoms = [
        {
            "id": "a1",
            "atom_type": "scope_item",
            "raw_text": "Remote Hands SDWAN Meraki MX Turning on circuits at each location",
        },
        {
            "id": "a2",
            "atom_type": "open_question",
            "raw_text": "Once we know is it going to be one device per site?",
        },
        {
            "id": "a3",
            "atom_type": "deal_metadata",
            "raw_text": "Will probably not do Montreal — keep everything on US paper",
        },
    ]
    cards, _ = build_customer_questions(
        gaps=[],
        sites=[SiteSummary(name=f"S{i}", kind="physical_site", publishable=True) for i in range(5)],
        envelope={
            "atoms": atoms,
            "service_routing": {
                "primary": "network_maintenance",
                "override_reason": "sdwan_meraki_network_install_evidence",
            },
        },
        feedback_events=[dismiss],
        cap=8,
    )
    joined = " | ".join(c.suggested_open_question.lower() for c in cards)
    assert "topology" not in joined
    assert "one device per site" not in joined
    assert "hub" not in joined or "spoke" not in joined


def test_gap_question_cross_suppress_promotes_blocker_severity():
    questions = [
        GapCard(
            rule_id="cq.commercial",
            domain_id="global",
            domain_label="Global",
            label="Commercial",
            severity="warning",
            message="ask commercial",
            suggested_open_question="What is the commercial model: fixed fee, T&M, NTE?",
        )
    ]
    gaps = [
        GapCard(
            rule_id="global.commercial_structure",
            domain_id="global",
            domain_label="Global",
            label="Commercial",
            severity="blocker",
            message="No pricing structure found",
            suggested_open_question=(
                "What is the commercial model: fixed fee, T&M, NTE, unit price, "
                "milestone billing, or quote/PO structure?"
            ),
        ),
        GapCard(
            rule_id="global.exclusions",
            domain_id="global",
            domain_label="Global",
            label="Exclusions",
            severity="warning",
            message="No exclusions",
            suggested_open_question="What is explicitly excluded or by others?",
        ),
    ]
    kept = _suppress_gaps_covered_by_questions(gaps, questions)
    assert len(kept) == 1
    assert kept[0].rule_id == "global.exclusions"
    assert questions[0].severity == "blocker"


def test_distinct_intents_sop_approval_acceptance_stay_separate():
    """SOP receipt ≠ generic approval ≠ POC acceptance — do not over-merge."""
    from dataclasses import dataclass

    from orbitbrief_core.pm_handoff.semantic_dedupe import pair_near_duplicate
    from orbitbrief_core.retrieval.embedder import DeterministicHashEmbedder

    @dataclass
    class Row:
        text: str
        score: float

    sop = "Can we get the customer's SOP before the first site, and who owns revisions?"
    approval = (
        "Who approves putting Montreal / Canada work on CDW US paper versus deferring that site?"
    )
    accept = (
        "Who signs POC / SOP acceptance after the first site, and what is the pass/fail criteria?"
    )
    survey = "Which site is the first walkthrough / site survey, and who schedules customer access?"
    commercial = (
        "Is the site survey a separate charge (per-site fee / NTE), or included in the install quote?"
    )
    rows = [
        Row(sop, 0.9),
        Row(approval, 0.88),
        Row(accept, 0.84),
        Row(survey, 0.86),
        Row(commercial, 0.85),
    ]
    # Neural path: cosine-only. Hash stub still uses lexical gates — force neural
    # flag via pair check so CI proves distinct intents don't collapse by family.
    emb = DeterministicHashEmbedder(dim=256)
    vecs = emb.embed([sop, approval, accept])
    assert not pair_near_duplicate(sop, approval, vecs[0], vecs[1], neural=True)[0]
    assert not pair_near_duplicate(sop, accept, vecs[0], vecs[2], neural=True)[0]
    assert not pair_near_duplicate(approval, accept, vecs[1], vecs[2], neural=True)[0]

    kept, meta = semantic_dedupe(
        rows,
        text_fn=lambda r: r.text,
        score_fn=lambda r: (r.score,),
    )
    # Topology-style paraphrases may still merge under hash; these five texts
    # are intentionally distinct — keep all five when containment is low.
    assert meta.output_count >= 4
    assert any("SOP before the first site" in k.text for k in kept)
    assert any("Montreal" in k.text or "Canada" in k.text for k in kept)
    assert any("walkthrough" in k.text for k in kept)
    assert any("separate charge" in k.text for k in kept)


def test_semantic_dedupe_prefers_pm_gold():
    items = [
        ("mode", "Who owns change approval on this engagement?", 0.8, "mode_template"),
        ("gold", "Who is the customer approval authority for scope/change decisions?", 0.97, "pm_gold"),
    ]

    class Row:
        def __init__(self, rid, text, score, source):
            self.rule_id = rid
            self.text = text
            self.score = score
            self.source = source

    rows = [Row(*x) for x in items]
    # Force near-dup via containment-friendly wording
    rows[0].text = (
        "Determine customer approval authority for scope/change decisions on "
        "this engagement; confirm with the customer."
    )
    rows[1].text = (
        "Request customer's SOP before first site; determine who owns revisions "
        "and approval authority for scope/change decisions."
    )

    def score_fn(r: Row) -> tuple:
        src = {"pm_gold": 4, "evidence": 3, "mode_template": 2}.get(r.source, 0)
        return (r.score, src)

    kept, meta = semantic_dedupe(
        rows,
        text_fn=lambda r: r.text,
        score_fn=score_fn,
    )
    assert meta.output_count == 1
    assert kept[0].source == "pm_gold"
