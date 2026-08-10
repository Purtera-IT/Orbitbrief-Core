"""Never hand the model a field its own schema will reject.

`SiteSummary` is declared `extra="forbid"`. The snapshot used to offer four
fields that violate it — `candidate_names`, `site_keys`, `member_atom_ids`,
`artifact_ids` — and on Clayton (437 site clusters) the model returned exactly
those and omitted `cluster_id`, i.e. it echoed its input instead of
transforming it. Validation rejected the lot: 42,773 characters, 670 seconds,
discarded for a deterministic skeleton of 32 sites and zero claims.

The invariant is structural, not stylistic: a field the model can see is a
field a weak model may copy, so the snapshot must be a subset of what the
schema permits back.
"""
from __future__ import annotations

import inspect

from orbitbrief_core.world_model.planner import prompt as prompt_mod
from orbitbrief_core.world_model.planner.schema import SiteSummary

# Fields the model is asked to CREATE rather than copy; their absence from the
# snapshot is the point of the exercise.
_MODEL_AUTHORED = {"role", "depends_on_cluster_ids"}


def _snapshot_site_keys() -> set[str]:
    """The literal dict keys the prompt builds for each site cluster."""
    src = inspect.getsource(prompt_mod)
    start = src.index("    sites = [")
    end = src.index("]", src.index("for c in inputs.site_reality.clusters", start))
    block = src[start:end]
    return {
        line.split('"')[1]
        for line in block.splitlines()
        if line.strip().startswith('"') and ":" in line
    }


def test_snapshot_offers_no_field_the_schema_forbids():
    permitted = set(SiteSummary.model_fields)
    offered = _snapshot_site_keys()
    assert offered <= permitted, (
        "prompt offers fields SiteSummary will reject: "
        + ", ".join(sorted(offered - permitted))
    )


def test_the_four_echo_fields_are_gone():
    """Named explicitly so a future edit re-adding one fails loudly rather than
    silently reintroducing an eleven-minute discarded call."""
    offered = _snapshot_site_keys()
    for field in ("candidate_names", "site_keys", "member_atom_ids", "artifact_ids"):
        assert field not in offered, f"{field} is back in the planner snapshot"


def test_cluster_id_is_still_offered():
    """It is `Field(min_length=1)` and required — the model copies it rather
    than inventing it, so it must be visible."""
    assert "cluster_id" in _snapshot_site_keys()


def test_model_authored_fields_are_not_pre_filled():
    """Handing the model `role` would invite it to echo one rather than decide."""
    assert not (_snapshot_site_keys() & _MODEL_AUTHORED)
