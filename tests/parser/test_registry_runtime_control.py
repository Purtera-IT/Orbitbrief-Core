from __future__ import annotations

from pathlib import Path

import pytest

import orbitbrief_core.parser.runtime as runtime_module
from orbitbrief_core.parser.registry import (
    RegistryDispatchError,
    build_default_strategy_registry,
    load_parser_registry,
)
from orbitbrief_core.parser.router import ParsePlan
from orbitbrief_core.parser.shared.types import ContainerType, DiscourseType


def _plan(*, modality: str, discourse: DiscourseType, strategy_chain: tuple[str, ...]) -> ParsePlan:
    return ParsePlan(
        doc_id="reg_doc_001",
        container_type=ContainerType.TEXT,
        discourse_type=discourse,
        parser_profile_id=f"parser:professional_services_text:{modality}",
        adapter_chain=(modality,),
        strategy_chain=strategy_chain,
        quality_mode="standard",
        authority_mode="test",
        packet_policy="test",
        routing_confidence=0.9,
        route_scores=(),
        route_evidence=(),
        review_flags=(),
        metadata={"modality": modality},
    )


def test_default_registry_supports_known_adapter_and_strategy() -> None:
    registry = load_parser_registry()
    strategy_registry = build_default_strategy_registry()
    plan = _plan(modality="txt", discourse=DiscourseType.CALL_TRANSCRIPT, strategy_chain=("call_transcript",))
    registry.validate_plan(plan)
    adapter = registry.get_adapter(plan)
    assert adapter.info.modality == "txt"
    chain = strategy_registry.strategy_chain(modality="txt", strategy_names=("call_transcript",), strict=True)
    assert chain[0].name == "call_transcript"


def test_default_registry_rejects_incompatible_plan() -> None:
    strategy_registry = build_default_strategy_registry()
    with pytest.raises(RegistryDispatchError):
        strategy_registry.validate(modality="pdf_ocr", strategy_names=("email_thread",), strict=True)


def test_registry_loader_rejects_legacy_adapter_path(tmp_path: Path) -> None:
    cfg = tmp_path / "parser_registry.yaml"
    cfg.write_text(
        """
id: runtime.parsers.registry
version: 1.1.0
status: active
parsers:
  - parser_id: bad_legacy_parser
    modality: txt
    adapter: orbitbrief_core.runtime_spine.parsers.txt:TxtParser
    enabled: true
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(RegistryDispatchError):
        load_parser_registry(cfg)


def test_registry_loader_rejects_duplicate_enabled_modality(tmp_path: Path) -> None:
    cfg = tmp_path / "parser_registry.yaml"
    cfg.write_text(
        """
id: runtime.parsers.registry
version: 1.1.0
status: active
parsers:
  - parser_id: txt_primary
    modality: txt
    adapter: orbitbrief_core.parser.adapters.txt:TxtAdapter
    enabled: true
  - parser_id: txt_shadow
    modality: txt
    adapter: orbitbrief_core.parser.adapters.md:MarkdownAdapter
    enabled: true
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(RegistryDispatchError):
        load_parser_registry(cfg)


def test_runtime_entrypoint_uses_loader_when_registry_not_supplied(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"value": False}
    real_loader = runtime_module.load_parser_registry

    def _wrapped_loader():
        called["value"] = True
        return real_loader()

    monkeypatch.setattr(runtime_module, "load_parser_registry", _wrapped_loader)
    plan = _plan(modality="txt", discourse=DiscourseType.CALL_TRANSCRIPT, strategy_chain=("call_transcript",))
    adapter = runtime_module.get_adapter_for_plan(plan, registry=None, strict=True)
    assert called["value"] is True
    assert adapter.info.modality == "txt"
