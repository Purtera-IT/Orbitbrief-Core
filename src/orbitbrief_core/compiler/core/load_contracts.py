from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping as AbcMapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Mapping, TypeAlias

import yaml


DocumentRole = Literal[
    "source_contracts",
    "field_catalog",
    "enhanced_machine",
    "rich_modalities",
    "scope_contract",
    "handoff_contract",
]

DocumentFormat = Literal["json", "yaml"]
FrozenJSONLike: TypeAlias = (
    str
    | int
    | float
    | bool
    | None
    | tuple["FrozenJSONLike", ...]
    | Mapping[str, "FrozenJSONLike"]
)

EXPECTED_ROLE_KEYS: dict[DocumentRole, set[str]] = {
    "source_contracts": {
        "modalities",
        "narrative_modalities",
        "sources",
        "source_contracts",
        "common_target_views",
        "base_scope",
    },
    "field_catalog": {
        "fields",
        "field_catalog",
        "pre_field_definitions",
        "post_field_definitions",
        "rich_base_pre",
        "fixed_post",
    },
    "enhanced_machine": {"task_contract", "scope", "routing_handoff_contract", "field_definitions"},
    "rich_modalities": {"modalities", "allowed_field_paths", "parser_sandwich"},
    "scope_contract": {"pack_id", "artifact_family", "role_id", "scope"},
    "handoff_contract": {
        "routing_handoff_contract",
        "candidate_domain_overlays",
        "follow_on_artifact_requests",
    },
}


class ContractLoadError(Exception):
    """Base exception for contract loading failures."""


class MissingContractFileError(ContractLoadError):
    """Raised when a required contract file is missing or not a file."""


class ContractParseError(ContractLoadError):
    """Raised when a contract file cannot be decoded or parsed."""


class ContractShapeError(ContractLoadError):
    """Raised when a parsed contract does not match expected shape."""


class ContractConflictError(ContractLoadError):
    """Raised when optional contract sources conflict with embedded sections."""


@dataclass(frozen=True)
class SourceMetadata:
    role: DocumentRole
    format: DocumentFormat
    path: Path
    filename: str
    sha256: str
    size_bytes: int
    modified_time_epoch: float
    parser_version: str
    contract_version: str | None = None


@dataclass(frozen=True)
class SourceDocument:
    metadata: SourceMetadata
    raw_text: str
    data: Mapping[str, FrozenJSONLike]


@dataclass(frozen=True)
class PackContractPaths:
    pack_id: str
    source_contracts_path: Path
    field_catalog_path: Path
    enhanced_machine_path: Path
    rich_modalities_path: Path
    scope_contract_path: Path | None = None
    handoff_contract_path: Path | None = None


@dataclass(frozen=True)
class RawContractsBundle:
    pack_id: str
    source_contracts: SourceDocument
    field_catalog: SourceDocument
    enhanced_machine: SourceDocument
    rich_modalities: SourceDocument
    scope_contract: SourceDocument | None = None
    handoff_contract: SourceDocument | None = None

    @property
    def all_documents(self) -> tuple[SourceDocument, ...]:
        docs = [
            self.source_contracts,
            self.field_catalog,
            self.enhanced_machine,
            self.rich_modalities,
        ]
        if self.scope_contract is not None:
            docs.append(self.scope_contract)
        if self.handoff_contract is not None:
            docs.append(self.handoff_contract)
        return tuple(docs)


