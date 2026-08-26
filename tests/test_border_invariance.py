"""Border invariance — the seam audit crosses into orbitbrief-core (2026-08-25).

The audit law from the parser-os side (five audits: every bug at a
representation boundary, none inside rules) applied to the envelope->core
border. One fix (string-dressed money) and the held invariants, pinned.
"""

import pytest

from orbitbrief_core.neural_heads._common import _largest_amount, resolve_deal_total
from orbitbrief_core.validator.sow_completeness import _router_primary


class TestDealTotalDress:
    """The brief's headline number must not depend on JSON number dressing."""

    @pytest.mark.parametrize("rev", [48500, 48500.0, "48500", "48,500.00", "$48,500"])
    def test_revenue_in_every_dress(self, rev):
        env = {"deal_financials": {"totals": {"revenue": rev}}}
        assert resolve_deal_total(env) == 48500.0

    @pytest.mark.parametrize("ot", [48500, "48500", "48,500"])
    def test_overall_total_in_every_dress(self, ot):
        env = {"deal_financials": {"overall_total": ot}}
        assert resolve_deal_total(env) == 48500.0

    def test_boolean_is_not_an_amount(self):
        env = {"deal_financials": {"totals": {"revenue": True}}}
        assert resolve_deal_total(env) is None

    def test_garbage_string_falls_through_not_crashes(self):
        env = {"deal_financials": {"totals": {"revenue": "TBD"}}}
        assert resolve_deal_total(env) is None

    @pytest.mark.parametrize("text", [
        "Total project revenue: $48,500.00",
        "Total project revenue: $48500",
        "Total project revenue: 48,500 USD",
    ])
    def test_largest_amount_dress(self, text):
        assert _largest_amount(text) == 48500.0


class TestRouterPrimaryDress:
    """Held invariants of the service_routing reader, pinned."""

    def test_abstained_yields_nothing(self):
        sr = {"enabled": True, "abstained": True, "primary": None,
              "neural_primary": "wireless", "confidence": 0.8}
        assert _router_primary(sr) == (None, 0.0)

    def test_confident_comes_through(self):
        sr = {"enabled": True, "abstained": False, "primary": "wireless",
              "confidence": 0.83}
        assert _router_primary(sr) == ("wireless", 0.83)

    def test_string_confidence_parses(self):
        sr = {"enabled": True, "abstained": False, "primary": "wireless",
              "confidence": "0.83"}
        assert _router_primary(sr) == ("wireless", 0.83)

    def test_missing_and_disabled_yield_nothing(self):
        assert _router_primary(None) == (None, 0.0)
        assert _router_primary({}) == (None, 0.0)
        assert _router_primary({"enabled": False, "primary": "wireless"}) == (None, 0.0)


class TestBorderSchemaTolerance:
    """parser-os keys core does not consume yet must SURVIVE, not be rejected
    or stripped -- the border's extra=allow policy is what lets the producer
    move first. envelope['reconciliation'] (phase-2 verdicts) is the live
    example: shipped by parser-os since 2026-08-24, consumer pending."""

    def test_new_producer_keys_round_trip(self):
        from orbitbrief_core.seam.envelope import EnvelopeV2

        payload = {
            "schema_version": "orbitbrief.input.v2",
            "project_id": "p1",
            "compile_id": "c1",
            "generated_at": "2026-08-25T00:00:00Z",
            "documents": [],
            "atoms": [],
            "summary": {"artifact_count": 0, "page_count": 0,
                        "atom_count": 0, "packet_count": 0},
            "reconciliation": {"resolved": [], "open_conflicts": [],
                               "counts": {"resolved": 0, "open": 0}},
            "service_routing": {"enabled": True, "abstained": True,
                                "scope_summary_version": 2},
        }
        dumped = EnvelopeV2.model_validate(payload).model_dump()
        assert dumped["reconciliation"]["counts"] == {"resolved": 0, "open": 0}
        assert dumped["service_routing"]["scope_summary_version"] == 2
