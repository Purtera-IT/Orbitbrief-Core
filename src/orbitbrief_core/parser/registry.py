from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from orbitbrief_core.parser.adapters import ADAPTER_REGISTRY
from orbitbrief_core.parser.adapters.base import BaseAdapter
from orbitbrief_core.parser.router import ParsePlan
from orbitbrief_core.parser.shared.types import DiscourseType
from orbitbrief_core.parser.strategies import (
    BaseStrategy,
    CallTranscriptStrategy,
    EmailThreadStrategy,
    HybridStrategy,
    MeetingNotesStrategy,
    ProjectMemoStrategy,
)


class RegistryDispatchError(RuntimeError):
    """Raised when runtime dispatch cannot resolve adapter/strategy."""


class NoOpStrategy:
    """Explicit fallback strategy that leaves parse unchanged."""

    name = "noop"

    def apply(self, *, document_parse, parse_plan, compiled_pack):  # noqa: D401
        return document_parse


@dataclass(slots=True)
class ParserRegistry:
    """Deterministic adapter/strategy control plane."""

    allow_strategy_fallback: bool = True
    _adapter_factories: dict[str, Callable[[], BaseAdapter]] = field(default_factory=dict, init=False, repr=False)
    _strategies: dict[str, BaseStrategy] = field(default_factory=dict, init=False, repr=False)
    _compatibility: dict[str, set[str]] = field(default_factory=dict, init=False, repr=False)
    _fallback_strategy: BaseStrategy = field(default_factory=NoOpStrategy, init=False, repr=False)

    def __post_init__(self) -> None:
        self._compatibility = {
            "call_transcript": {"txt", "md", "docx", "pdf_text", "pdf_ocr", "pasted_notes", "email_export"},
            "meeting_notes": {"txt", "md", "docx", "pdf_text", "pdf_ocr", "pasted_notes"},
            "email_thread": {"email_export", "txt", "md"},
            "project_memo": {"txt", "md", "docx", "pdf_text", "pdf_ocr", "email_export"},
            "hybrid": {"txt", "md", "docx", "email_export", "pdf_text", "pdf_ocr", "pasted_notes"},
            "noop": {"txt", "md", "docx", "email_export", "pdf_text", "pdf_ocr", "pasted_notes"},
        }

    # Registration API
    def register_adapter(self, modality: str, adapter_factory: Callable[[], BaseAdapter] | type) -> None:
        key = modality.strip()
        if not key:
            raise RegistryDispatchError("Adapter modality key cannot be empty.")
        if isinstance(adapter_factory, type):
            self._adapter_factories[key] = adapter_factory  # type: ignore[assignment]
        else:
            self._adapter_factories[key] = adapter_factory

    def register_strategy(self, discourse_key: str | DiscourseType, strategy: BaseStrategy) -> None:
        key = discourse_key.value if isinstance(discourse_key, DiscourseType) else str(discourse_key)
        key = key.strip()
        if not key:
            raise RegistryDispatchError("Strategy discourse key cannot be empty.")
        self._strategies[key] = strategy

    # Introspection API
    def supported_modalities(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapter_factories))

    def supported_discourse_types(self) -> tuple[str, ...]:
        return tuple(sorted(self._strategies))

    # Dispatch helpers
    @staticmethod
    def _adapter_key_from_plan(parse_plan: ParsePlan) -> str:
        if parse_plan.adapter_chain:
            return parse_plan.adapter_chain[0]
        parser_profile_id = parse_plan.parser_profile_id.strip()
        if parser_profile_id and ":" in parser_profile_id:
            return parser_profile_id.rsplit(":", 1)[-1]
        raise RegistryDispatchError(f"No adapter key resolved for doc_id={parse_plan.doc_id!r}.")

    @staticmethod
    def _plan_modality(parse_plan: ParsePlan) -> str:
        maybe = parse_plan.metadata.get("modality") if isinstance(parse_plan.metadata, Mapping) else None
        if isinstance(maybe, str) and maybe.strip():
            return maybe.strip()
        return ParserRegistry._adapter_key_from_plan(parse_plan)

    def validate_plan(self, parse_plan: ParsePlan, *, strict: bool = True) -> None:
        adapter_key = self._adapter_key_from_plan(parse_plan)
        if adapter_key not in self._adapter_factories:
            available = ", ".join(self.supported_modalities())
            raise RegistryDispatchError(f"Unsupported adapter key {adapter_key!r}. Available adapters: {available}.")

        modality = self._plan_modality(parse_plan)
        for strategy_name in parse_plan.strategy_chain:
            strategy = self._strategies.get(strategy_name)
            if strategy is None:
                if strict and not self.allow_strategy_fallback:
                    available = ", ".join(self.supported_discourse_types())
                    raise RegistryDispatchError(f"Unsupported strategy {strategy_name!r}. Available strategies: {available}.")
                continue
            allowed_modalities = self._compatibility.get(strategy.name)
            if allowed_modalities is not None and modality not in allowed_modalities:
                raise RegistryDispatchError(
                    f"Incompatible plan: modality {modality!r} cannot run strategy {strategy.name!r}."
                )

    def get_adapter(self, parse_plan: ParsePlan) -> BaseAdapter:
        key = self._adapter_key_from_plan(parse_plan)
        factory = self._adapter_factories.get(key)
        if factory is None:
            available = ", ".join(self.supported_modalities())
            raise RegistryDispatchError(f"Unsupported adapter key {key!r}. Available adapters: {available}.")
        return factory()

    def get_strategy(self, parse_plan: ParsePlan, strategy_name: str, *, strict: bool = True) -> BaseStrategy | None:
        strategy = self._strategies.get(strategy_name)
        if strategy is None:
            if strict and not self.allow_strategy_fallback:
                available = ", ".join(self.supported_discourse_types())
                raise RegistryDispatchError(f"Unsupported strategy {strategy_name!r}. Available strategies: {available}.")
            return self._fallback_strategy if self.allow_strategy_fallback else None
        return strategy

    def strategy_chain(self, parse_plan: ParsePlan, *, strict: bool = True) -> tuple[BaseStrategy, ...]:
        chain: list[BaseStrategy] = []
        self.validate_plan(parse_plan, strict=strict)
        for name in parse_plan.strategy_chain:
            strategy = self.get_strategy(parse_plan, name, strict=strict)
            if strategy is not None:
                chain.append(strategy)
        return tuple(chain)


def build_default_registry(*, allow_strategy_fallback: bool = True) -> ParserRegistry:
    registry = ParserRegistry(allow_strategy_fallback=allow_strategy_fallback)
    for modality, adapter_cls in ADAPTER_REGISTRY.items():
        registry.register_adapter(modality, adapter_cls)
    registry.register_strategy(DiscourseType.CALL_TRANSCRIPT, CallTranscriptStrategy())
    registry.register_strategy("conversation", CallTranscriptStrategy())
    registry.register_strategy(DiscourseType.MEETING_NOTES, MeetingNotesStrategy())
    registry.register_strategy(DiscourseType.EMAIL_THREAD, EmailThreadStrategy())
    registry.register_strategy(DiscourseType.PROJECT_MEMO, ProjectMemoStrategy())
    registry.register_strategy(DiscourseType.HYBRID_NOTES_MEMO, HybridStrategy())
    registry.register_strategy("hybrid", HybridStrategy())
    return registry
