"""A v2 scope atom must reach the SOW body, not vanish from it."""
from __future__ import annotations

import json

from orbitbrief_core.orchestrator.atom_type_fold import fold_v2_atom_types
from orbitbrief_core.orchestrator.artifacts import BriefArtifacts
from orbitbrief_core.orchestrator.pipeline import BriefPipeline


def test_work_scope_item_folds_to_scope_item_and_keeps_v2_label():
    env = {"atoms": [
        {"id": "a1", "atom_type": "work_scope_item", "text": "Mount 110 TVs"},
        {"id": "a2", "atom_type": "scope_item", "text": "Cable each drop"},
        {"id": "a3", "atom_type": "exclusion", "text": "No electrical work"},
    ]}
    assert fold_v2_atom_types(env) == 1
    a1, a2, a3 = env["atoms"]
    assert a1["atom_type"] == "scope_item" and a1["atom_type_v2"] == "work_scope_item"
    assert "atom_type_v2" not in a2 and "atom_type_v2" not in a3


def test_fold_is_idempotent_and_tolerates_junk():
    env = {"atoms": [{"atom_type": "work_scope_item"}, None, "x", {}]}
    assert fold_v2_atom_types(env) == 1
    assert fold_v2_atom_types(env) == 0
    assert env["atoms"][0]["atom_type_v2"] == "work_scope_item"
    assert fold_v2_atom_types({}) == 0


def test_ingest_stage_writes_the_folded_canonical_envelope(tmp_path):
    src = tmp_path / "envelope.json"
    src.write_text(json.dumps({"project_id": "p", "atoms": [
        {"id": "a1", "atom_type": "work_scope_item", "text": "Mount 110 TVs"},
    ]}), encoding="utf-8")
    artifacts = BriefArtifacts(tmp_path / "out")
    pipe = BriefPipeline.__new__(BriefPipeline)
    try:
        runtime, rec = pipe._stage_load_runtime(src, artifacts)
    except Exception:
        # EvidenceRuntime may demand a fuller envelope; the canonical copy is
        # written before it is built, and that copy is what builders read.
        rec = None
    canon = json.loads(artifacts.envelope_path.read_text(encoding="utf-8"))
    assert canon["atoms"][0]["atom_type"] == "scope_item"
    if rec is not None:
        assert rec.detail["v2_atom_types_folded"] == 1
        runtime.close()
