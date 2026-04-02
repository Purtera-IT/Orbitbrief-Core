from __future__ import annotations
import argparse
from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence
import yaml

from orbitbrief_core.compiler.core.canonical_ir import CanonicalIR, build_canonical_ir
from orbitbrief_core.compiler.core.load_contracts import PackContractPaths, RawContractsBundle, load_raw_contracts
from orbitbrief_core.compiler.core.resolve_precedence import ResolvedContractsBundle, resolve_precedence
from orbitbrief_core.compiler.packs.professional_services_text.compile_allowed_masks import (
    CompiledAllowedMasks,
    compile_allowed_masks,
)
from orbitbrief_core.compiler.packs.professional_services_text.compile_claim_family_table import (
    CompiledClaimFamilyTable,
    compile_claim_family_table,
)
from orbitbrief_core.compiler.packs.professional_services_text.compile_field_table import (
    CompiledFieldTable,
    compile_field_table,
)
from orbitbrief_core.compiler.packs.professional_services_text.compile_negative_examples import CompiledNegativeExampleTable, compile_negative_examples
from orbitbrief_core.compiler.packs.professional_services_text.compile_parser_profile_table import (
    CompiledParserProfileTable,
    compile_parser_profile_table,
)
from orbitbrief_core.compiler.packs.professional_services_text.compile_projection_rule_table import (
    CompiledProjectionRuleTable,
    compile_projection_rule_table,
)
from orbitbrief_core.compiler.packs.professional_services_text.compile_retrieval_exemplars import CompiledRetrievalExemplarTable, compile_retrieval_exemplars
from orbitbrief_core.compiler.packs.professional_services_text.compile_review_rule_table import (
    CompiledReviewRuleTable,
    compile_review_rule_table,
)
from orbitbrief_core.compiler.packs.professional_services_text.load_compiled_pack import (
    CompiledPack,
    load_compiled_pack as _load_compiled_pack,
)
from orbitbrief_core.compiler.packs.professional_services_text.serialize_pack import write_compiled_pack


@dataclass(frozen=True)
class CompiledPackArtifacts:
    raw: RawContractsBundle
    resolved: ResolvedContractsBundle
    ir: CanonicalIR
    field_table: CompiledFieldTable
    claim_family_table: CompiledClaimFamilyTable
    review_rule_table: CompiledReviewRuleTable
    projection_rule_table: CompiledProjectionRuleTable
    allowed_masks: CompiledAllowedMasks
    parser_profiles: CompiledParserProfileTable
    negative_examples: CompiledNegativeExampleTable
    retrieval_exemplars: CompiledRetrievalExemplarTable
    contract_input_paths: tuple[Path, ...]
    strict_mask_alignment_enforced: bool


def _default_curated_examples_path(paths: PackContractPaths) -> Path:
    machine_dir = paths.enhanced_machine_path.parent
    return machine_dir / "professional_services_text_examples.yaml"


def _boundary_hardening_dir(paths: PackContractPaths) -> Path:
    return paths.enhanced_machine_path.parent.parent / "boundary_hardening"


