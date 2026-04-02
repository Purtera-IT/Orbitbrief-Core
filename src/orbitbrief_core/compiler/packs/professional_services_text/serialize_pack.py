from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from orbitbrief_core.compiler.packs.professional_services_text.compile_allowed_masks import (
    to_jsonable_diagnostic as masks_to_jsonable_diagnostic,
    to_jsonable_mask,
    to_jsonable_summary as masks_to_jsonable_summary,
)
from orbitbrief_core.compiler.packs.professional_services_text.compile_claim_family_table import (
    to_jsonable_diagnostic as claim_to_jsonable_diagnostic,
    to_jsonable_row as claim_to_jsonable_row,
    to_jsonable_summary as claim_to_jsonable_summary,
)
from orbitbrief_core.compiler.packs.professional_services_text.compile_field_table import (
    to_jsonable_diagnostic as field_to_jsonable_diagnostic,
    to_jsonable_row as field_to_jsonable_row,
    to_jsonable_summary as field_to_jsonable_summary,
)
from orbitbrief_core.compiler.packs.professional_services_text.compile_negative_examples import (
    to_jsonable_diagnostic as negative_to_jsonable_diagnostic,
    to_jsonable_row as negative_to_jsonable_row,
    to_jsonable_summary as negative_to_jsonable_summary,
)
from orbitbrief_core.compiler.packs.professional_services_text.compile_parser_profile_table import (
    to_jsonable_diagnostic as parser_to_jsonable_diagnostic,
    to_jsonable_row as parser_to_jsonable_row,
    to_jsonable_summary as parser_to_jsonable_summary,
)
from orbitbrief_core.compiler.packs.professional_services_text.compile_projection_rule_table import (
    to_jsonable_diagnostic as projection_to_jsonable_diagnostic,
    to_jsonable_row as projection_to_jsonable_row,
    to_jsonable_summary as projection_to_jsonable_summary,
)
from orbitbrief_core.compiler.packs.professional_services_text.compile_retrieval_exemplars import (
    to_jsonable_diagnostic as retrieval_to_jsonable_diagnostic,
    to_jsonable_row as retrieval_to_jsonable_row,
    to_jsonable_summary as retrieval_to_jsonable_summary,
)
from orbitbrief_core.compiler.packs.professional_services_text.compile_review_rule_table import (
    to_jsonable_diagnostic as review_to_jsonable_diagnostic,
    to_jsonable_row as review_to_jsonable_row,
    to_jsonable_summary as review_to_jsonable_summary,
)


@dataclass(frozen=True)
class ArtifactDescriptor:
    artifact_name: str
    filename: str
    row_count: int
    sha256: str


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_dump(path: Path, payload: Mapping[str, Any]) -> str:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return _sha256_file(path)


def _artifact_envelope(
    *,
    artifact_name: str,
    pack_id: str,
    compiler_version: str,
    rows: Sequence[Any],
    summary: Any,
    diagnostics: Sequence[Any],
    row_serializer: Callable[[Any], dict[str, Any]],
    summary_serializer: Callable[[Any], dict[str, Any]],
    diagnostic_serializer: Callable[[Any], dict[str, Any]],
) -> dict[str, Any]:
    stable_rows = [row_serializer(row) for row in rows]
    return {
        "artifact_name": artifact_name,
        "pack_id": pack_id,
        "compiler_version": compiler_version,
        "row_count": len(stable_rows),
        "rows": stable_rows,
        "summary": summary_serializer(summary),
        "diagnostics": [diagnostic_serializer(diag) for diag in diagnostics],
    }


