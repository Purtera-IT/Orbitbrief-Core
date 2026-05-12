"""Phase-1A: end-to-end tests for the orbitbrief.input.v2 envelope consumer.

Three layers of coverage, in order of strictness:

1. **Schema invariants** — :class:`EnvelopeV2` rejects malformed
   payloads (wrong schema_version, missing required fields).
2. **Pydantic round-trip** — load a real envelope built by parser-os,
   pass it through ``EnvelopeV2`` and back to ``model_dump`` — the
   document/atom/edge/packet identity surfaces stay intact.
3. **Determinism** — the same envelope produces a byte-identical
   :class:`ConsumerSummary` across two runs.

We build the envelope from a tiny in-memory parser-os ``CompileResult``
so the test is self-contained and doesn't depend on fixture PDFs.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.orbitbrief_envelope import (
    ENVELOPE_SCHEMA_VERSION as PARSER_OS_SCHEMA_VERSION,
    build_orbitbrief_envelope,
)
from app.core.schemas import (
    ArtifactType,
    AtomType,
    AuthorityClass,
    CompileManifest,
    CompileResult,
    EvidenceAtom,
    ReviewStatus,
    SourceRef,
)

from orbitbrief_core.seam import (
    ENVELOPE_SCHEMA_VERSION,
    EnvelopeV2,
    consume_envelope,
    load_envelope,
    load_envelope_dict,
)
from orbitbrief_core.seam.loader import EnvelopeLoadError


PROJECT_ID = "phase1a_smoke"
COMPILE_ID = "cmp_phase1a_smoke"


# ────────────────────────────── fixtures ───────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _empty_manifest() -> CompileManifest:
    now = _now()
    return CompileManifest(
        compile_id=COMPILE_ID,
        project_id=PROJECT_ID,
        started_at=now,
        completed_at=now,
        deterministic_seed="phase1a",
        input_signature="phase1a:empty",
        output_signature="phase1a:empty",
    )


def _atom(
    *,
    atom_id: str,
    artifact_id: str = "art_phase1a",
    atom_type: AtomType = AtomType.scope_item,
    authority: AuthorityClass = AuthorityClass.contractual_scope,
    confidence: float = 0.9,
    text: str = "Sample atom text",
) -> EvidenceAtom:
    return EvidenceAtom(
        id=atom_id,
        project_id=PROJECT_ID,
        artifact_id=artifact_id,
        atom_type=atom_type,
        authority_class=authority,
        confidence=confidence,
        raw_text=text,
        normalized_text=text,
        value={"text": text},
        entity_keys=[],
        review_status=ReviewStatus.auto_accepted,
        parser_version="phase1a-1.0",
        source_refs=[
            SourceRef(
                id=f"src_{atom_id}",
                artifact_id=artifact_id,
                artifact_type=ArtifactType.txt,
                filename="phase1a.txt",
                locator={"line_start": 1, "line_end": 1},
                extraction_method="phase1a_test_fixture",
                parser_version="phase1a-1.0",
            )
        ],
    )


def _compile_result_with_atoms(*, atom_count: int = 3) -> CompileResult:
    atoms = [
        _atom(
            atom_id=f"atm_phase1a_{i:02d}",
            confidence=round(0.5 + (i * 0.1), 2),
            text=f"Atom number {i} talks about cameras at site {chr(65 + i)}",
        )
        for i in range(atom_count)
    ]
    return CompileResult(
        project_id=PROJECT_ID,
        compile_id=COMPILE_ID,
        atoms=atoms,
        entities=[],
        edges=[],
        packets=[],
        manifest=_empty_manifest(),
    )


@pytest.fixture
def envelope_dict(tmp_path: Path) -> dict[str, Any]:
    """A real envelope dict from parser-os, no fixture PDFs needed."""
    return build_orbitbrief_envelope(
        project_dir=tmp_path,
        compile_result=_compile_result_with_atoms(),
    )


# ────────────────────────────── 1. invariants ──────────────────────────


def test_schema_version_constant_pins_v2() -> None:
    """OrbitBrief and parser-os MUST agree on the schema string."""
    assert ENVELOPE_SCHEMA_VERSION == "orbitbrief.input.v2"
    assert ENVELOPE_SCHEMA_VERSION == PARSER_OS_SCHEMA_VERSION


def test_envelope_rejects_wrong_schema_version() -> None:
    """A v3 (or any non-v2) envelope must fail loud at the boundary."""
    with pytest.raises(ValidationError):
        EnvelopeV2.model_validate(
            {
                "schema_version": "orbitbrief.input.v3",
                "project_id": "x",
                "compile_id": "y",
                "generated_at": _now(),
                "summary": {
                    "artifact_count": 0,
                    "page_count": 0,
                    "atom_count": 0,
                    "packet_count": 0,
                },
            }
        )


def test_envelope_rejects_missing_required_field() -> None:
    """``project_id`` is required — omitting it must raise."""
    with pytest.raises(ValidationError):
        EnvelopeV2.model_validate(
            {
                "schema_version": "orbitbrief.input.v2",
                # project_id intentionally omitted
                "compile_id": "y",
                "generated_at": _now(),
                "summary": {
                    "artifact_count": 0,
                    "page_count": 0,
                    "atom_count": 0,
                    "packet_count": 0,
                },
            }
        )


def test_envelope_tolerates_unknown_top_level_field(envelope_dict: dict[str, Any]) -> None:
    """Forward-compat: a v2.1 producer adding extras must not break us."""
    payload = dict(envelope_dict)
    payload["future_only_field"] = {"hint": "added in a hypothetical v2.1"}
    envelope = EnvelopeV2.model_validate(payload)
    assert envelope.schema_version == "orbitbrief.input.v2"


# ────────────────────────────── 2. round-trip ──────────────────────────


def test_load_envelope_dict_roundtrips_atoms_and_documents(
    envelope_dict: dict[str, Any],
) -> None:
    """Atom/document IDs survive Pydantic round-trip without loss."""
    envelope = load_envelope_dict(envelope_dict)
    assert envelope.summary.atom_count == len(envelope_dict["atoms"])
    assert {a.id for a in envelope.atoms} == {a["id"] for a in envelope_dict["atoms"]}
    assert {d.artifact_id for d in envelope.documents} == {
        d["artifact_id"] for d in envelope_dict["documents"]
    }


def test_load_envelope_from_disk(tmp_path: Path, envelope_dict: dict[str, Any]) -> None:
    """The CLI path (file → EnvelopeV2) works end-to-end."""
    path = tmp_path / "orbitbrief.input.json"
    path.write_text(json.dumps(envelope_dict, indent=2), encoding="utf-8")
    envelope = load_envelope(path)
    assert envelope.schema_version == ENVELOPE_SCHEMA_VERSION
    assert envelope.project_id == PROJECT_ID


def test_load_envelope_missing_file_raises_typed_error(tmp_path: Path) -> None:
    with pytest.raises(EnvelopeLoadError, match="not found"):
        load_envelope(tmp_path / "does_not_exist.json")


def test_load_envelope_invalid_json_raises_typed_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not json {", encoding="utf-8")
    with pytest.raises(EnvelopeLoadError, match="not valid JSON"):
        load_envelope(bad)


def test_load_envelope_top_level_must_be_object(tmp_path: Path) -> None:
    bad = tmp_path / "list.json"
    bad.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(EnvelopeLoadError, match="must be a JSON object"):
        load_envelope(bad)


# ────────────────────────────── 3. determinism ─────────────────────────


def test_consume_envelope_is_deterministic(envelope_dict: dict[str, Any]) -> None:
    """Same envelope → byte-identical summary across re-runs.

    This is the contract Phase 2 retrieval / Phase 3 calibration
    depend on. If this regresses, we have non-determinism somewhere
    in the consumer pipeline.
    """
    envelope = load_envelope_dict(envelope_dict)
    summary_a = consume_envelope(envelope)
    summary_b = consume_envelope(envelope)

    json_a = summary_a.model_dump_json(indent=2)
    json_b = summary_b.model_dump_json(indent=2)
    assert json_a == json_b


def test_consume_envelope_basic_counts(envelope_dict: dict[str, Any]) -> None:
    """Sanity: counts in the summary match the envelope."""
    envelope = load_envelope_dict(envelope_dict)
    summary = consume_envelope(envelope)
    assert summary.schema_version == "orbitbrief.input.v2"
    assert summary.project_id == PROJECT_ID
    assert summary.compile_id == COMPILE_ID
    assert summary.atom_count == envelope.summary.atom_count
    assert summary.packet_count == envelope.summary.packet_count


def test_consume_envelope_top_atoms_are_confidence_sorted(
    envelope_dict: dict[str, Any],
) -> None:
    """Top-N atoms come back in descending confidence order."""
    envelope = load_envelope_dict(envelope_dict)
    summary = consume_envelope(envelope, top_n_atoms=10)
    confidences = [a.confidence for a in summary.top_atoms_by_confidence]
    assert confidences == sorted(confidences, reverse=True)


def test_consume_envelope_breakdowns_ordered_by_count_desc(
    envelope_dict: dict[str, Any],
) -> None:
    """``by_*`` dicts are sorted by ``(-count, key)`` for deterministic JSON."""
    envelope = load_envelope_dict(envelope_dict)
    summary = consume_envelope(envelope)
    counts = list(summary.by_atom_type.values())
    assert counts == sorted(counts, reverse=True)


def test_consume_envelope_verification_buckets_sum_to_atom_count(
    envelope_dict: dict[str, Any],
) -> None:
    """Every atom must be accounted for in exactly one verification bucket."""
    envelope = load_envelope_dict(envelope_dict)
    summary = consume_envelope(envelope)
    v = summary.verification
    assert (
        v.verified + v.failed + v.partial + v.unsupported + v.unverified
        == summary.atom_count
    )
