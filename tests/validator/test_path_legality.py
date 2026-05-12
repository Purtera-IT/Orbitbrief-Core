"""Phase-6 verify gate: an ungrounded claim is rejected by the validator."""
from __future__ import annotations

import pytest

from orbitbrief_core.validator import (
    BrainOutputValidator,
    DictEvidenceLookup,
    NullEvidenceLookup,
    ValidationRuleId,
    ValidationSeverity,
)


def _scope_item(item_id: str, *, packets, atoms):
    return {
        "id": item_id,
        "statement": f"item {item_id}",
        "supporting_packet_ids": list(packets),
        "supporting_atom_ids": list(atoms),
        "confidence": 0.85,
        "category": "general",
    }


def test_ungrounded_packet_id_is_rejected(
    build_state, small_bundle, small_brief, lookup_with_two_atoms
) -> None:
    """An item citing a packet not in the bundle → BLOCKER UNRESOLVED_PACKET."""
    state = build_state(
        {"scope_items": [_scope_item("s1", packets=("pkt_does_not_exist",), atoms=())]}
    )
    validator = BrainOutputValidator(lookup=lookup_with_two_atoms)
    report = validator.validate_managed_services(
        state, brief=small_brief, bundle=small_bundle
    )

    assert len(report.failed_items) == 1
    iv = report.failed_items[0]
    rule_ids = {f.rule_id for f in iv.failures}
    assert ValidationRuleId.UNRESOLVED_PACKET in rule_ids
    assert iv.has_blocker
    assert iv.item.item_id == "s1"


def test_atom_outside_packet_is_rejected(
    build_state, small_bundle, small_brief, lookup_with_two_atoms
) -> None:
    """Cite a real packet but a foreign atom → BLOCKER PATH_LEGALITY."""
    state = build_state(
        {
            "scope_items": [
                _scope_item("s1", packets=("pkt_s1",), atoms=("a_alien",))
            ]
        }
    )
    validator = BrainOutputValidator(lookup=lookup_with_two_atoms)
    report = validator.validate_managed_services(
        state, brief=small_brief, bundle=small_bundle
    )

    iv = report.failed_items[0]
    rule_ids = {f.rule_id for f in iv.failures}
    assert ValidationRuleId.PATH_LEGALITY in rule_ids
    assert iv.has_blocker


def test_unresolvable_atom_is_warning(
    build_state, small_bundle, small_brief
) -> None:
    """Atom not in :class:`EvidenceLookup` → WARNING UNRESOLVED_ATOM (not blocker)."""
    state = build_state(
        {
            "scope_items": [
                _scope_item("s1", packets=("pkt_s1",), atoms=("a1",))
            ]
        }
    )
    # NullEvidenceLookup returns None for every atom.
    validator = BrainOutputValidator(lookup=NullEvidenceLookup())
    report = validator.validate_managed_services(
        state, brief=small_brief, bundle=small_bundle
    )
    iv = report.items[0]
    rule_ids = {f.rule_id for f in iv.failures}
    assert ValidationRuleId.UNRESOLVED_ATOM in rule_ids
    # WARNING means not a hard blocker, but the item is still 'not passed'
    # because passed = no non-INFO failures.
    assert not iv.passed
    assert not iv.has_blocker


def test_atom_without_locator_is_warning(
    build_state, small_bundle, small_brief
) -> None:
    """Atom present but no ``locator`` → WARNING MISSING_SOURCE_REF."""
    bare_lookup = DictEvidenceLookup(
        atoms={
            "a1": {"id": "a1", "text": "no locator", "verified": "verified", "locator": {}},
        }
    )
    state = build_state(
        {
            "scope_items": [
                _scope_item("s1", packets=("pkt_s1",), atoms=("a1",))
            ]
        }
    )
    validator = BrainOutputValidator(lookup=bare_lookup)
    report = validator.validate_managed_services(
        state, brief=small_brief, bundle=small_bundle
    )
    iv = report.items[0]
    rule_ids = {f.rule_id for f in iv.failures}
    assert ValidationRuleId.MISSING_SOURCE_REF in rule_ids


def test_well_grounded_item_passes(
    build_state, small_bundle, small_brief, lookup_with_two_atoms
) -> None:
    """Real packet + real atom + real locator → no failures, item passes."""
    state = build_state(
        {
            "scope_items": [
                _scope_item("s1", packets=("pkt_s1",), atoms=("a1",))
            ]
        }
    )
    validator = BrainOutputValidator(lookup=lookup_with_two_atoms)
    report = validator.validate_managed_services(
        state, brief=small_brief, bundle=small_bundle
    )
    assert report.failed_items == ()
    assert report.passed_items == report.items
    assert report.rule_counts() == {}