def _autodiscover_boundary_paths(paths: PackContractPaths) -> tuple[Path | None, Path | None, tuple[Path, ...]]:
    boundary_dir = _boundary_hardening_dir(paths)
    discovered_inputs: list[Path] = []
    scope_path = paths.scope_contract_path
    handoff_path = paths.handoff_contract_path

    default_scope = boundary_dir / "professional_services_text_scope_block.yaml"
    default_handoff = boundary_dir / "professional_services_text_handoff_contract.yaml"
    machine_patch = boundary_dir / "professional_services_text_machine_patch.yaml"

    if scope_path is None and default_scope.exists():
        scope_path = default_scope
        discovered_inputs.append(default_scope)
    if handoff_path is None and default_handoff.exists():
        handoff_path = default_handoff
        discovered_inputs.append(default_handoff)

    if (scope_path is None or handoff_path is None) and machine_patch.exists():
        patch_data = yaml.safe_load(machine_patch.read_text(encoding="utf-8"))
        if isinstance(patch_data, dict):
            tmp_root = Path(tempfile.mkdtemp(prefix="orbitbrief_scope_handoff_"))
            if scope_path is None and isinstance(patch_data.get("scope"), dict):
                extracted_scope = tmp_root / "scope_from_machine_patch.yaml"
                extracted_scope.write_text(yaml.safe_dump({"scope": patch_data["scope"]}, sort_keys=False), encoding="utf-8")
                scope_path = extracted_scope
                discovered_inputs.append(machine_patch)
            if handoff_path is None and isinstance(patch_data.get("routing_handoff_contract"), dict):
                extracted_handoff = tmp_root / "handoff_from_machine_patch.yaml"
                extracted_handoff.write_text(
                    yaml.safe_dump({"routing_handoff_contract": patch_data["routing_handoff_contract"]}, sort_keys=False),
                    encoding="utf-8",
                )
                handoff_path = extracted_handoff
                if machine_patch not in discovered_inputs:
                    discovered_inputs.append(machine_patch)

    return scope_path, handoff_path, tuple(sorted(set(discovered_inputs)))


def _effective_paths(paths: PackContractPaths) -> tuple[PackContractPaths, tuple[Path, ...]]:
    scope_path, handoff_path, discovered = _autodiscover_boundary_paths(paths)
    return (
        PackContractPaths(
            pack_id=paths.pack_id,
            source_contracts_path=paths.source_contracts_path,
            field_catalog_path=paths.field_catalog_path,
            enhanced_machine_path=paths.enhanced_machine_path,
            rich_modalities_path=paths.rich_modalities_path,
            scope_contract_path=scope_path,
            handoff_contract_path=handoff_path,
        ),
        discovered,
    )


def compile_pack(
    paths: PackContractPaths,
    *,
    curated_examples_paths: Sequence[Path] | None = None,
    semantic_contract_paths: Sequence[Path] | None = None,
    strict_mask_alignment: bool = True,
) -> CompiledPackArtifacts:
    effective_paths, discovered_inputs = _effective_paths(paths)
    raw = load_raw_contracts(effective_paths)
    resolved = resolve_precedence(raw)
    ir = build_canonical_ir(resolved)

    field_table = compile_field_table(ir)
    claim_family_table = compile_claim_family_table(ir)
    review_rule_table = compile_review_rule_table(ir)
    projection_rule_table = compile_projection_rule_table(ir)
    allowed_masks = compile_allowed_masks(
        ir,
        field_table,
        claim_family_table,
        review_rule_table,
        projection_rule_table,
    )
    parser_profiles = compile_parser_profile_table(ir, allowed_masks, strict_mask_alignment=strict_mask_alignment)

    default_curated = _default_curated_examples_path(effective_paths)
    curated_paths = (
        tuple(curated_examples_paths)
        if curated_examples_paths is not None
        else ((default_curated,) if default_curated.exists() else ())
    )
    semantic_paths = (
        tuple(semantic_contract_paths)
        if semantic_contract_paths is not None
        else (
            effective_paths.enhanced_machine_path,
            effective_paths.rich_modalities_path,
            effective_paths.field_catalog_path,
            effective_paths.source_contracts_path,
            *( (effective_paths.scope_contract_path,) if effective_paths.scope_contract_path is not None else () ),
            *( (effective_paths.handoff_contract_path,) if effective_paths.handoff_contract_path is not None else () ),
            *discovered_inputs,
        )
    )
    negative_examples = compile_negative_examples(
        ir,
        curated_examples_paths=curated_paths,
        semantic_contract_paths=semantic_paths,
    )
    retrieval_exemplars = compile_retrieval_exemplars(
        ir,
        curated_examples_paths=curated_paths,
        semantic_contract_paths=semantic_paths,
    )

    return CompiledPackArtifacts(
        raw=raw,
        resolved=resolved,
        ir=ir,
        field_table=field_table,
        claim_family_table=claim_family_table,
        review_rule_table=review_rule_table,
        projection_rule_table=projection_rule_table,
        allowed_masks=allowed_masks,
        parser_profiles=parser_profiles,
        negative_examples=negative_examples,
        retrieval_exemplars=retrieval_exemplars,
        contract_input_paths=tuple(
            sorted(
                {
                    *curated_paths,
                    *semantic_paths,
                    *discovered_inputs,
                }
            )
        ),
        strict_mask_alignment_enforced=strict_mask_alignment,
    )

