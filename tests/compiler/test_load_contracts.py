from __future__ import annotations

import json
from pathlib import Path

import pytest

from orbitbrief_core.compiler.core.load_contracts import (
    ContractLoadError,
    ContractConflictError,
    ContractParseError,
    ContractShapeError,
    MissingContractFileError,
    PackContractPaths,
    bundle_manifest,
    get_embedded_scope,
    load_document,
    load_raw_contracts,
)


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def _build_valid_paths(tmp_path: Path) -> PackContractPaths:
    source_contracts = _write(
        tmp_path / "managed_services_base_source_contracts.json",
        json.dumps({"version": "1.0.0", "modalities": {"txt": {}}}),
    )
    field_catalog = _write(
        tmp_path / "managed_services_base_precise_field_catalog.json",
        json.dumps({"version": "1.0.0", "fields": [{"path": "project_summary"}]}),
    )
    enhanced_machine = _write(
        tmp_path / "professional_services_text_enhanced_machine.yaml",
        "\n".join(
            [
                "version: 1.0.0",
                "task_contract:",
                "  task_name: text_narrative_parser",
            ]
        ),
    )
    rich_modalities = _write(
        tmp_path / "professional_services_text_rich_all_modalities.yaml",
        "\n".join(
            [
                "version: 1.0.0",
                "modalities:",
                "  txt: {}",
            ]
        ),
    )
    return PackContractPaths(
        pack_id="professional_services_text",
        source_contracts_path=source_contracts,
        field_catalog_path=field_catalog,
        enhanced_machine_path=enhanced_machine,
        rich_modalities_path=rich_modalities,
    )


def test_load_contracts_success(tmp_path: Path) -> None:
    paths = _build_valid_paths(tmp_path)
    bundle = load_raw_contracts(paths)

    assert bundle.pack_id == "professional_services_text"
    assert bundle.source_contracts.metadata.role == "source_contracts"
    assert bundle.field_catalog.metadata.role == "field_catalog"
    assert bundle.enhanced_machine.metadata.role == "enhanced_machine"
    assert bundle.rich_modalities.metadata.role == "rich_modalities"
    assert len(bundle.all_documents) == 4


def test_missing_required_file_raises(tmp_path: Path) -> None:
    paths = _build_valid_paths(tmp_path)
    paths = PackContractPaths(
        pack_id=paths.pack_id,
        source_contracts_path=paths.source_contracts_path,
        field_catalog_path=tmp_path / "missing_field_catalog.json",
        enhanced_machine_path=paths.enhanced_machine_path,
        rich_modalities_path=paths.rich_modalities_path,
    )

    with pytest.raises(MissingContractFileError):
        load_raw_contracts(paths)


def test_malformed_json_raises_parse_error(tmp_path: Path) -> None:
    broken_json = _write(tmp_path / "broken.json", '{"fields": [}')
    with pytest.raises(ContractParseError):
        load_document(broken_json, "field_catalog")


def test_malformed_yaml_raises_parse_error(tmp_path: Path) -> None:
    broken_yaml = _write(tmp_path / "broken.yaml", "task_contract: [")
    with pytest.raises(ContractParseError):
        load_document(broken_yaml, "enhanced_machine")


def test_wrong_top_level_shape_raises(tmp_path: Path) -> None:
    wrong_shape = _write(tmp_path / "wrong_shape.json", json.dumps(["not", "a", "mapping"]))
    with pytest.raises(ContractShapeError):
        load_document(wrong_shape, "field_catalog")


def test_embedded_scope_conflict_raises(tmp_path: Path) -> None:
    paths = _build_valid_paths(tmp_path)
    _write(paths.enhanced_machine_path, "scope: {}\ntask_contract: {task_name: text_narrative_parser}\n")
    scope_contract = _write(
        tmp_path / "professional_services_text_scope_block.yaml",
        "pack_id: x\nrole_id: transcript_or_notes\n",
    )

    conflict_paths = PackContractPaths(
        pack_id=paths.pack_id,
        source_contracts_path=paths.source_contracts_path,
        field_catalog_path=paths.field_catalog_path,
        enhanced_machine_path=paths.enhanced_machine_path,
        rich_modalities_path=paths.rich_modalities_path,
        scope_contract_path=scope_contract,
    )

    with pytest.raises(ContractConflictError):
        load_raw_contracts(conflict_paths)


def test_embedded_handoff_conflict_raises(tmp_path: Path) -> None:
    paths = _build_valid_paths(tmp_path)
    _write(
        paths.enhanced_machine_path,
        "routing_handoff_contract: {}\ntask_contract: {task_name: text_narrative_parser}\n",
    )
    handoff_contract = _write(
        tmp_path / "professional_services_text_handoff_contract.yaml",
        "routing_handoff_contract: {}\n",
    )

    conflict_paths = PackContractPaths(
        pack_id=paths.pack_id,
        source_contracts_path=paths.source_contracts_path,
        field_catalog_path=paths.field_catalog_path,
        enhanced_machine_path=paths.enhanced_machine_path,
        rich_modalities_path=paths.rich_modalities_path,
        handoff_contract_path=handoff_contract,
    )

    with pytest.raises(ContractConflictError):
        load_raw_contracts(conflict_paths)


