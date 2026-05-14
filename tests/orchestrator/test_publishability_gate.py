"""PR14 — replay verified states + do-not-publish flags hard gate."""
from __future__ import annotations

from orbitbrief_core.orchestrator.bundle_assembler import (
    _atom_is_publishable,
    _DO_NOT_PUBLISH_FLAGS,
    _PUBLISHABLE_VERIFIED_STATES,
)


def test_no_atom_is_none_safe():
    assert _atom_is_publishable(None) is False


def test_atom_with_no_verified_field_is_publishable():
    """Back-compat: envelopes from before the verifier ran default
    to publishable."""
    assert _atom_is_publishable({"id": "a"}) is True


def test_verified_atom_publishable():
    for state in _PUBLISHABLE_VERIFIED_STATES:
        assert _atom_is_publishable({"id": "a", "verified": state}) is True, state


def test_failed_replay_blocks_publication():
    assert _atom_is_publishable({"id": "a", "verified": "failed"}) is False
    assert _atom_is_publishable({"id": "a", "verified": "unsupported"}) is False
    assert _atom_is_publishable({"id": "a", "verified": "unverified"}) is False


def test_do_not_publish_flag_blocks_even_when_verified():
    """A flagged atom (visual review marker, ambiguous unchecked
    checkbox) is non-publishable even if its verified state is
    'verified'."""
    for flag in _DO_NOT_PUBLISH_FLAGS:
        atom = {
            "id": "a",
            "verified": "verified",
            "review_flags": [flag],
        }
        assert _atom_is_publishable(atom) is False, flag


def test_unflagged_verified_passes():
    atom = {"id": "a", "verified": "verified", "review_flags": []}
    assert _atom_is_publishable(atom) is True