def emit_compiled_pack(
    artifacts: CompiledPackArtifacts,
    compiled_root: Path,
    *,
    pack_version: str = "v1",
) -> Path:
    return write_compiled_pack(artifacts, compiled_root=compiled_root, pack_version=pack_version)


def load_compiled_pack(
    pack_id: str,
    *,
    compiled_root: Path | None = None,
    pack_version: str = "v1",
) -> CompiledPack:
    root = compiled_root or (Path.cwd() / "compiled_artifacts")
    return _load_compiled_pack(pack_id, compiled_root=root, pack_version=pack_version)


def _print_report_line(line: str) -> None:
    print(line, flush=True)


def _collect_warnings_from_payload(payload: Mapping[str, Any] | None) -> list[str]:
    out: list[str] = []
    if not isinstance(payload, dict):
        return out
    rows = payload.get("rows")
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            level = str(row.get("level", "")).lower()
            if level in {"warning", "info"}:
                code = str(row.get("code", "unknown_code"))
                msg = str(row.get("message", ""))
                out.append(f"{level}:{code}: {msg}")
    return out


def run_compile_and_validate(paths: PackContractPaths, *, output_root: Path, pack_version: str) -> bool:
    effective_paths, discovered_inputs = _effective_paths(paths)
    _print_report_line("PACK BUILD REPORT")
    _print_report_line(f"pack_id: {effective_paths.pack_id}")
    _print_report_line(f"pack_version: {pack_version}")
    _print_report_line("compiler_version: canonical_ir.v1")
    _print_report_line(f"output_dir: {output_root / paths.pack_id / pack_version}")
    _print_report_line("")

    _print_report_line("SOURCE LOAD")
    sources = [
        effective_paths.source_contracts_path,
        effective_paths.field_catalog_path,
        effective_paths.enhanced_machine_path,
        effective_paths.rich_modalities_path,
        effective_paths.scope_contract_path,
        effective_paths.handoff_contract_path,
        *discovered_inputs,
    ]
    for source in sorted({s for s in sources if s is not None}):
        status = "[OK]" if source.exists() else "[MISSING]"
        _print_report_line(f"{status} {source}")
    _print_report_line("")

    try:
        artifacts = compile_pack(paths, strict_mask_alignment=True)
        manifest_path = emit_compiled_pack(artifacts, output_root, pack_version=pack_version)
        loaded = load_compiled_pack(effective_paths.pack_id, compiled_root=output_root, pack_version=pack_version)
    except Exception as exc:
        _print_report_line("FINAL RESULT")
        _print_report_line("STATUS: FAIL")
        _print_report_line("READY_FOR_PARSERS: NO")
        _print_report_line(f"BLOCKER: {type(exc).__name__}: {exc}")
        return False

    _print_report_line("CANONICAL IR")
    _print_report_line(f"pack_id: {artifacts.ir.manifest.pack_id}")
    _print_report_line(f"artifact_family: {artifacts.ir.manifest.artifact_family}")
    _print_report_line(f"role_id: {artifacts.ir.manifest.role_id}")
    _print_report_line(f"modalities: {', '.join(artifacts.ir.manifest.admitted_modalities)}")
    _print_report_line(f"field_count: {len(artifacts.ir.fields)}")
    _print_report_line(f"claim_family_count: {len(artifacts.ir.claim_families)}")
    _print_report_line(f"review_rule_count: {len(artifacts.ir.review_rules)}")
    _print_report_line(f"projection_rule_count: {len(artifacts.ir.projection_rules)}")
    _print_report_line(f"parser_profile_count: {len(artifacts.ir.parser_profiles)}")
    _print_report_line("")

    _print_report_line("COMPILED ARTIFACTS")
    _print_report_line(f"field_table rows: {len(artifacts.field_table.rows)}")
    _print_report_line(f"claim_family_table rows: {len(artifacts.claim_family_table.rows)}")
    _print_report_line(f"review_rules rows: {len(artifacts.review_rule_table.rows)}")
    _print_report_line(f"projection_rules rows: {len(artifacts.projection_rule_table.rows)}")
    _print_report_line(f"allowed_field_masks rows: {len(artifacts.allowed_masks.masks)}")
    _print_report_line(f"parser_profiles rows: {len(artifacts.parser_profiles.rows)}")
    _print_report_line(f"negative_examples rows: {len(artifacts.negative_examples.rows)}")
    _print_report_line(f"retrieval_exemplars rows: {len(artifacts.retrieval_exemplars.rows)}")
    _print_report_line("")

    _print_report_line("SERIALIZATION")
    _print_report_line(f"[OK] manifest: {manifest_path}")
    for name, desc in loaded.manifest.artifacts.items():
        _print_report_line(f"[OK] {name}: {desc.filename}")
    _print_report_line("")

    _print_report_line("LOAD_COMPILED_PACK")
    _print_report_line("[OK] manifest loaded")
    _print_report_line("[OK] all artifact files found")
    _print_report_line("[OK] hash validation passed")
    _print_report_line("[OK] row_count validation passed")
    _print_report_line("[OK] cross-artifact reference validation passed")
    _print_report_line("")

    all_warnings = set(loaded.warnings)
    all_warnings.update(_collect_warnings_from_payload(loaded.diagnostics))
    for artifact_payload in (
        loaded.field_table,
        loaded.claim_family_table,
        loaded.review_rules,
        loaded.projection_rules,
        loaded.allowed_field_masks,
        loaded.parser_profiles,
        loaded.negative_examples,
        loaded.retrieval_exemplars,
    ):
        all_warnings.update(_collect_warnings_from_payload(artifact_payload))
    if len(artifacts.projection_rule_table.rows) == 0:
        all_warnings.add("warning:projection_rules.empty: projection rules artifact is empty for this pack build")
    _print_report_line("WARNINGS")
    if all_warnings:
        for warning in sorted(all_warnings):
            _print_report_line(f"- {warning}")
    else:
        _print_report_line("- none")
    _print_report_line("")

    _print_report_line("FINAL RESULT")
    _print_report_line("STATUS: PASS")
    _print_report_line("READY_FOR_PARSERS: YES")
    return True


def _build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compile and validate professional_services_text pack.")
    parser.add_argument("--pack", default="professional_services_text")
    parser.add_argument("--version", default="v1")
    parser.add_argument("--output", required=True, help="Compiled artifact root directory.")
    parser.add_argument("--source-contracts", required=True)
    parser.add_argument("--field-catalog", required=True)
    parser.add_argument("--enhanced-machine", required=True)
    parser.add_argument("--rich-modalities", required=True)
    parser.add_argument("--scope-contract")
    parser.add_argument("--handoff-contract")
    return parser


def main() -> int:
    args = _build_cli().parse_args()
    paths = PackContractPaths(
        pack_id=args.pack,
        source_contracts_path=Path(args.source_contracts),
        field_catalog_path=Path(args.field_catalog),
        enhanced_machine_path=Path(args.enhanced_machine),
        rich_modalities_path=Path(args.rich_modalities),
        scope_contract_path=Path(args.scope_contract) if args.scope_contract else None,
        handoff_contract_path=Path(args.handoff_contract) if args.handoff_contract else None,
    )
    ok = run_compile_and_validate(paths, output_root=Path(args.output), pack_version=args.version)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
