"""Gates for template-generated asks that splice raw atom text into a stem.

Every question below is copied verbatim from a live deal's
``customer_questions_pool`` and carries the verdict a DeepSeek audit gave it
(464 cards, 14 deals). The bad ones shipped to PMs labelled ``blocker``.
"""

from orbitbrief_core.pm_handoff.models import GapCard
from orbitbrief_core.pm_handoff.question_quality import (
    quoted_span_violation,
    validate_question_card,
)

# --- rated BAD by the audit: unusable quoted span -------------------------
BAD_QUOTED = [
    (
        'Lock scope for "• Protect adjacent finishes and flooring • Provide" '
        "— include as written, defer, or remove — CDW — at Atmore AL?",
        "quote_spliced_bullets",
    ),
    (
        'Which quote wave includes "Termination. PCIGA may terminate this Purchase" '
        "— this wave, deferred, or out — CDW — at Atmore AL?",
        "quote_legal_boilerplate",
    ),
    (
        'Does "The selected vendor shall provide all labor" remain in fixed fee, '
        "or move to T&M / change-order — CDW — at Atmore AL?",
        "quote_rfp_boilerplate",
    ),
    (
        'Who owns delivery of "the intent of this project is to install a new LED" '
        "— PurTera, GC, or customer — CDW — at Atmore AL?",
        "quote_mid_sentence",
    ),
]

# --- rated GOOD by the audit: must survive both gates ---------------------
GOOD_ASKS = [
    # Hardest negative: quotes a span AND ends in a defer/revise stem that is
    # deliberately close to the internal-classification wording.
    'Confirm qty/model for "(17) Cameras device ip camera" is the authoritative '
    "quote line — include as written, revise the assumption, or defer?",
    "Who is the day-of onsite contact for Atmore AL, and how do we reach them — CDW?",
    "Which existing displays/codecs stay mounted, which are removed, and what is "
    "reused vs new BOM on this site — CDW — at Atmore AL?",
    "What hardware is customer-furnished vs PurTera-furnished — and who stages it "
    "to site — CDW — at Atmore AL?",
    "What are the approved work hours / blackout windows for install and cutover?",
]

# --- rated BAD: internal commercial classification, not a customer ask -----
INTERNAL_STEMS = [
    'Which quote wave includes "Provide and install: device display" — this wave, '
    "deferred, or out — CDW — at Atmore AL?",
    'Does "Install in rack items provided by Tillys" remain in fixed fee, or move '
    "to T&M / change-order — Sonance DSP?",
]


def _card(question: str) -> GapCard:
    return GapCard(
        rule_id="scope.scope_item.deadbeef",
        domain_id="operations",
        domain_label="Operations",
        label="Scope",
        severity="blocker",
        message=question,
        suggested_open_question=question,
        sources=[{"filename": "rfp.pdf", "quote": "x" * 40}],
    )


def test_unusable_quoted_spans_are_flagged():
    for question, expected in BAD_QUOTED:
        assert quoted_span_violation(question) == expected, question


def test_good_asks_keep_their_quoted_spans():
    for question in GOOD_ASKS:
        assert quoted_span_violation(question) is None, question


def test_internal_classification_stems_are_rejected():
    for question in INTERNAL_STEMS:
        codes = {v.code for v in validate_question_card(_card(question))}
        assert "internal_scope_classification" in codes, question


def test_good_asks_are_not_rejected_by_the_new_gates():
    """The gates must not cost a PM a question the auditor rated good."""
    new_codes = {
        "internal_scope_classification",
        "quote_spliced_bullets",
        "quote_legal_boilerplate",
        "quote_rfp_boilerplate",
        "quote_mid_sentence",
        "quote_cut_midclause",
    }
    for question in GOOD_ASKS:
        codes = {v.code for v in validate_question_card(_card(question))}
        assert not (codes & new_codes), (question, codes)


def test_bad_quoted_asks_are_rejected_end_to_end():
    for question, _ in BAD_QUOTED:
        assert validate_question_card(_card(question)), question
