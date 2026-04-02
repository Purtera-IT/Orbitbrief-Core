from __future__ import annotations

import json
from pathlib import Path

import pytest

from orbitbrief_core.compiler.core.load_contracts import (
    ContractConflictError,
    ContractLoadError,
    PackContractPaths,
    load_raw_contracts,
)
from orbitbrief_core.compiler.core.resolve_precedence import CONCERNS, resolve_precedence


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def _build_paths(
    tmp_path: Path,
    *,
    source_modalities: tuple[str, ...] = ("txt",),
    semantic_profiles: str = "modality_profiles:\n  txt: {}\n",
    field_semantics: str = "pre_field_definitions:\n  project_summary: {kind: string}\n",
    projection_rules: str = "projection_rules: {}\n",
    embedded_scope: str | None = "scope:\n  pack_id: professional_services_text\n  artifact_family: managed_services_text\n  role_id: transcript_or_notes\n",
    embedded_handoff: str | None = None,
    external_scope: str | None = None,
    external_handoff: str | None = None,
) -> PackContractPaths:
    source_contracts = _write(
        tmp_path / "managed_services_base_source_contracts.json",
        json.dumps(
            {
                "version": "1.0.0",
                "modalities": {m: {} for m in source_modalities},
                "sources": {"bundle": "base"},
            }
        ),
    )
    field_catalog = _write(
        tmp_path / "managed_services_base_precise_field_catalog.json",
        json.dumps(
            {
                "version": "1.0.0",
                "fields": {
                    "project_summary": {},
                    "scope_overview": {},
                    "site_count": {},
                }
            }
        ),
    )
    enhanced_parts = [
        "version: 1.0.0",
        "task_contract:",
        "  task_name: text_narrative_parser",
        semantic_profiles.rstrip(),
        field_semantics.rstrip(),
        projection_rules.rstrip(),
    ]
    if embedded_scope:
        enhanced_parts.append(embedded_scope.rstrip())
    if embedded_handoff:
        enhanced_parts.append(embedded_handoff.rstrip())
    enhanced_machine = _write(
        tmp_path / "professional_services_text_enhanced_machine.yaml",
        "\n".join(enhanced_parts) + "\n",
    )
    rich_modalities = _write(
        tmp_path / "professional_services_text_rich_all_modalities.yaml",
        "\n".join(
            [
                "version: 1.0.0",
                "modality_profiles:",
                "  txt: {}",
                "parser_sandwich:",
                "  layer_a_deterministic_pre_parser: {}",
                "field_path_index:",
                "  rich_discovery_pre: [project_summary, scope_overview, site_count]",
            ]
        )
        + "\n",
    )

    scope_contract_path = _write(tmp_path / "scope.yaml", external_scope) if external_scope else None
    handoff_contract_path = _write(tmp_path / "handoff.yaml", external_handoff) if external_handoff else None

    return PackContractPaths(
        pack_id="professional_services_text",
        source_contracts_path=source_contracts,
        field_catalog_path=field_catalog,
        enhanced_machine_path=enhanced_machine,
        rich_modalities_path=rich_modalities,
        scope_contract_path=scope_contract_path,
        handoff_contract_path=handoff_contract_path,
    )


def test_v2_happy_path(tmp_path: Path) -> None:
    paths = _build_paths(tmp_path)
    resolved = resolve_precedence(load_raw_contracts(paths))

    assert resolved.pack_id == "professional_services_text"
    assert resolved.resolved_scope.role_id == "transcript_or_notes"
    assert "txt" in resolved.resolved_modalities
    assert resolved.diagnostics


def test_v2_external_scope_normalization(tmp_path: Path) -> None:
    paths = _build_paths(
        tmp_path,
        embedded_scope=None,
        external_scope="\n".join(
            [
                "scope:",
                "  pack_id: professional_services_text",
                "  artifact_family: managed_services_text",
                "  role_id: transcript_or_notes",
            ]
        )
        + "\n",
    )
    resolved = resolve_precedence(load_raw_contracts(paths))
    assert resolved.resolved_scope.artifact_family == "managed_services_text"
    scope_record = next(r for r in resolved.resolution_records if r.concern == "scope")
    assert scope_record.winner_role == "scope_contract"


def test_v2_embedded_scope_normalization(tmp_path: Path) -> None:
    paths = _build_paths(tmp_path, external_scope=None)
    resolved = resolve_precedence(load_raw_contracts(paths))
    scope_record = next(r for r in resolved.resolution_records if r.concern == "scope")
    assert scope_record.winner_role == "enhanced_machine"


