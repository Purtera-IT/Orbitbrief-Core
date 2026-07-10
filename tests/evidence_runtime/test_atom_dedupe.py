"""Duplicate atom ids in an envelope must not hard-fail DuckDB ingest."""

from __future__ import annotations

from orbitbrief_core.evidence_runtime.store import EnvelopeKey, EvidenceStore


def _minimal_envelope(*, atom_ids: list[str]) -> dict:
    atoms = [
        {
            "id": aid,
            "artifact_id": "art_1",
            "atom_type": "bom_line",
            "authority_class": "customer",
            "confidence": 0.9,
            "text": f"atom {aid}",
            "section_path": [],
            "locator": {},
            "verified": "unverified",
        }
        for aid in atom_ids
    ]
    return {
        "schema_version": "orbitbrief.input.v2",
        "project_id": "proj_dup",
        "compile_id": "compile_dup",
        "atoms": atoms,
        "documents": [],
        "entities": [],
        "edges": [],
        "packets": [],
        "indexes": {},
        "summary": {
            "artifact_count": 1,
            "page_count": 1,
            "atom_count": len(atoms),
            "packet_count": 0,
        },
    }


def test_duplicate_atom_ids_are_skipped_on_ingest() -> None:
    store = EvidenceStore.connect()
    # Same atom id twice — previously raised duckdb.ConstraintException.
    key = store.ingest_envelope(_minimal_envelope(atom_ids=["atm_a", "atm_a", "atm_b"]))
    assert isinstance(key, EnvelopeKey)
    assert store.fetch_atom(key, "atm_a") is not None
    assert store.fetch_atom(key, "atm_b") is not None
    count = store.connection.execute(
        "SELECT COUNT(*) FROM atoms WHERE project_id=? AND compile_id=?",
        [key.project_id, key.compile_id],
    ).fetchone()[0]
    assert count == 2
