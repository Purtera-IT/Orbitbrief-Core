from __future__ import annotations

from dataclasses import dataclass

import pytest

from orbitbrief_core.parser.registry import RegistryDispatchError, build_default_registry
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
    registry = build_default_registry()
    plan = _plan(modality="txt", discourse=DiscourseType.CALL_TRANSCRIPT, strategy_chain=("call_transcript",))
    registry.validate_plan(plan, strict=True)
    adapter = registry.get_adapter(plan)
    assert adapter.info.modality == "txt"
    assert registry.strategy_chain(plan, strict=True)[0].name == "call_transcript"


def test_default_registry_rejects_incompatible_plan() -> None:
    registry = build_default_registry()
    plan = _plan(modality="pdf_ocr", discourse=DiscourseType.EMAIL_THREAD, strategy_chain=("email_thread",))
    with pytest.raises(RegistryDispatchError):
        registry.validate_plan(plan, strict=True)