def test_v2_external_handoff_normalization(tmp_path: Path) -> None:
    paths = _build_paths(
        tmp_path,
        external_handoff="routing_handoff_contract:\n  candidate_domain_overlays: [wireless]\n",
    )
    resolved = resolve_precedence(load_raw_contracts(paths))
    assert resolved.resolved_handoff is not None
    assert resolved.resolved_handoff.candidate_domain_overlays == ("wireless",)


def test_v2_embedded_handoff_normalization(tmp_path: Path) -> None:
    paths = _build_paths(
        tmp_path,
        embedded_handoff="routing_handoff_contract:\n  candidate_domain_overlays: [telecom]\n",
    )
    resolved = resolve_precedence(load_raw_contracts(paths))
    assert resolved.resolved_handoff is not None
    assert resolved.resolved_handoff.candidate_domain_overlays == ("telecom",)


def test_v2_parser_profile_fallback_merge(tmp_path: Path) -> None:
    paths = _build_paths(
        tmp_path,
        source_modalities=("txt", "docx"),
        semantic_profiles="modality_profiles:\n  txt: {}\n",
    )
    resolved = resolve_precedence(load_raw_contracts(paths))
    parser_record = next(r for r in resolved.resolution_records if r.concern == "parser_profiles")
    assert parser_record.strategy in {"authoritative_override", "fallback_merge"}


def test_v2_illegal_projection_target_raises(tmp_path: Path) -> None:
    paths = _build_paths(
        tmp_path,
        projection_rules="projection_rules:\n  emits: [illegal_field]\n",
    )
    with pytest.raises(ContractLoadError, match="Illegal field references"):
        resolve_precedence(load_raw_contracts(paths))


def test_v2_unknown_modality_in_parser_profiles_raises(tmp_path: Path) -> None:
    paths = _build_paths(
        tmp_path,
        source_modalities=("txt",),
        semantic_profiles="modality_profiles:\n  csv: {}\n",
    )
    with pytest.raises(ContractLoadError, match="unknown modalities"):
        resolve_precedence(load_raw_contracts(paths))


def test_v2_boundary_leakage_structured_forbidden_section(tmp_path: Path) -> None:
    paths = _build_paths(
        tmp_path,
        embedded_scope="\n".join(
            [
                "scope:",
                "  pack_id: professional_services_text",
                "  artifact_family: managed_services_text",
                "  role_id: transcript_or_notes",
                "  not_authoritative_for: [spreadsheet row truth]",
            ]
        )
        + "\n",
        field_semantics="pre_field_definitions:\n  site_roster_rows[].site_id: {kind: string}\n",
    )
    with pytest.raises(ContractLoadError, match="Boundary violation"):
        resolve_precedence(load_raw_contracts(paths))


def test_v2_warning_when_no_handoff_present(tmp_path: Path) -> None:
    paths = _build_paths(tmp_path, embedded_handoff=None, external_handoff=None)
    resolved = resolve_precedence(load_raw_contracts(paths))
    assert any(d.code == "resolve_precedence.handoff_missing" for d in resolved.diagnostics)


def test_v2_resolution_records_completeness(tmp_path: Path) -> None:
    paths = _build_paths(tmp_path)
    resolved = resolve_precedence(load_raw_contracts(paths))
    concerns = {record.concern for record in resolved.resolution_records}
    assert set(CONCERNS).issubset(concerns)


def test_v2_summary_diagnostic_present(tmp_path: Path) -> None:
    paths = _build_paths(tmp_path)
    resolved = resolve_precedence(load_raw_contracts(paths))
    assert any(d.code == "resolve_precedence.v2.summary" for d in resolved.diagnostics)


def test_v2_pack_id_mismatch_is_hard_error(tmp_path: Path) -> None:
    paths = _build_paths(
        tmp_path,
        embedded_scope="\n".join(
            [
                "scope:",
                "  pack_id: mismatched_pack_id",
                "  artifact_family: managed_services_text",
                "  role_id: transcript_or_notes",
            ]
        )
        + "\n",
    )
    with pytest.raises(ContractLoadError, match="does not match resolved pack_id"):
        resolve_precedence(load_raw_contracts(paths))


def test_v2_embedded_and_external_scope_conflict_still_blocked_in_loader(tmp_path: Path) -> None:
    paths = _build_paths(
        tmp_path,
        embedded_scope="scope:\n  pack_id: professional_services_text\n  artifact_family: managed_services_text\n  role_id: transcript_or_notes\n",
        external_scope="pack_id: professional_services_text\nrole_id: transcript_or_notes\n",
    )
    with pytest.raises(ContractConflictError):
        load_raw_contracts(paths)
