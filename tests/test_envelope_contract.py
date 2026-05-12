"""Phase-0 contract test for the parser-os ↔ OrbitBrief seam.

The ``orbitbrief.input.v2`` envelope is the *only* surface OrbitBrief is
allowed to consume from parser-os. This test pins three invariants:

1. The envelope builder is importable from parser-os under its public
   module path (``app.core.orbitbrief_envelope``). No reach into
   ``app.parsers.*`` or any other internal surface is needed.
2. The schema version constant resolves to ``orbitbrief.input.v2`` and
   the built envelope carries the same value. A bump here MUST be a
   conscious version change in parser-os.
3. The envelope JSON-round-trips losslessly: ``json.dumps`` followed by
   ``json.loads`` returns an equivalent dict. This is the bare minimum
   for safe transport across the seam (CLI hand-off, on-disk caches,
   network shipping, etc.).

If any of these assertions break, downstream OrbitBrief Core code can
silently corrupt or drop fields, so we fail loud here.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Public seam — only these top-level modules from parser-os are allowed.
from app.core.orbitbrief_envelope import (
    ENVELOPE_FILENAME,
    ENVELOPE_SCHEMA_VERSION,
    build_orbitbrief_envelope,
    write_orbitbrief_envelope,
)
from app.core.schemas import CompileManifest, CompileResult


EXPECTED_SCHEMA_VERSION = "orbitbrief.input.v2"


def _empty_manifest(project_id: str = "phase0_smoke") -> CompileManifest:
    """Smallest valid CompileManifest with no artifacts.

    Keeps the test self-contained — no fixture PDFs needed. The envelope
    builder must accept an empty manifest and emit a well-formed
    document with zero artifacts.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return CompileManifest(
        compile_id="cmp_phase0_smoke",
        project_id=project_id,
        started_at=now,
        completed_at=now,
        deterministic_seed="phase0",
        input_signature="phase0:empty",
        output_signature="phase0:empty",
    )


def _empty_compile_result(project_id: str = "phase0_smoke") -> CompileResult:
    return CompileResult(
        project_id=project_id,
        compile_id="cmp_phase0_smoke",
        atoms=[],
        entities=[],
        edges=[],
        packets=[],
        manifest=_empty_manifest(project_id=project_id),
    )


def test_envelope_schema_version_is_v2() -> None:
    """Module constant pins the wire format. Must be ``orbitbrief.input.v2``."""
    assert ENVELOPE_SCHEMA_VERSION == EXPECTED_SCHEMA_VERSION, (
        "Phase-0 contract: parser-os must ship the v2 envelope. "
        f"Got {ENVELOPE_SCHEMA_VERSION!r} — bump downstream consumers "
        "before changing this constant."
    )


def test_envelope_builds_from_minimal_compile_result(tmp_path: Path) -> None:
    """Build the envelope from an empty CompileResult and validate top-level shape."""
    compile_result = _empty_compile_result()
    envelope = build_orbitbrief_envelope(
        project_dir=tmp_path,
        compile_result=compile_result,
    )

    # Top-level keys are the public contract.
    required_keys = {
        "schema_version",
        "project_id",
        "compile_id",
        "generated_at",
        "summary",
        "documents",
        "atoms",
        "packets",
        "entities",
        "edges",
        "indexes",
    }
    missing = required_keys - envelope.keys()
    assert not missing, f"envelope missing required keys: {sorted(missing)}"

    assert envelope["schema_version"] == EXPECTED_SCHEMA_VERSION
    assert envelope["project_id"] == "phase0_smoke"
    assert envelope["compile_id"] == "cmp_phase0_smoke"
    # Empty manifest → empty collections.
    assert envelope["documents"] == []
    assert envelope["atoms"] == []
    assert envelope["packets"] == []


def test_envelope_round_trips_through_json(tmp_path: Path) -> None:
    """``json.dumps`` → ``json.loads`` must be lossless for the envelope."""
    compile_result = _empty_compile_result()
    envelope = build_orbitbrief_envelope(
        project_dir=tmp_path,
        compile_result=compile_result,
    )

    serialized = json.dumps(envelope, ensure_ascii=False, sort_keys=True)
    restored = json.loads(serialized)

    assert restored == envelope, "envelope JSON round-trip lost or mutated fields"
    assert restored["schema_version"] == EXPECTED_SCHEMA_VERSION


def test_write_envelope_emits_named_artifact(tmp_path: Path) -> None:
    """``write_orbitbrief_envelope`` writes the canonical JSON filename."""
    compile_result = _empty_compile_result()
    envelope = build_orbitbrief_envelope(
        project_dir=tmp_path,
        compile_result=compile_result,
    )

    out_dir = tmp_path / "envelope_out"
    json_path, md_path = write_orbitbrief_envelope(
        project_dir=tmp_path,
        envelope=envelope,
        out_dir=out_dir,
    )

    assert json_path.name == ENVELOPE_FILENAME
    assert json_path.is_file()
    assert md_path.is_file()

    on_disk = json.loads(json_path.read_text(encoding="utf-8"))
    assert on_disk["schema_version"] == EXPECTED_SCHEMA_VERSION
    assert on_disk == envelope


def test_orbitbrief_core_does_not_import_parser_internals() -> None:
    """Belt-and-suspenders for the import-linter contract.

    A direct import of ``app.parsers`` from inside an ``orbitbrief_core``
    module would be a Phase-0 violation. We assert the policy here so the
    suite fails loud even if ``lint-imports`` is skipped in CI.
    """
    forbidden_prefixes = ("app.parsers", "app.segmentation")
    import importlib
    import pkgutil

    pkg = importlib.import_module("orbitbrief_core")
    bad: list[tuple[str, str]] = []
    for module_info in pkgutil.walk_packages(pkg.__path__, prefix="orbitbrief_core."):
        try:
            mod = importlib.import_module(module_info.name)
        except Exception:  # noqa: BLE001 — best-effort scan
            continue
        for attr in dir(mod):
            value = getattr(mod, attr, None)
            mod_name = getattr(value, "__module__", "") or ""
            for forbidden in forbidden_prefixes:
                if mod_name.startswith(forbidden):
                    bad.append((module_info.name, mod_name))

    assert not bad, (
        "OrbitBrief modules referenced parser-os internals: "
        + ", ".join(f"{a} -> {b}" for a, b in bad)
    )


if __name__ == "__main__":  # pragma: no cover — manual smoke
    pytest.main([__file__, "-v"])
