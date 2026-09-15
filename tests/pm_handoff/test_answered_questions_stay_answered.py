"""A PM's answer keeps its ask off the next brief of the same deal, whatever id the
ask comes back under; another deal's answer does not (000036, 2026-09-15)."""
from orbitbrief_core.pm_handoff.question_engine import QuestionCandidate, apply_feedback
from orbitbrief_core.pm_handoff.question_feedback import (
    ACTION_ANSWERED,
    QuestionFeedbackEvent,
    compile_feedback_policy,
    fingerprint_question,
)

Q = "Who confirms the Samsung 65-inch display, mount and hardware are onsite before the techs arrive?"
A = "Checkout LLC provides the Samsung 65-inch display, the mount or stand, hardware and all accessories, and has them onsite before the technicians arrive."


def _cand(rule_id, text):
    return QuestionCandidate(
        rule_id=rule_id, domain_id="commercial", label=rule_id.split(".")[-1], severity="blocker",
        message=text, suggested_open_question=text, observed_summary="", source="llm_exposure", score=0.9,
    )


def _answered(deal_id="deal-36"):
    return QuestionFeedbackEvent(
        deal_id=deal_id, action=ACTION_ANSWERED, rule_id="llm.exposure.display_delivery_precondition",
        question_text=Q, edited_text=A, fingerprint=fingerprint_question(Q),
    )


def test_an_answered_rule_id_is_not_asked_again_on_that_deal():
    policy = compile_feedback_policy([_answered()], deal_id="deal-36")
    out = apply_feedback([_cand("llm.exposure.display_delivery_precondition", Q)], policy, project_mode="av_install")
    assert out == []


def test_the_same_ask_under_a_new_id_and_wording_is_still_answered():
    policy = compile_feedback_policy([_answered()], deal_id="deal-36")
    recoined = _cand(
        "llm.exposure.customer_kit_receipt_confirmation",
        "Checkout LLC must have the Samsung 65-inch display, mount, hardware and accessories onsite before the techs arrive — who confirms receipt?",
    )
    assert apply_feedback([recoined], policy, project_mode="av_install") == []


def test_another_deals_answer_does_not_silence_this_deal():
    policy = compile_feedback_policy([_answered(deal_id="deal-other")], deal_id="deal-36")
    assert policy.answered_rule_ids == frozenset() and policy.answered_texts == ()
    out = apply_feedback([_cand("llm.exposure.display_delivery_precondition", Q)], policy, project_mode="av_install")
    assert len(out) == 1


def test_without_a_deal_id_answers_still_apply():
    policy = compile_feedback_policy([_answered()])
    assert "llm.exposure.display_delivery_precondition" in policy.answered_rule_ids
