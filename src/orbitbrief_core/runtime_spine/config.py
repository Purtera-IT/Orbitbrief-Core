from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


IMPLEMENTED_RUNTIME_ROLES = {
    "transcript_or_notes",
    "site_roster_spreadsheet",
    "drawing_packet",
}

METADATA_KEYS = {
    "schema_name",
    "schema_version",
    "domain_id",
    "file_modality",
    "packet_type",
    "sheet_type",
    "schema_title",
    "schema_stage",
    "schema_system",
    "source_modality",
    "target_output_type",
    "description",
    "purpose",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def workspace_root() -> Path:
    return repo_root().parent


def shared_contracts_root() -> Path:
    return workspace_root() / "Shared-contracts"


def domain_config_root() -> Path:
    return repo_root() / "config" / "domains" / "professional_services"


def source_contracts_root() -> Path:
    return shared_contracts_root() / "contracts" / "orbitbrief" / "professional_services"


def mapping_config_root(role_id: str) -> Path:
    return domain_config_root() / "mapping" / role_id


def _yaml_load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


@lru_cache(maxsize=1)
def load_domain_config() -> dict[str, Any]:
    return _yaml_load(domain_config_root() / "domain.yaml")


@lru_cache(maxsize=1)
def load_role_registry() -> dict[str, dict[str, Any]]:
    roles_dir = domain_config_root() / "roles"
    return {path.stem: _yaml_load(path) for path in sorted(roles_dir.glob("*.yaml"))}


@lru_cache(maxsize=1)
def load_injection_registry() -> dict[str, dict[str, Any]]:
    inj_dir = domain_config_root() / "injections"
    return {path.stem: _yaml_load(path) for path in sorted(inj_dir.glob("*.yaml"))}


@lru_cache(maxsize=1)
def load_schema_registry() -> dict[str, Any]:
    return _yaml_load(domain_config_root() / "schema_registry.yaml")


@lru_cache(maxsize=1)
def schema_registry_by_ref() -> dict[str, dict[str, Any]]:
    return {entry["schema_ref_id"]: entry for entry in load_schema_registry()["entries"]}


@lru_cache(maxsize=1)
def load_role_modality_matrix() -> dict[str, Any]:
    return _yaml_load(domain_config_root() / "role_modality_matrix.yaml")


def matrix_rows_for_role(role_id: str) -> list[dict[str, Any]]:
    for row in load_role_modality_matrix()["roles"]:
        if row["role_id"] == role_id:
            return row["rows"]
    raise KeyError(f"Role modality matrix missing role: {role_id}")


def modality_key(modality: str) -> str:
    raw = str(modality).strip().lower()
    if raw.startswith("."):
        raw = raw[1:]
    compact = "".join(ch for ch in raw if ch.isalnum())
    if compact in {"zip", "zipexport"}:
        return "zip"
    if compact in {"dwgexportpdf"}:
        return "dwgexportpdf"
    if compact in {"imagepdf"}:
        return "imagepdf"
    if compact in {"emailexport"}:
        return "emailexport"
    if compact in {"pastednotes", "textblob"}:
        return "pastednotes"
    return compact


def modality_row(role_id: str, modality: str) -> dict[str, Any]:
    modality_l = modality_key(modality)
    for row in matrix_rows_for_role(role_id):
        if modality_key(str(row["modality"])) == modality_l:
            return row
    raise KeyError(f"No modality row for {role_id=} {modality=}")


def schema_entry(schema_ref_id: str) -> dict[str, Any]:
    try:
        return schema_registry_by_ref()[schema_ref_id]
    except KeyError as exc:
        raise KeyError(f"Unknown schema ref: {schema_ref_id}") from exc


def schema_payload(schema_ref_id: str) -> dict[str, Any]:
    entry = schema_entry(schema_ref_id)
    payload_ref = entry.get("schema_payload_ref") or entry.get("source_repo_path")
    if payload_ref is None:
        raise KeyError(f"Schema ref has no payload path: {schema_ref_id}")
    payload_path = shared_contracts_root() / payload_ref
    payload_doc = json.loads(payload_path.read_text())
    return payload_doc["schema_payload"]


def allowed_business_fields(schema_ref_id: str) -> list[str]:
    return [field for field in schema_payload(schema_ref_id).keys() if field not in METADATA_KEYS]


def role_config(role_id: str) -> dict[str, Any]:
    return load_role_registry()[role_id]


def injection_config(role_id: str) -> dict[str, Any]:
    return load_injection_registry()[role_id]


def supported_modalities_for_role(role_id: str) -> list[str]:
    return list(role_config(role_id)["allowed_modalities"])


def executable_pre_schema_ref(role_id: str, modality: str) -> str:
    row = modality_row(role_id, modality)
    ref = row.get("pre_source_ref")
    if not ref:
        raise KeyError(f"No PRE schema ref for {role_id=} {modality=}")
    return ref


def post_schema_ref(role_id: str, modality: str) -> str:
    row = modality_row(role_id, modality)
    ref = row.get("post_source_ref")
    if not ref:
        raise KeyError(f"No POST schema ref for {role_id=} {modality=}")
    return ref


def role_runtime_status(role_id: str) -> str:
    role = role_config(role_id)
    if role.get("status") == "parked":
        return "parked"
    if role_id in IMPLEMENTED_RUNTIME_ROLES:
        return "implemented"
    return "not_implemented"


def implemented_roles() -> list[str]:
    return sorted(IMPLEMENTED_RUNTIME_ROLES)


def config_snapshot_ref() -> dict[str, Any]:
    tracked_files = [domain_config_root() / "domain.yaml", domain_config_root() / "schema_registry.yaml", domain_config_root() / "role_modality_matrix.yaml"]
    tracked_files.extend(sorted((domain_config_root() / "roles").glob("*.yaml")))
    tracked_files.extend(sorted((domain_config_root() / "components").glob("*.yaml")))
    tracked_files.extend(sorted((domain_config_root() / "injections").glob("*.yaml")))
    hasher = hashlib.sha256()
    refs = []
    for path in tracked_files:
        rel = path.relative_to(repo_root()).as_posix()
        body = path.read_bytes()
        hasher.update(rel.encode("utf-8"))
        hasher.update(body)
        refs.append(rel)
    return {
        "snapshot_id": f"professional_services:{hasher.hexdigest()[:16]}",
        "snapshot_hash": hasher.hexdigest(),
        "domain_id": "professional_services",
        "snapshot_paths": refs,
    }
