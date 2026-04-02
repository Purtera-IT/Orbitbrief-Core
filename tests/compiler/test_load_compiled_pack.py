from __future__ import annotations

import json
from pathlib import Path

import pytest

from orbitbrief_core.compiler.core.load_contracts import ContractLoadError, PackContractPaths
from orbitbrief_core.compiler.packs.professional_services_text.compiler_runner import (
    compile_pack,
    emit_compiled_pack,
    load_compiled_pack,
)


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def _build_paths(tmp_path: Path) -> PackContractPaths:
    source_contracts = _write(
        tmp_path / "managed_services_base_source_contracts.json",
        json.dumps({"version": "1.0.0", "narrative_modalities": {"txt": {}, "docx": {}}, "source_contracts": {"bundle": "base"}}),
    )
    field_catalog = _write(
        tmp_path / "managed_services_base_precise_field_catalog.json",
        json.dumps(
            {
                "version": "1.0.0",
                "pre_field_definitions": {"project_summary": {"kind": "string"}, "site_count": {"kind": "integer"}},
                "post_field_definitions": {"scope_overview": {"kind": "string"}},
                "field_paths": ["project_summary", "site_count", "scope_overview"],
            }
        ),
    )
    enhanced_machine = _write(
        tmp_path / "professional_services_text_enhanced_machine.yaml",
        "\n".join(
            [
                "version: 1.0.0",
                "task_contract:",
                "  task_name: text_narrative_parser",
                "scope:",
                "  pack_id: professional_services_text",
                "  artifact_family: managed_services_text",
                "  role_id: transcript_or_notes",
                "field_semantics:",
                "  project_summary:",
                "    desc: Summary field",
                "claim_family_semantics:",
                "  project_summary_claim:",
                "    desc: Summary claim family",
                "    maps_to: [project_summary]",
                "review_rules:",
                "  weak_signal:",
                "    severity: warning",
                "    trigger_type: weak_evidence",
                "    machine_instruction: Ask for stronger support.",
                "    fields: [project_summary]",
                "    claim_families: [project_summary_claim]",
                "projection_rules:",
                "  summarize:",
                "    claim_family: project_summary_claim",
                "    target_fields: [scope_overview]",
                "modality_profiles:",
                "  txt: {}",
                "  docx: {}",
            ]
        )
        + "\n",
    )
    rich_modalities = _write(
        tmp_path / "professional_services_text_rich_all_modalities.yaml",
        "\n".join(
            [
                "version: 1.0.0",
                "modalities:",
                "  txt: {}",
                "  docx: {}",
                "parser_sandwich:",
                "  layer_a_deterministic_pre_parser: {}",
                "field_path_index:",
                "  rich_discovery_pre: [project_summary, site_count, scope_overview]",
            ]
        )
        + "\n",
    )
    _write(
        tmp_path / "professional_services_text_examples.yaml",
        "\n".join(
            [
                "schema_id: professional_services_text_examples.v1",
                "pack_id: professional_services_text",
                "supported_modalities: [txt, docx]",
                "retrieval_exemplars:",
                "  - text: Site count is 14 stores in wave one.",
                "    category: site_count",
                "    linked_field_paths: [site_count]",
                "    linked_claim_families: [project_summary_claim]",
                "negative_examples:",
                "  - text: Please consider the environment before printing.",
                "    category: legal_disclaimer",
                "    modalities: [docx]",
            ]
        )
        + "\n",
    )
    return PackContractPaths(
        pack_id="professional_services_text",
        source_contracts_path=source_contracts,
        field_catalog_path=field_catalog,
        enhanced_machine_path=enhanced_machine,
        rich_modalities_path=rich_modalities,
    )


def test_load_compiled_pack_happy_path(tmp_path: Path) -> None:
    artifacts = compile_pack(_build_paths(tmp_path))
    compiled_root = tmp_path / "compiled_artifacts"
    emit_compiled_pack(artifacts, compiled_root)
    loaded = load_compiled_pack("professional_services_text", compiled_root=compiled_root)
    assert loaded.manifest.pack_id == "professional_services_text"
    assert loaded.field_table["artifact_name"] == "field_table"
    assert loaded.negative_examples["artifact_name"] == "negative_examples"


def test_load_compiled_pack_hash_mismatch_fails(tmp_path: Path) -> None:
    artifacts = compile_pack(_build_paths(tmp_path))
    compiled_root = tmp_path / "compiled_artifacts"
    emit_compiled_pack(artifacts, compiled_root)
    target = compiled_root / "professional_services_text" / "v1" / "field_table.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["rows"][0]["field_name"] = "tampered"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(ContractLoadError, match="hash mismatch"):
        load_compiled_pack("professional_services_text", compiled_root=compiled_root)
