from __future__ import annotations

from pathlib import Path

import pytest

from orbitbrief_core.compiler.core.load_contracts import PackContractPaths
from orbitbrief_core.compiler.packs.professional_services_text.compiler_runner import (
    compile_pack,
    emit_compiled_pack,
    load_compiled_pack,
)


def test_real_bundle_compile_and_load_strict() -> None:
    workspace = Path("/Users/purtera/dev/purtera")
    source_contracts = workspace / "Shared-contracts/contracts/orbitbrief/professional_services/transcript_or_notes/base/source/managed_services_base_source_contracts.json"
    field_catalog = workspace / "Shared-contracts/contracts/orbitbrief/professional_services/transcript_or_notes/base/source/managed_services_base_precise_field_catalog.json"
    enhanced_machine = workspace / "Shared-contracts/contracts/orbitbrief/professional_services/transcript_or_notes/base/machine/professional_services_text_enhanced_machine.yaml"
    rich_modalities = workspace / "Shared-contracts/contracts/orbitbrief/professional_services/transcript_or_notes/base/machine/professional_services_text_rich_all_modalities.yaml"
    required = (source_contracts, field_catalog, enhanced_machine, rich_modalities)
    if not all(path.exists() for path in required):
        pytest.skip("Real bundle contracts not available in this environment.")

    paths = PackContractPaths(
        pack_id="professional_services_text",
        source_contracts_path=source_contracts,
        field_catalog_path=field_catalog,
        enhanced_machine_path=enhanced_machine,
        rich_modalities_path=rich_modalities,
    )
    artifacts = compile_pack(paths, strict_mask_alignment=True)
    out_root = Path("/tmp/compiled_artifacts_real_bundle_test")
    emit_compiled_pack(artifacts, out_root)
    loaded = load_compiled_pack("professional_services_text", compiled_root=out_root)

    assert loaded.manifest.pack_id == "professional_services_text"
    assert loaded.manifest.capabilities.get("strict_mask_alignment_enforced") is True
    assert any(path.endswith("professional_services_text_scope_block.yaml") for path in loaded.manifest.source_paths)
    assert any(path.endswith("professional_services_text_handoff_contract.yaml") for path in loaded.manifest.source_paths)
