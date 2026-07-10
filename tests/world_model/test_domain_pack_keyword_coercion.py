"""YAML bare numerics must not crash pack keyword scoring."""

from __future__ import annotations

from orbitbrief_core.world_model.registry import DomainPackRegistry


def test_numeric_boosted_keyword_coerced_to_str() -> None:
    # Bare `1099` in YAML becomes int unless quoted; registry must coerce.
    yaml_text = """
packs:
  - id: staff_augmentation
    display_name: Staff Augmentation
    intake_aliases: []
    subdomain_labels: []
    keywords: [staff]
    boosted_keywords: [1099, field_engineer]
"""
    reg = DomainPackRegistry._from_yaml_text(yaml_text)
    pack = reg.get("staff_augmentation")
    assert pack is not None
    assert pack.boosted_keywords == ("1099", "field_engineer")
    assert all(isinstance(k, str) for k in pack.boosted_keywords)


def test_bundled_staff_augmentation_has_1099_token() -> None:
    reg = DomainPackRegistry.load()
    pack = reg.get("staff_augmentation")
    assert pack is not None
    assert "1099" in pack.boosted_keywords
    assert all(isinstance(k, str) for k in (*pack.keywords, *pack.boosted_keywords))
