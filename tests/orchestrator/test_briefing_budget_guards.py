"""Tests for the brain prompt-budget guards.

The COPPER_001 wall-clock incident on 2026-05-15: a single
``low_voltage_cabling`` brain call burned 21 minutes and emitted zero
items because the snapshot prompt expanded to fill qwen3:14b's entire
40 K-token context window, leaving no room for the JSON response. The
runner now caps packets-per-family + snippet length + gold-example
count, AND has a belt-and-suspenders ``_shrink_snapshot_inplace``
helper that aggressively trims the snapshot if it's still oversized.
These tests lock in those guards.
"""
from __future__ import annotations

import json

from orbitbrief_core.brains._briefing_runner import (
    _GOLD_EXAMPLES_PER_SECTION_CAP,
    _GUIDANCE_LINES_PER_SECTION_CAP,
    _MAX_OUTPUT_TOKENS,
    _MAX_SNIPPET_CHARS,
    _PACKETS_PER_FAMILY_CAP,
    _shrink_snapshot_inplace,
    _format_validation_failure,
)


def test_default_budgets_are_below_qwen3_14b_safe_envelope() -> None:
    # qwen3:14b ships with a 40960-token context. Empirically each
    # packet view averages ~250 chars (~80 tokens) and there are ~9
    # packet families on a real RFP case. With these caps the
    # packet-bundle portion of the prompt should stay well under
    # half the context window, leaving headroom for the system
    # prompt + response. If anyone bumps these defaults without
    # thinking about the math, this test should be the trip-wire.
    assert _PACKETS_PER_FAMILY_CAP <= 8
    assert _MAX_SNIPPET_CHARS <= 200
    assert _GOLD_EXAMPLES_PER_SECTION_CAP <= 1
    assert _GUIDANCE_LINES_PER_SECTION_CAP <= 5
    # Output cap should give the response real room.
    assert _MAX_OUTPUT_TOKENS >= 8192


def test_shrink_snapshot_halves_packets_per_family_until_under_target() -> None:
    big_packet = {"packet_id": "pkt_x" * 20, "family": "f", "atom_text": {"a": "x" * 500}}
    snapshot = {
        "brief": {"project_id": "p", "compile_id": "c"},
        "domain": {"id": "d"},
        "section_guidance": {
            f"sec_{i}": {
                "guidance": [f"g{i}_{j}" for j in range(5)],
                "gold_examples": [{"statement": "x" * 200} for _ in range(3)],
            }
            for i in range(9)
        },
        "packets_by_family": {
            f"family_{i}": [dict(big_packet) for _ in range(20)]
            for i in range(8)
        },
    }
    before = len(json.dumps(snapshot))
    target = before // 4
    _shrink_snapshot_inplace(snapshot, target_chars=target)
    after = len(json.dumps(snapshot))
    assert after <= target * 1.05, f"shrink failed: {after} > {target}"
    # Floor: at least one packet per family stays.
    for fam, pkts in snapshot["packets_by_family"].items():
        assert len(pkts) >= 1, f"shrink zeroed family {fam}"
    # Floor: at least one guidance line per section stays.
    for sec, entry in snapshot["section_guidance"].items():
        assert len(entry["guidance"]) >= 1, f"shrink zeroed guidance for {sec}"


def test_truncation_error_message_tells_operator_what_to_bump() -> None:
    err = json.JSONDecodeError("Unterminated string starting at", "x" * 10, 5)
    msg = _format_validation_failure(err)
    # The single most common production failure now has a clear
    # remediation hint instead of a cryptic char-offset error.
    assert "output-token truncation" in msg
    assert "max-output-tokens" in msg
