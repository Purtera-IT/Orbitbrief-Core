"""Phase-2 verdict wiring: envelope["reconciliation"] -> PMHandoff -> markdown.

The dead pipe found by the border audit, now lit. The COPPER shape is the
founding fixture on the parser-os side; this is its landing on the brief side.
"""

from orbitbrief_core.pm_handoff.builder import _build_reconciliation_verdicts
from orbitbrief_core.pm_handoff.models import PMHandoff
from orbitbrief_core.pm_handoff.render_markdown import (
    _render_reconciliation_verdicts,
    render_pm_handoff_markdown,
)

_RESOLVED = {
    "conflict_id": "cf_1",
    "scope_key": "cat6 drops @ ATL-01",
    "resolved": True,
    "winner": {"atom_id": "a1", "rank": 90, "value": "56",
               "authority": "customer_current_authored",
               "text": "plan for 56 drops"},
    "superseded": [
        {"atom_id": "a2", "rank": 65, "value": "40",
         "authority": "vendor_quote", "text": "Cat6 drop, qty 40"},
    ],
    "edge_ids": ["e1"],
    "reason": "56 governs because customer_current_authored (rank 90) beats '40' at rank 65",
}
_OPEN = {
    "conflict_id": "cf_2",
    "scope_key": "APs @ HQ",
    "resolved": False,
    "winner": None,
    "superseded": [
        {"atom_id": "a3", "rank": 90, "value": "50",
         "authority": "customer_current_authored", "text": "50 APs"},
        {"atom_id": "a4", "rank": 90, "value": "56",
         "authority": "customer_current_authored", "text": "56 APs"},
    ],
    "edge_ids": ["e2"],
    "reason": "two rank-90 claims disagree; picking between equals is a PM's judgment",
}
_ENVELOPE_REC = {
    "resolved": [_RESOLVED],
    "open_conflicts": [_OPEN],
    "counts": {"conflict_sets": 2, "resolved": 1, "open": 1},
    "edge_rule_precision": {"contradicts": 0.41, "supports": 0.90,
                            "n_labelled_pairs": 447},
}


def _handoff(**kw) -> PMHandoff:
    return PMHandoff(case_id="c1", status="green", status_label="ok",
                     one_line_summary="s", metrics={}, **kw)


class TestBuilderProjection:
    def test_passes_through_with_counts_and_precision(self):
        out = _build_reconciliation_verdicts({"reconciliation": _ENVELOPE_REC})
        assert out["counts"] == {"conflict_sets": 2, "resolved": 1, "open": 1}
        assert out["resolved"][0]["winner"]["value"] == "56"
        assert out["edge_rule_precision"]["contradicts"] == 0.41

    def test_old_envelope_without_key_is_empty(self):
        assert _build_reconciliation_verdicts({}) == {}
        assert _build_reconciliation_verdicts(None) == {}
        assert _build_reconciliation_verdicts({"reconciliation": "junk"}) == {}

    def test_caps_report_uncapped_counts(self):
        rec = {"resolved": [_RESOLVED] * 60, "open_conflicts": [],
               "counts": {"conflict_sets": 60, "resolved": 60, "open": 0}}
        out = _build_reconciliation_verdicts({"reconciliation": rec})
        assert len(out["resolved"]) == 50          # capped for handoff size
        assert out["counts"]["resolved"] == 60     # the truth stays uncapped


class TestMarkdownSection:
    def test_absent_renders_nothing(self):
        assert _render_reconciliation_verdicts(_handoff()) == []

    def test_verdicts_render_with_receipts_and_caveat(self):
        h = _handoff(reconciliation_verdicts=_build_reconciliation_verdicts(
            {"reconciliation": _ENVELOPE_REC}))
        md = "\n".join(_render_reconciliation_verdicts(h))
        assert "resolved by authority" in md
        assert "56" in md and "customer_current_authored" in md
        assert "rank 90" in md
        assert "superseded" in md and "vendor_quote" in md
        assert "41% precise" in md          # the honesty caveat travels
        assert "Needs your call" in md      # the open conflict surfaces
        assert "PM's judgment" in md

    def test_full_handoff_render_includes_the_section(self):
        h = _handoff(reconciliation_verdicts=_build_reconciliation_verdicts(
            {"reconciliation": _ENVELOPE_REC}))
        md = render_pm_handoff_markdown(h)
        assert "Cross-document conflicts" in md

    def test_json_round_trip_via_to_dict(self):
        h = _handoff(reconciliation_verdicts=_build_reconciliation_verdicts(
            {"reconciliation": _ENVELOPE_REC}))
        import json
        d = json.loads(json.dumps(h.to_dict()))
        assert d["reconciliation_verdicts"]["counts"]["open"] == 1
