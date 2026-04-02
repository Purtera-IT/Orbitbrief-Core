from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from orbitbrief_core.compiler.core.load_contracts import ContractLoadError

REQUIRED_ARTIFACTS: tuple[str, ...] = (
    "field_table",
    "claim_family_table",
    "review_rules",
    "projection_rules",
    "allowed_field_masks",
    "parser_profiles",
    "negative_examples",
    "retrieval_exemplars",
)


@dataclass(frozen=True)
class ArtifactDescriptor:
    filename: str
    row_count: int
    sha256: str


@dataclass(frozen=True)
class PackManifest:
    pack_id: str
    artifact_family: str
    role_id: str
    pack_version: str
    compiler_version: str
    schema_version: str
    runtime_compat_version: str
    generated_at: str
    modalities: tuple[str, ...]
    discourse_profiles: tuple[str, ...]
    source_paths: tuple[str, ...]
    source_hashes: Mapping[str, str]
    capabilities: Mapping[str, Any]
    artifacts: Mapping[str, ArtifactDescriptor]
    diagnostics_file: str | None = None


@dataclass(frozen=True)
class CompiledPack:
    manifest: PackManifest
    field_table: Mapping[str, Any]
    claim_family_table: Mapping[str, Any]
    review_rules: Mapping[str, Any]
    projection_rules: Mapping[str, Any]
    allowed_field_masks: Mapping[str, Any]
    parser_profiles: Mapping[str, Any]
    negative_examples: Mapping[str, Any]
    retrieval_exemplars: Mapping[str, Any]
    diagnostics: Mapping[str, Any] | None
    warnings: tuple[str, ...]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> Mapping[str, Any]:
    if not path.exists() or not path.is_file():
        raise ContractLoadError(f"Expected JSON file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ContractLoadError(f"Expected top-level mapping in {path}, got {type(data).__name__}")
    return data


def _parse_manifest(manifest_data: Mapping[str, Any], expected_pack_id: str) -> PackManifest:
    required = (
        "pack_id",
        "artifact_family",
        "role_id",
        "pack_version",
        "compiler_version",
        "schema_version",
        "runtime_compat_version",
        "generated_at",
        "modalities",
        "discourse_profiles",
        "source_paths",
        "source_hashes",
        "artifacts",
    )
    missing = [key for key in required if key not in manifest_data]
    if missing:
        raise ContractLoadError(f"Manifest is missing required keys: {missing}")
    pack_id = str(manifest_data["pack_id"])
    if pack_id != expected_pack_id:
        raise ContractLoadError(
            f"Manifest pack_id '{pack_id}' does not match requested pack_id '{expected_pack_id}'."
        )
    artifacts_raw = manifest_data["artifacts"]
    if not isinstance(artifacts_raw, Mapping):
        raise ContractLoadError("Manifest artifacts entry must be a mapping.")
    descriptors: dict[str, ArtifactDescriptor] = {}
    for name in REQUIRED_ARTIFACTS:
        raw = artifacts_raw.get(name)
        if not isinstance(raw, Mapping):
            raise ContractLoadError(f"Manifest missing required artifact descriptor: {name}")
        filename = raw.get("filename")
        row_count = raw.get("row_count")
        sha256 = raw.get("sha256")
        if not isinstance(filename, str) or not isinstance(row_count, int) or not isinstance(sha256, str):
            raise ContractLoadError(f"Invalid descriptor for artifact {name}")
        descriptors[name] = ArtifactDescriptor(filename=filename, row_count=row_count, sha256=sha256)

    source_hashes_raw = manifest_data["source_hashes"]
    if not isinstance(source_hashes_raw, Mapping):
        raise ContractLoadError("Manifest source_hashes must be a mapping")
    source_hashes = {str(k): str(v) for k, v in source_hashes_raw.items()}
    capabilities_raw = manifest_data.get("capabilities")
    capabilities = capabilities_raw if isinstance(capabilities_raw, Mapping) else {}

    modalities = tuple(sorted(str(v) for v in manifest_data["modalities"]))
    discourse_profiles = tuple(sorted(str(v) for v in manifest_data["discourse_profiles"]))
    source_paths = tuple(sorted(str(v) for v in manifest_data["source_paths"]))
    return PackManifest(
        pack_id=pack_id,
        artifact_family=str(manifest_data["artifact_family"]),
        role_id=str(manifest_data["role_id"]),
        pack_version=str(manifest_data["pack_version"]),
        compiler_version=str(manifest_data["compiler_version"]),
        schema_version=str(manifest_data["schema_version"]),
        runtime_compat_version=str(manifest_data["runtime_compat_version"]),
        generated_at=str(manifest_data["generated_at"]),
        modalities=modalities,
        discourse_profiles=discourse_profiles,
        source_paths=source_paths,
        source_hashes=MappingProxyType(source_hashes),
        capabilities=MappingProxyType({str(k): v for k, v in capabilities.items()}),
        artifacts=MappingProxyType(descriptors),
        diagnostics_file=(
            str(manifest_data["diagnostics_file"])
            if isinstance(manifest_data.get("diagnostics_file"), str)
            else None
        ),
    )


def _load_artifact(
    pack_dir: Path,
    *,
    artifact_name: str,
    descriptor: ArtifactDescriptor,
) -> Mapping[str, Any]:
    artifact_path = pack_dir / descriptor.filename
    payload = _read_json(artifact_path)
    if payload.get("artifact_name") != artifact_name:
        raise ContractLoadError(
            f"Artifact name mismatch for {artifact_name}: got {payload.get('artifact_name')!r}"
        )
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ContractLoadError(f"Artifact {artifact_name} must include list 'rows'")
    if len(rows) != descriptor.row_count:
        raise ContractLoadError(
            f"Artifact row_count mismatch for {artifact_name}: "
            f"manifest={descriptor.row_count}, actual={len(rows)}"
        )
    actual_sha = _sha256_file(artifact_path)
    if actual_sha != descriptor.sha256:
        raise ContractLoadError(
            f"Artifact hash mismatch for {artifact_name}: manifest={descriptor.sha256}, actual={actual_sha}"
        )
    return payload


def _unique(rows: list[Mapping[str, Any]], id_key: str, label: str) -> None:
    ids = [str(row.get(id_key, "")) for row in rows]
    if any(not id_value for id_value in ids):
        raise ContractLoadError(f"{label} rows contain empty {id_key}")
    if len(ids) != len(set(ids)):
        raise ContractLoadError(f"{label} rows contain duplicate {id_key}")


def _validate_cross_artifact(
    manifest: PackManifest,
    artifacts: Mapping[str, Mapping[str, Any]],
) -> tuple[str, ...]:
    warnings: list[str] = []
    modalities = set(manifest.modalities)
    discourse_profiles = set(manifest.discourse_profiles)

    field_rows = artifacts["field_table"]["rows"]
    claim_rows = artifacts["claim_family_table"]["rows"]
    review_rows = artifacts["review_rules"]["rows"]
    projection_rows = artifacts["projection_rules"]["rows"]
    mask_rows = artifacts["allowed_field_masks"]["rows"]
    parser_rows = artifacts["parser_profiles"]["rows"]
    negative_rows = artifacts["negative_examples"]["rows"]
    retrieval_rows = artifacts["retrieval_exemplars"]["rows"]

    _unique(field_rows, "field_id", "field_table")
    _unique(claim_rows, "claim_family_id", "claim_family_table")
    _unique(review_rows, "rule_id", "review_rules")
    _unique(projection_rows, "projection_rule_id", "projection_rules")
    _unique(mask_rows, "mask_id", "allowed_field_masks")
    _unique(parser_rows, "parser_profile_id", "parser_profiles")
    _unique(negative_rows, "negative_example_id", "negative_examples")
    _unique(retrieval_rows, "exemplar_id", "retrieval_exemplars")

    field_ids = {str(row["field_id"]) for row in field_rows}
    claim_ids = {str(row["claim_family_id"]) for row in claim_rows}
    rule_ids = {str(row["rule_id"]) for row in review_rows}
    modality_masks = {str(row["modality"]) for row in mask_rows}

    for row in projection_rows:
        if str(row["source_claim_family_id"]) not in claim_ids:
            raise ContractLoadError("projection_rules contains unknown source_claim_family_id")
        unknown_targets = [f for f in row.get("target_field_ids", []) if str(f) not in field_ids]
        if unknown_targets:
            raise ContractLoadError(f"projection_rules references unknown target_field_ids: {unknown_targets}")

    for row in review_rows:
        unknown_fields = [f for f in row.get("applies_to_field_ids", []) if str(f) not in field_ids]
        if unknown_fields:
            raise ContractLoadError(f"review_rules references unknown applies_to_field_ids: {unknown_fields}")
        unknown_claims = [c for c in row.get("applies_to_claim_family_ids", []) if str(c) not in claim_ids]
        if unknown_claims:
            raise ContractLoadError(
                f"review_rules references unknown applies_to_claim_family_ids: {unknown_claims}"
            )
        unknown_modalities = [m for m in row.get("applies_to_modalities", []) if str(m) not in modalities]
        if unknown_modalities:
            raise ContractLoadError(f"review_rules references unknown modalities: {unknown_modalities}")

    for row in mask_rows:
        unknown_allowed_fields = [f for f in row.get("allowed_field_ids", []) if str(f) not in field_ids]
        if unknown_allowed_fields:
            raise ContractLoadError(
                f"allowed_field_masks references unknown allowed_field_ids: {unknown_allowed_fields}"
            )

    for row in parser_rows:
        modality = str(row.get("modality"))
        if modality not in modality_masks:
            raise ContractLoadError(f"parser_profiles modality has no matching allowed mask: {modality}")

    def _validate_examples(rows: list[Mapping[str, Any]], name: str) -> None:
        for row in rows:
            unknown_fields = [f for f in row.get("linked_field_ids", []) if str(f) not in field_ids]
            if unknown_fields:
                raise ContractLoadError(f"{name} references unknown linked_field_ids: {unknown_fields}")
            unknown_claims = [c for c in row.get("linked_claim_family_ids", []) if str(c) not in claim_ids]
            if unknown_claims:
                raise ContractLoadError(f"{name} references unknown linked_claim_family_ids: {unknown_claims}")
            unknown_rules = [r for r in row.get("linked_review_rule_ids", []) if str(r) not in rule_ids]
            if unknown_rules:
                raise ContractLoadError(f"{name} references unknown linked_review_rule_ids: {unknown_rules}")
            unknown_modalities = [m for m in row.get("modalities", []) if str(m) not in modalities]
            if unknown_modalities:
                raise ContractLoadError(f"{name} references unknown modalities: {unknown_modalities}")
            unknown_profiles = [p for p in row.get("discourse_profiles", []) if str(p) not in discourse_profiles]
            if unknown_profiles:
                raise ContractLoadError(f"{name} references unknown discourse_profiles: {unknown_profiles}")

    _validate_examples(negative_rows, "negative_examples")
    _validate_examples(retrieval_rows, "retrieval_exemplars")

    for profile in discourse_profiles:
        if not any(profile in row.get("discourse_profiles", []) for row in retrieval_rows):
            warnings.append(f"0 retrieval exemplars for discourse profile: {profile}")
    for modality in modalities:
        if not any(modality in row.get("modalities", []) for row in negative_rows):
            warnings.append(f"0 negative examples for modality: {modality}")
    return tuple(sorted(set(warnings)))


def load_compiled_pack(
    pack_id: str,
    *,
    compiled_root: Path,
    pack_version: str = "v1",
) -> CompiledPack:
    pack_dir = compiled_root / pack_id / pack_version
    manifest_path = pack_dir / "manifest.json"
    manifest_data = _read_json(manifest_path)
    manifest = _parse_manifest(manifest_data, pack_id)

    artifacts: dict[str, Mapping[str, Any]] = {}
    for artifact_name in REQUIRED_ARTIFACTS:
        artifacts[artifact_name] = _load_artifact(
            pack_dir,
            artifact_name=artifact_name,
            descriptor=manifest.artifacts[artifact_name],
        )

    diagnostics_payload: Mapping[str, Any] | None = None
    if manifest.diagnostics_file:
        diagnostics_path = pack_dir / manifest.diagnostics_file
        if diagnostics_path.exists():
            diagnostics_payload = _read_json(diagnostics_path)
        else:
            diagnostics_payload = None

    warnings = list(_validate_cross_artifact(manifest, artifacts))
    if manifest.diagnostics_file and diagnostics_payload is None:
        warnings.append(f"optional diagnostics file missing: {manifest.diagnostics_file}")
    if artifacts["projection_rules"].get("row_count") == 0:
        warnings.append("projection rules artifact is empty; runtime projection is effectively disabled")
    if not bool(manifest.capabilities.get("strict_mask_alignment_enforced", True)):
        warnings.append("strict mask alignment was not enforced during compile")
    for payload in (
        diagnostics_payload,
        artifacts["field_table"],
        artifacts["claim_family_table"],
        artifacts["review_rules"],
        artifacts["projection_rules"],
        artifacts["allowed_field_masks"],
        artifacts["parser_profiles"],
        artifacts["negative_examples"],
        artifacts["retrieval_exemplars"],
    ):
        if not isinstance(payload, Mapping):
            continue
        rows = payload.get("rows")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            level = str(row.get("level", "")).lower()
            if level in {"warning", "info"}:
                code = str(row.get("code", "unknown_code"))
                message = str(row.get("message", ""))
                warnings.append(f"{level}:{code}: {message}")

    return CompiledPack(
        manifest=manifest,
        field_table=artifacts["field_table"],
        claim_family_table=artifacts["claim_family_table"],
        review_rules=artifacts["review_rules"],
        projection_rules=artifacts["projection_rules"],
        allowed_field_masks=artifacts["allowed_field_masks"],
        parser_profiles=artifacts["parser_profiles"],
        negative_examples=artifacts["negative_examples"],
        retrieval_exemplars=artifacts["retrieval_exemplars"],
        diagnostics=diagnostics_payload,
        warnings=tuple(sorted(set(warnings))),
    )
