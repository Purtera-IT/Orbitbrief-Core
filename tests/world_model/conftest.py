"""Fixtures shared by world_model tests.

The synthetic envelope helpers are kept here (not in the root
conftest) so they don't pollute the rest of the suite.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from orbitbrief_core.evidence_runtime.runtime import EvidenceRuntime


def _atom(
    atom_id: str,
    text: str,
    *,
    artifact_id: str = "art_1",
    atom_type: str = "scope_item",
    authority_class: str = "machine_extractor",
    confidence: float = 0.9,
) -> dict[str, Any]:
    return {
        "id": atom_id,
        "artifact_id": artifact_id,
        "atom_type": atom_type,
        "authority_class": authority_class,
        "confidence": confidence,
        "text": text,
        "section_path": [],
        "locator": {},
        "verified": "unverified",
    }


def _entity(
    entity_id: str,
    canonical_key: str,
    canonical_name: str,
    *,
    aliases: list[str] | None = None,
    source_atom_ids: list[str] | None = None,
    artifact_ids: list[str] | None = None,
    entity_type: str = "site",
) -> dict[str, Any]:
    return {
        "id": entity_id,
        "entity_type": entity_type,
        "canonical_key": canonical_key,
        "canonical_name": canonical_name,
        "aliases": aliases or [],
        "artifact_ids": artifact_ids or [],
        "source_atom_ids": source_atom_ids or [],
        "review_status": "auto_accepted",
        "confidence": 0.95,
    }


def _edge(
    edge_id: str,
    edge_type: str,
    from_id: str,
    to_id: str,
    *,
    confidence: float = 0.9,
) -> dict[str, Any]:
    return {
        "id": edge_id,
        "edge_type": edge_type,
        "from_atom_id": from_id,
        "to_atom_id": to_id,
        "reason": "test",
        "confidence": confidence,
        "cross_artifact": False,
        "metadata": {},
    }


def _envelope(
    atoms: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    project_id: str = "test_project",
    compile_id: str = "test_compile_001",
    documents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a minimal ``orbitbrief.input.v2`` envelope dict.

    Builds the ``atoms_by_entity_key`` index by inverting each
    entity's ``source_atom_ids`` — the engines use this index for
    O(1) site → atom lookups.
    """
    docs = documents or [
        {
            "artifact_id": "art_1",
            "filename": "test.pdf",
            "artifact_type": "pdf",
            "sha256": "0" * 64,
            "size_bytes": 1024,
            "parser_name": "test",
            "parser_version": "0.0.0",
            "structured": {},
            "atom_ids": [a["id"] for a in atoms],
        }
    ]
    atoms_by_entity_key: dict[str, list[str]] = {}
    for ent in entities:
        for aid in ent.get("source_atom_ids") or []:
            atoms_by_entity_key.setdefault(ent["canonical_key"], []).append(aid)
    for v in atoms_by_entity_key.values():
        v.sort()

    return {
        "schema_version": "orbitbrief.input.v2",
        "project_id": project_id,
        "compile_id": compile_id,
        "generated_at": "2026-01-01T00:00:00Z",
        "summary": {
            "artifact_count": len(docs),
            "page_count": 1,
            "atom_count": len(atoms),
            "packet_count": 0,
            "entity_count": len(entities),
            "edge_count": len(edges),
        },
        "documents": docs,
        "atoms": atoms,
        "entities": entities,
        "edges": edges,
        "packets": [],
        "indexes": {
            "atoms_by_section_path": {},
            "atoms_by_atom_type": {},
            "atoms_by_authority": {},
            "atoms_by_artifact": {
                docs[0]["artifact_id"]: sorted(a["id"] for a in atoms)
            },
            "atoms_by_entity_key": atoms_by_entity_key,
            "edges_by_atom": {},
            "entity_id_by_canonical_key": {
                e["canonical_key"]: e["id"] for e in entities
            },
        },
    }


