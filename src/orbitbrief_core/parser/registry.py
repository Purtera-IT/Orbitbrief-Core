from __future__ import annotations

from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Any, Callable, Mapping

from jsonschema import ValidationError
from jsonschema import validate as jsonschema_validate
import yaml

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
    """Raised when runtime dispatch cannot resolve parser/strategy control plane."""


class NoOpStrategy:
    """Explicit fallback strategy that leaves parse unchanged."""

    name = "noop"

    def apply(self, *, document_parse, parse_plan, compiled_pack):  # noqa: D401
        return document_parse


ALLOWED_CAPABILITY_KEYS = {
    "supports_sections",
    "supports_messages",
    "supports_page_provenance",
    "supports_ocr",
}
_DEPRECATED_ADAPTER_PREFIXES = (
    "orbitbrief_core.runtime_spine.parsers",
    "orbitbrief_core.runtime_spine.parser",
)


@dataclass(frozen=True, slots=True)
class ParserSpec:
    parser_id: str
    modality: str
    adapter: str
    enabled: bool
    version: str | None = None
    strategy_defaults: tuple[str, ...] = ()
    capabilities: Mapping[str, bool] = field(default_factory=dict)
    schema_refs: tuple[str, ...] = ()


@dataclass(slots=True)
class ParserRegistry:
    """Canonical parser-spec + adapter dispatch registry."""

    specs_by_id: dict[str, ParserSpec] = field(default_factory=dict)
    specs_by_modality: dict[str, ParserSpec] = field(default_factory=dict)
    _adapter_factories: dict[str, Callable[[], BaseAdapter]] = field(default_factory=dict, init=False, repr=False)

    def register_spec(self, spec: ParserSpec) -> None:
        if spec.parser_id in self.specs_by_id:
            raise RegistryDispatchError(f"Duplicate parser_id: {spec.parser_id}")
        self.specs_by_id[spec.parser_id] = spec
        if not spec.enabled:
            return
        if spec.modality in self.specs_by_modality:
            raise RegistryDispatchError(f"Duplicate enabled parser modality: {spec.modality}")
        self.specs_by_modality[spec.modality] = spec

    # Registration API
    def register_adapter(self, modality: str, adapter_factory: Callable[[], BaseAdapter] | type) -> None:
        key = modality.strip()
        if not key:
            raise RegistryDispatchError("Adapter modality key cannot be empty.")
        if isinstance(adapter_factory, type):
            self._adapter_factories[key] = adapter_factory  # type: ignore[assignment]
        else:
            self._adapter_factories[key] = adapter_factory

    def supported_modalities(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapter_factories))

    def get(self, parser_id: str) -> ParserSpec:
        spec = self.specs_by_id.get(parser_id)
        if spec is None:
            raise RegistryDispatchError(f"Unknown parser_id: {parser_id}")
        return spec

    def get_by_modality(self, modality: str) -> ParserSpec:
        spec = self.specs_by_modality.get(modality)
        if spec is None:
            raise RegistryDispatchError(f"No enabled parser spec for modality: {modality}")
        return spec

    def all_enabled(self) -> tuple[ParserSpec, ...]:
        return tuple(self.specs_by_modality[modality] for modality in sorted(self.specs_by_modality))

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

    def plan_modality(self, parse_plan: ParsePlan) -> str:
        return self._plan_modality(parse_plan)

    def validate_plan(self, parse_plan: ParsePlan) -> None:
        adapter_key = self._adapter_key_from_plan(parse_plan)
        if adapter_key not in self._adapter_factories:
            available = ", ".join(self.supported_modalities())
            raise RegistryDispatchError(f"Unsupported adapter key {adapter_key!r}. Available adapters: {available}.")
        self.get_by_modality(self._plan_modality(parse_plan))

    def get_adapter(self, parse_plan: ParsePlan) -> BaseAdapter:
        key = self._adapter_key_from_plan(parse_plan)
        factory = self._adapter_factories.get(key)
        if factory is None:
            available = ", ".join(self.supported_modalities())
            raise RegistryDispatchError(f"Unsupported adapter key {key!r}. Available adapters: {available}.")
        return factory()