def test_metadata_presence(tmp_path: Path) -> None:
    paths = _build_valid_paths(tmp_path)
    doc = load_document(paths.source_contracts_path, "source_contracts")

    assert doc.metadata.path == paths.source_contracts_path.resolve()
    assert doc.metadata.filename == "managed_services_base_source_contracts.json"
    assert doc.metadata.format == "json"
    assert doc.metadata.size_bytes > 0
    assert doc.metadata.sha256
    assert doc.metadata.modified_time_epoch > 0
    assert doc.metadata.contract_version == "1.0.0"


def test_hash_stability(tmp_path: Path) -> None:
    paths = _build_valid_paths(tmp_path)
    doc_a = load_document(paths.field_catalog_path, "field_catalog")
    doc_b = load_document(paths.field_catalog_path, "field_catalog")

    assert doc_a.metadata.sha256 == doc_b.metadata.sha256


def test_duplicate_role_paths_raise(tmp_path: Path) -> None:
    paths = _build_valid_paths(tmp_path)
    duplicate_paths = PackContractPaths(
        pack_id=paths.pack_id,
        source_contracts_path=paths.source_contracts_path,
        field_catalog_path=paths.source_contracts_path,
        enhanced_machine_path=paths.enhanced_machine_path,
        rich_modalities_path=paths.rich_modalities_path,
    )
    with pytest.raises(ContractLoadError):
        load_raw_contracts(duplicate_paths)


def test_non_file_path_raises_missing_contract_error(tmp_path: Path) -> None:
    directory_path = tmp_path / "not_a_file"
    directory_path.mkdir(parents=True, exist_ok=True)
    with pytest.raises(MissingContractFileError):
        load_document(directory_path, "field_catalog")


def test_scope_contract_requires_pack_id_and_role_id(tmp_path: Path) -> None:
    invalid_scope = _write(tmp_path / "scope.yaml", "pack_id: x\n")
    with pytest.raises(ContractShapeError):
        load_document(invalid_scope, "scope_contract")


def test_handoff_contract_requires_mapping_or_list_form_arrays(tmp_path: Path) -> None:
    invalid_handoff = _write(tmp_path / "handoff.yaml", "candidate_domain_overlays: not-a-list\n")
    with pytest.raises(ContractShapeError):
        load_document(invalid_handoff, "handoff_contract")


def test_bundle_manifest_contains_loaded_docs(tmp_path: Path) -> None:
    paths = _build_valid_paths(tmp_path)
    bundle = load_raw_contracts(paths)
    manifest = bundle_manifest(bundle)

    assert manifest["pack_id"] == "professional_services_text"
    assert len(manifest["documents"]) == 4
    assert {doc["role"] for doc in manifest["documents"]} == {
        "source_contracts",
        "field_catalog",
        "enhanced_machine",
        "rich_modalities",
    }


def test_get_embedded_scope_returns_mapping_when_present(tmp_path: Path) -> None:
    paths = _build_valid_paths(tmp_path)
    _write(
        paths.enhanced_machine_path,
        "\n".join(
            [
                "version: 1.0.0",
                "task_contract:",
                "  task_name: text_narrative_parser",
                "scope:",
                "  pack_id: professional_services_text",
            ]
        ),
    )
    bundle = load_raw_contracts(paths)
    scope = get_embedded_scope(bundle.enhanced_machine)

    assert scope is not None
    assert scope["pack_id"] == "professional_services_text"


def test_source_contracts_accepts_narrative_modalities_shape(tmp_path: Path) -> None:
    source_contracts = _write(
        tmp_path / "managed_services_base_source_contracts.json",
        json.dumps(
            {
                "version": "1.0.0",
                "narrative_modalities": {"txt": {}, "docx": {}},
                "base_scope": {"role_id": "transcript_or_notes"},
            }
        ),
    )
    doc = load_document(source_contracts, "source_contracts")
    assert "narrative_modalities" in doc.data


def test_field_catalog_accepts_split_pre_post_shape(tmp_path: Path) -> None:
    field_catalog = _write(
        tmp_path / "managed_services_base_precise_field_catalog.json",
        json.dumps(
            {
                "version": "1.0.0",
                "pre_field_definitions": {"project_summary": {"kind": "string"}},
                "post_field_definitions": {"scope_overview": {"kind": "string"}},
            }
        ),
    )
    doc = load_document(field_catalog, "field_catalog")
    assert "pre_field_definitions" in doc.data
    assert "post_field_definitions" in doc.data