@pytest.fixture
def wireless_envelope() -> dict[str, Any]:
    """A small envelope dominated by wireless / AP keywords."""
    atoms = [
        _atom(
            "a1",
            "Coverage and capacity AP install for the warehouse: mounting at "
            "ceiling height with predictive validation outputs.",
        ),
        _atom(
            "a2",
            "Survey scope includes RF obstacles and AP model assumptions for a "
            "remote predictive WSS engagement.",
        ),
        _atom(
            "a3",
            "Lift safety controls in place; mounting to deck per spec; install "
            "by others where noted.",
        ),
    ]
    return _envelope(atoms, entities=[], edges=[])


@pytest.fixture
def itad_envelope() -> dict[str, Any]:
    """Envelope dominated by ITAD chain-of-custody language."""
    atoms = [
        _atom(
            "a1",
            "Chain of custody from staging to sanitization with serial-level "
            "fidelity; certificate of destruction issued per asset.",
        ),
        _atom(
            "a2",
            "ITAD vendor will provide handoff and asset tag fidelity for all "
            "decommissioned hardware.",
        ),
    ]
    return _envelope(atoms, entities=[], edges=[])


@pytest.fixture
def three_site_envelope() -> dict[str, Any]:
    """Synthetic 3-site / 4-source envelope for site_reality clustering.

    * Building A appears in 2 artifacts under different aliases
      (linked by ``co_mention`` edges).
    * Building B is a single-source site.
    * Building C is named two different ways across two artifacts
      (no edges, but matching canonical_name string after normalization).
    """
    atoms = [
        _atom("a_a1", "Building A — main entrance scope.", artifact_id="src_pdf"),
        _atom("a_a2", "Bldg A: rear loading dock, badge access required.", artifact_id="src_xlsx"),
        _atom("a_b1", "Building B punch list items.", artifact_id="src_pdf"),
        _atom("a_c1", "Building C: north wing.", artifact_id="src_email"),
        _atom("a_c2", "Building C - North Wing extension scope.", artifact_id="src_transcript"),
    ]
    entities = [
        _entity(
            "e_a_pdf",
            "site:building_a",
            "Building A",
            aliases=["Bldg A"],
            source_atom_ids=["a_a1"],
            artifact_ids=["src_pdf"],
        ),
        _entity(
            "e_a_xlsx",
            "site:bldg_a_alt",
            "Building A",
            aliases=["Bldg A"],
            source_atom_ids=["a_a2"],
            artifact_ids=["src_xlsx"],
        ),
        _entity(
            "e_b",
            "site:building_b",
            "Building B",
            source_atom_ids=["a_b1"],
            artifact_ids=["src_pdf"],
        ),
        _entity(
            "e_c_email",
            "site:building_c",
            "Building C",
            source_atom_ids=["a_c1"],
            artifact_ids=["src_email"],
        ),
        _entity(
            "e_c_xscript",
            "site:building_c_alt",
            "Building C",
            source_atom_ids=["a_c2"],
            artifact_ids=["src_transcript"],
        ),
    ]
    # Explicit same_as edge bridges Bldg A's two keys across artifacts.
    edges = [_edge("ed_1", "same_as", "a_a1", "a_a2")]
    docs = [
        {
            "artifact_id": aid,
            "filename": f"{aid}.{ext}",
            "artifact_type": atype,
            "sha256": "0" * 64,
            "size_bytes": 1024,
            "parser_name": "test",
            "parser_version": "0.0.0",
            "structured": {},
            "atom_ids": sorted(a["id"] for a in atoms if a["artifact_id"] == aid),
        }
        for aid, ext, atype in [
            ("src_pdf", "pdf", "pdf"),
            ("src_xlsx", "xlsx", "xlsx"),
            ("src_email", "msg", "email"),
            ("src_transcript", "txt", "transcript"),
        ]
    ]
    env = _envelope(atoms, entities, edges, documents=docs)
    return env


@pytest.fixture
def runtime_from_envelope():
    """Factory: dict envelope → in-memory EvidenceRuntime, auto-closed."""
    runtimes: list[EvidenceRuntime] = []

    def _factory(env: dict[str, Any]) -> EvidenceRuntime:
        rt = EvidenceRuntime.from_envelope(env)
        runtimes.append(rt)
        return rt

    yield _factory
    for rt in runtimes:
        rt.close()