@dataclass(slots=True)
class StrategyRegistry:
    """Strategy control plane; separate from parser declaration ownership."""

    allow_fallback: bool = True
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

    def register_strategy(self, discourse_key: str | DiscourseType, strategy: BaseStrategy) -> None:
        key = discourse_key.value if isinstance(discourse_key, DiscourseType) else str(discourse_key)
        key = key.strip()
        if not key:
            raise RegistryDispatchError("Strategy discourse key cannot be empty.")
        self._strategies[key] = strategy

    def supported_discourse_types(self) -> tuple[str, ...]:
        return tuple(sorted(self._strategies))

    def validate(self, *, modality: str, strategy_names: tuple[str, ...], strict: bool = True) -> None:
        for strategy_name in strategy_names:
            strategy = self._strategies.get(strategy_name)
            if strategy is None:
                if strict and not self.allow_fallback:
                    available = ", ".join(self.supported_discourse_types())
                    raise RegistryDispatchError(f"Unsupported strategy {strategy_name!r}. Available strategies: {available}.")
                continue
            allowed_modalities = self._compatibility.get(strategy.name)
            if allowed_modalities is not None and modality not in allowed_modalities:
                raise RegistryDispatchError(
                    f"Incompatible plan: modality {modality!r} cannot run strategy {strategy.name!r}."
                )

    def strategy_chain(self, *, modality: str, strategy_names: tuple[str, ...], strict: bool = True) -> tuple[BaseStrategy, ...]:
        self.validate(modality=modality, strategy_names=strategy_names, strict=strict)
        chain: list[BaseStrategy] = []
        for strategy_name in strategy_names:
            strategy = self._strategies.get(strategy_name)
            if strategy is None:
                if self.allow_fallback:
                    chain.append(self._fallback_strategy)
                continue
            chain.append(strategy)
        return tuple(chain)


def _default_registry_yaml_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "runtime" / "parsers" / "parser_registry.yaml"


def _default_registry_schema_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "runtime" / "parsers" / "parser_registry.schema.json"


def _validate_adapter_target(target: str) -> type[BaseAdapter]:
    module_name, sep, attr_name = target.partition(":")
    if not module_name or not sep or not attr_name:
        raise RegistryDispatchError(f"Invalid adapter target {target!r}. Expected 'module.path:ClassName'.")
    if module_name.startswith(_DEPRECATED_ADAPTER_PREFIXES):
        raise RegistryDispatchError(f"Deprecated adapter module path {module_name!r}.")
    try:
        module = import_module(module_name)
    except Exception as exc:  # pragma: no cover - exercised in tests by invalid module path
        raise RegistryDispatchError(f"Failed importing adapter module {module_name!r}: {exc}") from exc
    adapter_cls = getattr(module, attr_name, None)
    if not isinstance(adapter_cls, type):
        raise RegistryDispatchError(f"Adapter target {target!r} did not resolve to a class.")
    return adapter_cls


