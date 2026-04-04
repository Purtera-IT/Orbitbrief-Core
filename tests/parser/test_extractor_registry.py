from __future__ import annotations

from pathlib import Path

import pytest

from orbitbrief_core.runtime_spine import load_extractor_registry
from orbitbrief_core.runtime_spine.extractors.registry import ExtractorRegistryError


def test_extractor_registry_loads_and_resolves_primary_flow() -> None:
    registry = load_extractor_registry()
    spec = registry.resolve(
        role_id="transcript_or_notes",
        modality="txt",
        discourse_type="meeting_notes",
    )
    assert spec.extractor_id == "ps_text_narrative_v1"
    assert spec.emits_business_claims is True


def test_extractor_registry_falls_back_to_intake_only() -> None:
    registry = load_extractor_registry()
    spec = registry.resolve(
        role_id="unknown_role",
        modality="txt",
        discourse_type="meeting_notes",
    )
    assert spec.kind == "intake_only"
    assert spec.emits_business_claims is False


def test_extractor_registry_rejects_duplicate_extractor_id(tmp_path: Path) -> None:
    cfg = tmp_path / "extractor_registry.yaml"
    cfg.write_text(
        """
id: runtime.extractors.registry
version: 1.0.0
status: active
extractors:
  - extractor_id: dup
    role_id: transcript_or_notes
    kind: narrative
    entrypoint: orbitbrief_core.runtime_spine.extractors.runtime_impl:run_narrative_extractor
    supports_modalities: [txt]
    supports_discourse_types: [meeting_notes]
    packet_profile: p1
    emits_business_claims: true
    enabled: true
  - extractor_id: dup
    role_id: intake_only
    kind: intake_only
    entrypoint: orbitbrief_core.runtime_spine.extractors.runtime_impl:run_intake_only_extractor
    supports_modalities: [txt]
    supports_discourse_types: [meeting_notes]
    packet_profile: p2
    emits_business_claims: false
    enabled: true
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(ExtractorRegistryError):
        load_extractor_registry(cfg)


def test_extractor_registry_rejects_enabled_collision(tmp_path: Path) -> None:
    cfg = tmp_path / "extractor_registry.yaml"
    cfg.write_text(
        """
id: runtime.extractors.registry
version: 1.0.0
status: active
extractors:
  - extractor_id: one
    role_id: transcript_or_notes
    kind: narrative
    entrypoint: orbitbrief_core.runtime_spine.extractors.runtime_impl:run_narrative_extractor
    supports_modalities: [txt]
    supports_discourse_types: [meeting_notes]
    packet_profile: p1
    emits_business_claims: true
    enabled: true
  - extractor_id: two
    role_id: transcript_or_notes
    kind: specialized
    entrypoint: orbitbrief_core.runtime_spine.extractors.runtime_impl:run_narrative_extractor
    supports_modalities: [txt]
    supports_discourse_types: [meeting_notes]
    packet_profile: p2
    emits_business_claims: true
    enabled: true
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(ExtractorRegistryError):
        load_extractor_registry(cfg)
