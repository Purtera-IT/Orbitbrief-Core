"""Fixtures for the orchestrator tests.

The orchestrator integrates every layer; these fixtures build a
single coherent envelope that exercises pack_prior + site_reality +
planner + brain + validator + calibrator without needing a real
parser-os compile.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


def _atom(
    aid: str,
    text: str,
    *,
    artifact: str = "art",
    atype: str = "scope_item",
    auth: str = "machine_extractor",
    confidence: float = 0.9,
) -> dict[str, Any]:
    return {
        "id": aid,
        "artifact_id": artifact,
        "atom_type": atype,
        "authority_class": auth,
        "confidence": confidence,
        "text": text,
        "section_path": [],
        "locator": {"page": 1, "section": "Scope"},
        "verified": "verified",
    }


def _packet(pid: str, family: str, *, anchor: str, atoms: tuple[str, ...]) -> dict[str, Any]:
    return {
        "id": pid,
        "family": family,
        "anchor_type": "generic",
        "anchor_key": anchor,
        "status": "active",
        "confidence": 0.9,
        "governing_atom_ids": list(atoms),
        "supporting_atom_ids": [],
        "contradicting_atom_ids": [],
        "reason": "synthetic",
    }


def _entity(eid: str, key: str, name: str, *, atoms: tuple[str, ...]) -> dict[str, Any]:
    return {
        "id": eid,
        "entity_type": "site" if key.startswith("site:") else "thing",
        "canonical_key": key,
        "canonical_name": name,
        "aliases": [],
        "artifact_ids": ["art"],
        "source_atom_ids": list(atoms),
        "review_status": "auto_accepted",
        "confidence": 0.9,
    }


@pytest.fixture
def msp_envelope_dict() -> dict[str, Any]:
    """A self-contained envelope dominated by MSP-flavored atoms + packets."""
    atoms = [
        _atom("a1", "24x7 endpoint monitoring across 220 devices managed by msp."),
        _atom("a2", "Monthly OS and third-party patching with reboot windows."),
        _atom("a3", "Hardware replacement and warranty handling out of scope."),
        _atom("a4", "Customer to designate change-approval contact within 5 business days."),
        _atom("a5", "Dispatch to HQ requires badge approval and 48-hour lead time."),
        _atom("a6", "Endpoint logs satisfy HIPAA retention (6 years)."),
    ]
    packets = [
        _packet("pkt_s1", "scope_inclusion", anchor="endpoint_monitoring", atoms=("a1",)),
        _packet("pkt_s2", "scope_inclusion", anchor="patching", atoms=("a2",)),
        _packet("pkt_x1", "scope_exclusion", anchor="hw_replacement", atoms=("a3",)),
        _packet("pkt_c1", "customer_override", anchor="approver", atoms=("a4",)),
        _packet("pkt_site1", "site_access", anchor="hq_dispatch", atoms=("a5",)),
        _packet("pkt_compl1", "compliance_clause", anchor="hipaa", atoms=("a6",)),
    ]
    entities = [
        _entity("e_site_hq", "site:hq", "HQ", atoms=("a1", "a5")),
    ]
    return {
        "schema_version": "orbitbrief.input.v2",
        "project_id": "msp_orchestrator_smoke",
        "compile_id": "compile_001",
        "generated_at": "2026-01-01T00:00:00Z",
        "summary": {
            "artifact_count": 1,
            "page_count": 1,
            "atom_count": len(atoms),
            "packet_count": len(packets),
            "entity_count": len(entities),
            "edge_count": 0,
        },
        "documents": [
            {
                "artifact_id": "art",
                "filename": "msp_engagement.pdf",
                "artifact_type": "pdf",
                "sha256": "0" * 64,
                "size_bytes": 1024,
                "parser_name": "test",
                "parser_version": "0.0.0",
                "structured": {},
                "atom_ids": [a["id"] for a in atoms],
            }
        ],
        "atoms": atoms,
        "entities": entities,
        "edges": [],
        "packets": packets,
        "indexes": {
            "atoms_by_section_path": {},
            "atoms_by_atom_type": {},
            "atoms_by_authority": {},
            "atoms_by_artifact": {"art": [a["id"] for a in atoms]},
            "atoms_by_entity_key": {"site:hq": ["a1", "a5"]},
            "edges_by_atom": {},
            "entity_id_by_canonical_key": {"site:hq": "e_site_hq"},
        },
    }


@pytest.fixture
def msp_envelope_path(tmp_path: Path, msp_envelope_dict: dict[str, Any]) -> Path:
    p = tmp_path / "envelope.json"
    p.write_text(json.dumps(msp_envelope_dict, indent=2), encoding="utf-8")
    return p