def write_compiled_pack(
    artifacts: Any,
    *,
    compiled_root: Path,
    pack_version: str = "v1",
    schema_version: str = "1",
    runtime_compat_version: str = "1",
) -> Path:
    pack_id = artifacts.ir.manifest.pack_id
    compiler_version = artifacts.ir.manifest.compiler_version
    out_dir = compiled_root / pack_id / pack_version
    out_dir.mkdir(parents=True, exist_ok=True)

    descriptors: dict[str, ArtifactDescriptor] = {}

    def write_artifact(logical_name: str, filename: str, payload: dict[str, Any]) -> None:
        artifact_path = out_dir / filename
        sha = _json_dump(artifact_path, payload)
        descriptors[logical_name] = ArtifactDescriptor(
            artifact_name=logical_name,
            filename=filename,
            row_count=int(payload["row_count"]),
            sha256=sha,
        )

    write_artifact(
        "field_table",
        "field_table.json",
        _artifact_envelope(
            artifact_name="field_table",
            pack_id=pack_id,
            compiler_version=compiler_version,
            rows=artifacts.field_table.rows,
            summary=artifacts.field_table.summary,
            diagnostics=artifacts.field_table.diagnostics,
            row_serializer=field_to_jsonable_row,
            summary_serializer=field_to_jsonable_summary,
            diagnostic_serializer=field_to_jsonable_diagnostic,
        ),
    )
    write_artifact(
        "claim_family_table",
        "claim_family_table.json",
        _artifact_envelope(
            artifact_name="claim_family_table",
            pack_id=pack_id,
            compiler_version=compiler_version,
            rows=artifacts.claim_family_table.rows,
            summary=artifacts.claim_family_table.summary,
            diagnostics=artifacts.claim_family_table.diagnostics,
            row_serializer=claim_to_jsonable_row,
            summary_serializer=claim_to_jsonable_summary,
            diagnostic_serializer=claim_to_jsonable_diagnostic,
        ),
    )
    write_artifact(
        "review_rules",
        "review_rules.json",
        _artifact_envelope(
            artifact_name="review_rules",
            pack_id=pack_id,
            compiler_version=compiler_version,
            rows=artifacts.review_rule_table.rows,
            summary=artifacts.review_rule_table.summary,
            diagnostics=artifacts.review_rule_table.diagnostics,
            row_serializer=review_to_jsonable_row,
            summary_serializer=review_to_jsonable_summary,
            diagnostic_serializer=review_to_jsonable_diagnostic,
        ),
    )
    write_artifact(
        "projection_rules",
        "projection_rules.json",
        _artifact_envelope(
            artifact_name="projection_rules",
            pack_id=pack_id,
            compiler_version=compiler_version,
            rows=artifacts.projection_rule_table.rows,
            summary=artifacts.projection_rule_table.summary,
            diagnostics=artifacts.projection_rule_table.diagnostics,
            row_serializer=projection_to_jsonable_row,
            summary_serializer=projection_to_jsonable_summary,
            diagnostic_serializer=projection_to_jsonable_diagnostic,
        ),
    )
    write_artifact(
        "allowed_field_masks",
        "allowed_field_masks.json",
        _artifact_envelope(
            artifact_name="allowed_field_masks",
            pack_id=pack_id,
            compiler_version=compiler_version,
            rows=artifacts.allowed_masks.masks,
            summary=artifacts.allowed_masks.summary,
            diagnostics=artifacts.allowed_masks.diagnostics,
            row_serializer=to_jsonable_mask,
            summary_serializer=masks_to_jsonable_summary,
            diagnostic_serializer=masks_to_jsonable_diagnostic,
        ),
    )
    write_artifact(
        "parser_profiles",
        "parser_profiles.json",
        _artifact_envelope(
            artifact_name="parser_profiles",
            pack_id=pack_id,
            compiler_version=compiler_version,
            rows=artifacts.parser_profiles.rows,
            summary=artifacts.parser_profiles.summary,
            diagnostics=artifacts.parser_profiles.diagnostics,
            row_serializer=parser_to_jsonable_row,
            summary_serializer=parser_to_jsonable_summary,
            diagnostic_serializer=parser_to_jsonable_diagnostic,
        ),
    )
    write_artifact(
        "negative_examples",
        "negative_examples.json",
        _artifact_envelope(
            artifact_name="negative_examples",
            pack_id=pack_id,
            compiler_version=compiler_version,
            rows=artifacts.negative_examples.rows,
            summary=artifacts.negative_examples.summary,
            diagnostics=artifacts.negative_examples.diagnostics,
            row_serializer=negative_to_jsonable_row,
            summary_serializer=negative_to_jsonable_summary,
            diagnostic_serializer=negative_to_jsonable_diagnostic,
        ),
    )
    write_artifact(
        "retrieval_exemplars",
        "retrieval_exemplars.json",
        _artifact_envelope(
            artifact_name="retrieval_exemplars",
            pack_id=pack_id,
            compiler_version=compiler_version,
            rows=artifacts.retrieval_exemplars.rows,
            summary=artifacts.retrieval_exemplars.summary,
            diagnostics=artifacts.retrieval_exemplars.diagnostics,
            row_serializer=retrieval_to_jsonable_row,
            summary_serializer=retrieval_to_jsonable_summary,
            diagnostic_serializer=retrieval_to_jsonable_diagnostic,
        ),
    )

    diagnostics_payload = {
        "artifact_name": "build_diagnostics",
        "pack_id": pack_id,
        "compiler_version": compiler_version,
        "row_count": len(artifacts.ir.diagnostics),
        "rows": [
            {
                "level": d.level,
                "code": d.code,
                "message": d.message,
                "concern": d.concern,
                "context": dict(d.context) if isinstance(d.context, Mapping) else {},
            }
            for d in artifacts.ir.diagnostics
        ],
    }
    diagnostics_file = "diagnostics.json"
    _json_dump(out_dir / diagnostics_file, diagnostics_payload)

    discourse_profiles: set[str] = set()
    for row in artifacts.negative_examples.rows:
        discourse_profiles.update(row.discourse_profiles)
    for row in artifacts.retrieval_exemplars.rows:
        discourse_profiles.update(row.discourse_profiles)

    source_paths: list[str] = sorted({str(path.resolve()) for path in artifacts.contract_input_paths})
    source_hashes: dict[str, str] = {}
    for src in artifacts.contract_input_paths:
        if src.exists() and src.is_file():
            source_hashes[str(src.resolve())] = _sha256_file(src)

    capabilities = {
        "projection_rules_supported": True,
        "projection_rules_present": bool(artifacts.projection_rule_table.rows),
        "strict_mask_alignment_enforced": bool(getattr(artifacts, "strict_mask_alignment_enforced", True)),
    }

    manifest_payload: dict[str, Any] = {
        "pack_id": pack_id,
        "artifact_family": artifacts.ir.manifest.artifact_family,
        "role_id": artifacts.ir.manifest.role_id,
        "pack_version": pack_version,
        "compiler_version": compiler_version,
        "schema_version": schema_version,
        "runtime_compat_version": runtime_compat_version,
        "generated_at": datetime.now(UTC).isoformat(),
        "modalities": list(artifacts.ir.manifest.admitted_modalities),
        "discourse_profiles": sorted(discourse_profiles),
        "source_paths": source_paths,
        "source_hashes": source_hashes,
        "capabilities": capabilities,
        "artifacts": {
            key: {
                "filename": desc.filename,
                "row_count": desc.row_count,
                "sha256": desc.sha256,
            }
            for key, desc in sorted(descriptors.items())
        },
        "diagnostics_file": diagnostics_file,
    }
    manifest_path = out_dir / "manifest.json"
    _json_dump(manifest_path, manifest_payload)
    return manifest_path


def load_serialized_pack(pack_id: str, *, compiled_root: Path, pack_version: str = "v1") -> dict[str, Any]:
    pack_dir = compiled_root / pack_id / pack_version
    manifest_path = pack_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Compiled pack manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    loaded_artifacts: dict[str, Any] = {}
    for artifact_name, descriptor in manifest.get("artifacts", {}).items():
        artifact_file = descriptor.get("filename")
        if not artifact_file:
            continue
        artifact_path = pack_dir / str(artifact_file)
        if not artifact_path.exists():
            raise FileNotFoundError(f"Compiled artifact missing: {artifact_path}")
        loaded_artifacts[artifact_name] = json.loads(artifact_path.read_text(encoding="utf-8"))
    diagnostics_file = manifest.get("diagnostics_file")
    diagnostics_payload = None
    if isinstance(diagnostics_file, str):
        diag_path = pack_dir / diagnostics_file
        if diag_path.exists():
            diagnostics_payload = json.loads(diag_path.read_text(encoding="utf-8"))
    return {
        "manifest": manifest,
        "artifacts": loaded_artifacts,
        "diagnostics": diagnostics_payload,
    }