def _build_spec(raw: Mapping[str, Any], *, seen_ids: set[str]) -> ParserSpec:
    parser_id = str(raw.get("parser_id", "")).strip()
    modality = str(raw.get("modality", "")).strip()
    adapter = str(raw.get("adapter", "")).strip()
    if not parser_id or not modality or not adapter:
        raise RegistryDispatchError("Each parser entry must include parser_id, modality, and adapter.")
    if parser_id in seen_ids:
        raise RegistryDispatchError(f"Duplicate parser_id: {parser_id}")
    seen_ids.add(parser_id)
    capabilities_raw = raw.get("capabilities", {})
    if not isinstance(capabilities_raw, Mapping):
        raise RegistryDispatchError(f"Capabilities for {parser_id} must be an object.")
    unknown_capability_keys = set(capabilities_raw) - ALLOWED_CAPABILITY_KEYS
    if unknown_capability_keys:
        keys = ", ".join(sorted(unknown_capability_keys))
        raise RegistryDispatchError(f"Unknown capability keys for {parser_id}: {keys}")
    _validate_adapter_target(adapter)
    strategy_defaults_raw = raw.get("strategy_defaults", [])
    if not isinstance(strategy_defaults_raw, list):
        raise RegistryDispatchError(f"strategy_defaults for {parser_id} must be a list.")
    schema_refs_raw = raw.get("schema_refs", [])
    if not isinstance(schema_refs_raw, list):
        raise RegistryDispatchError(f"schema_refs for {parser_id} must be a list.")
    return ParserSpec(
        parser_id=parser_id,
        modality=modality,
        adapter=adapter,
        enabled=bool(raw.get("enabled", True)),
        version=str(raw.get("version")).strip() if raw.get("version") is not None else None,
        strategy_defaults=tuple(str(item).strip() for item in strategy_defaults_raw if str(item).strip()),
        capabilities={key: bool(value) for key, value in capabilities_raw.items()},
        schema_refs=tuple(str(item).strip() for item in schema_refs_raw if str(item).strip()),
    )


def load_parser_registry(
    path: str | Path | None = None,
) -> ParserRegistry:
    registry_path = Path(path) if path is not None else _default_registry_yaml_path()
    if not registry_path.exists():
        raise RegistryDispatchError(f"Parser registry config does not exist: {registry_path}")
    raw_yaml = registry_path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw_yaml)
    if not isinstance(data, Mapping):
        raise RegistryDispatchError(f"Parser registry must be a mapping document: {registry_path}")
    schema_path = _default_registry_schema_path()
    if not schema_path.exists():
        raise RegistryDispatchError(f"Parser registry schema does not exist: {schema_path}")
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    try:
        jsonschema_validate(instance=data, schema=schema)
    except ValidationError as exc:
        path_hint = ".".join(str(part) for part in exc.path) if exc.path else "<root>"
        raise RegistryDispatchError(f"Parser registry schema validation failed at {path_hint}: {exc.message}") from exc
    parser_rows = data.get("parsers")
    if not isinstance(parser_rows, list):
        raise RegistryDispatchError("Parser registry must contain a top-level 'parsers' list.")

    registry = ParserRegistry()
    seen_ids: set[str] = set()
    for raw in parser_rows:
        if not isinstance(raw, Mapping):
            raise RegistryDispatchError("Each parser row must be an object.")
        spec = _build_spec(raw, seen_ids=seen_ids)
        registry.register_spec(spec)
        if not spec.enabled:
            continue
        adapter_cls = _validate_adapter_target(spec.adapter)
        registry.register_adapter(spec.modality, adapter_cls)

    return registry


def build_default_strategy_registry(*, allow_fallback: bool = True) -> StrategyRegistry:
    registry = StrategyRegistry(allow_fallback=allow_fallback)
    registry.register_strategy(DiscourseType.CALL_TRANSCRIPT, CallTranscriptStrategy())
    registry.register_strategy("conversation", CallTranscriptStrategy())
    registry.register_strategy(DiscourseType.MEETING_NOTES, MeetingNotesStrategy())
    registry.register_strategy(DiscourseType.EMAIL_THREAD, EmailThreadStrategy())
    registry.register_strategy(DiscourseType.PROJECT_MEMO, ProjectMemoStrategy())
    registry.register_strategy(DiscourseType.HYBRID_NOTES_MEMO, HybridStrategy())
    registry.register_strategy("hybrid", HybridStrategy())
    return registry


def build_default_registry(*, allow_strategy_fallback: bool = True) -> ParserRegistry:
    """Backward-compatible alias; YAML now owns parser declarations."""
    _ = allow_strategy_fallback  # kept for backward-compatible call signatures
    return load_parser_registry()