def _deep_freeze(value: Any) -> FrozenJSONLike:
    if isinstance(value, dict):
        return MappingProxyType({k: _deep_freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_deep_freeze(v) for v in value)
    return value


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _detect_format(path: Path) -> DocumentFormat:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix in {".yaml", ".yml"}:
        return "yaml"
    raise ContractLoadError(f"Unsupported file format for {path}")


def _parse_text(raw_text: str, fmt: DocumentFormat, path: Path) -> Mapping[str, Any]:
    try:
        parsed = json.loads(raw_text) if fmt == "json" else yaml.safe_load(raw_text)
    except Exception as exc:  # pragma: no cover - parser exceptions vary by backend version
        raise ContractParseError(f"Failed to parse {path}: {exc}") from exc

    if not isinstance(parsed, dict):
        got = type(parsed).__name__
        raise ContractShapeError(f"Expected top-level mapping in {path}, got {got}")
    return parsed


def _extract_contract_version(data: Mapping[str, Any]) -> str | None:
    version = data.get("version")
    return str(version) if version is not None else None


def _validate_role_shape(data: Mapping[str, Any], role: DocumentRole, path: Path) -> None:
    expected_keys = EXPECTED_ROLE_KEYS[role]
    if not any(key in data for key in expected_keys):
        raise ContractShapeError(
            f"{path} does not look like a valid {role} document. "
            f"Expected at least one of: {sorted(expected_keys)}"
        )


def _validate_optional_contract_strength(data: Mapping[str, Any], role: DocumentRole, path: Path) -> None:
    if role == "scope_contract":
        scope_body = data.get("scope") if isinstance(data.get("scope"), AbcMapping) else data
        required = {"pack_id", "role_id"}
        missing = sorted(required - set(scope_body.keys()))
        if missing:
            raise ContractShapeError(
                f"{path} for role=scope_contract is missing required keys: {missing}"
            )
        return

    if role != "handoff_contract":
        return

    if "routing_handoff_contract" in data:
        if not isinstance(data["routing_handoff_contract"], AbcMapping):
            raise ContractShapeError(
                f"{path} has routing_handoff_contract but it is not a mapping object."
            )
        return

    explicit_arrays = [
        "candidate_domain_overlays",
        "follow_on_artifact_requests",
        "authority_needed_flags",
        "verification_needed_flags",
        "cross_pack_entities",
    ]
    for key in explicit_arrays:
        value = data.get(key)
        if isinstance(value, list):
            return

    raise ContractShapeError(
        f"{path} for role=handoff_contract must include a mapping "
        "'routing_handoff_contract' or at least one list-form handoff array."
    )


def _validate_unique_paths(paths: PackContractPaths) -> None:
    role_paths: dict[DocumentRole, Path | None] = {
        "source_contracts": paths.source_contracts_path,
        "field_catalog": paths.field_catalog_path,
        "enhanced_machine": paths.enhanced_machine_path,
        "rich_modalities": paths.rich_modalities_path,
        "scope_contract": paths.scope_contract_path,
        "handoff_contract": paths.handoff_contract_path,
    }
    seen: dict[Path, DocumentRole] = {}
    for role, maybe_path in role_paths.items():
        if maybe_path is None:
            continue
        resolved = maybe_path.resolve()
        previous_role = seen.get(resolved)
        if previous_role is not None:
            raise ContractLoadError(
                f"Duplicate contract path: role={role} and role={previous_role} both "
                f"point to {resolved}"
            )
        seen[resolved] = role


def _validate_embedded_optional_sections(
    enhanced_machine: SourceDocument,
    scope_contract: SourceDocument | None,
    handoff_contract: SourceDocument | None,
) -> None:
    has_embedded_scope = "scope" in enhanced_machine.data
    has_embedded_handoff = "routing_handoff_contract" in enhanced_machine.data

    if has_embedded_scope and scope_contract is not None:
        raise ContractConflictError(
            "Found both embedded 'scope' in enhanced_machine and an external scope_contract file."
        )
    if has_embedded_handoff and handoff_contract is not None:
        raise ContractConflictError(
            "Found both embedded 'routing_handoff_contract' in enhanced_machine and an external "
            "handoff_contract file."
        )


def load_document(path: Path, role: DocumentRole) -> SourceDocument:
    if not path.exists():
        raise MissingContractFileError(f"Missing contract file for role={role}: {path}")
    if not path.is_file():
        raise MissingContractFileError(
            f"Expected a file for role={role}, got non-file path: {path}"
        )

    raw_bytes = path.read_bytes()
    if not raw_bytes:
        raise ContractLoadError(f"Empty contract file for role={role}: {path}")

    try:
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractParseError(f"Failed to decode {path} as UTF-8: {exc}") from exc

    fmt = _detect_format(path)
    parsed_data = _parse_text(raw_text, fmt, path)
    _validate_role_shape(parsed_data, role, path)
    _validate_optional_contract_strength(parsed_data, role, path)

    stat = path.stat()
    metadata = SourceMetadata(
        role=role,
        format=fmt,
        path=path.resolve(),
        filename=path.name,
        sha256=_sha256_bytes(raw_bytes),
        size_bytes=len(raw_bytes),
        modified_time_epoch=stat.st_mtime,
        parser_version="load_contracts.v1",
        contract_version=_extract_contract_version(parsed_data),
    )
    return SourceDocument(
        metadata=metadata,
        raw_text=raw_text,
        data=_deep_freeze(parsed_data),
    )


def get_embedded_scope(enhanced_machine: SourceDocument) -> Mapping[str, FrozenJSONLike] | None:
    scope = enhanced_machine.data.get("scope")
    if isinstance(scope, AbcMapping):
        return scope
    return None


def bundle_manifest(bundle: RawContractsBundle) -> dict[str, Any]:
    return {
        "pack_id": bundle.pack_id,
        "documents": [
            {
                "role": doc.metadata.role,
                "path": str(doc.metadata.path),
                "sha256": doc.metadata.sha256,
                "format": doc.metadata.format,
                "size_bytes": doc.metadata.size_bytes,
                "contract_version": doc.metadata.contract_version,
                "parser_version": doc.metadata.parser_version,
            }
            for doc in bundle.all_documents
        ],
    }


def load_raw_contracts(paths: PackContractPaths) -> RawContractsBundle:
    _validate_unique_paths(paths)

    source_contracts = load_document(paths.source_contracts_path, "source_contracts")
    field_catalog = load_document(paths.field_catalog_path, "field_catalog")
    enhanced_machine = load_document(paths.enhanced_machine_path, "enhanced_machine")
    rich_modalities = load_document(paths.rich_modalities_path, "rich_modalities")

    scope_contract = (
        load_document(paths.scope_contract_path, "scope_contract")
        if paths.scope_contract_path is not None
        else None
    )
    handoff_contract = (
        load_document(paths.handoff_contract_path, "handoff_contract")
        if paths.handoff_contract_path is not None
        else None
    )

    _validate_embedded_optional_sections(
        enhanced_machine=enhanced_machine,
        scope_contract=scope_contract,
        handoff_contract=handoff_contract,
    )

    return RawContractsBundle(
        pack_id=paths.pack_id,
        source_contracts=source_contracts,
        field_catalog=field_catalog,
        enhanced_machine=enhanced_machine,
        rich_modalities=rich_modalities,
        scope_contract=scope_contract,
        handoff_contract=handoff_contract,
    )
