from __future__ import annotations

from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Any, Callable, Mapping

from jsonschema import ValidationError
from jsonschema import validate as jsonschema_validate
import yaml


class ExtractorRegistryError(RuntimeError):
    """Raised when extractor registry load, validation, or lookup fails."""


_ALLOWED_KINDS = {"narrative", "intake_only", "specialized"}
_DEPRECATED_ENTRYPOINT_PREFIXES = (
    "orbitbrief_core.runtime_spine.parsers",
    "orbitbrief_core.runtime_spine.parser",
)


@dataclass(frozen=True, slots=True)
class ExtractorSpec:
    extractor_id: str
    role_id: str
    kind: str
    entrypoint: str
    supports_modalities: tuple[str, ...]
    supports_discourse_types: tuple[str, ...]
    packet_profile: str
    emits_business_claims: bool
    enabled: bool
    allowed_claim_families: tuple[str, ...] = ()
    allowed_field_paths: tuple[str, ...] = ()
    require_evidence_refs: bool = True
    review_rules: Mapping[str, Any] = field(default_factory=dict)
    version: str | None = None


@dataclass(slots=True)
class ExtractorRegistry:
    """Canonical extractor control plane for role-flow eligibility."""

    specs_by_id: dict[str, ExtractorSpec] = field(default_factory=dict)
    _enabled_specs: list[ExtractorSpec] = field(default_factory=list, init=False, repr=False)

    def register_spec(self, spec: ExtractorSpec) -> None:
        if spec.extractor_id in self.specs_by_id:
            raise ExtractorRegistryError(f"Duplicate extractor_id: {spec.extractor_id}")
        self.specs_by_id[spec.extractor_id] = spec
        if spec.enabled:
            self._enabled_specs.append(spec)

    def all_enabled(self) -> tuple[ExtractorSpec, ...]:
        return tuple(sorted(self._enabled_specs, key=lambda spec: spec.extractor_id))

    def get(self, extractor_id: str) -> ExtractorSpec:
        spec = self.specs_by_id.get(extractor_id)
        if spec is None:
            raise ExtractorRegistryError(f"Unknown extractor_id: {extractor_id}")
        return spec

    def resolve(
        self,
        *,
        role_id: str,
        modality: str,
        discourse_type: str,
        allow_intake_only_fallback: bool = True,
    ) -> ExtractorSpec:
        candidates = [
            spec
            for spec in self._enabled_specs
            if spec.role_id == role_id
            and modality in spec.supports_modalities
            and discourse_type in spec.supports_discourse_types
        ]
        if len(candidates) > 1:
            ids = ", ".join(sorted(spec.extractor_id for spec in candidates))
            raise ExtractorRegistryError(
                f"Ambiguous extractor resolution for role={role_id!r}, modality={modality!r}, discourse={discourse_type!r}: {ids}"
            )
        if len(candidates) == 1:
            return candidates[0]
        if allow_intake_only_fallback:
            fallback = [
                spec
                for spec in self._enabled_specs
                if spec.kind == "intake_only"
                and modality in spec.supports_modalities
                and discourse_type in spec.supports_discourse_types
            ]
            if len(fallback) == 1:
                return fallback[0]
            if len(fallback) > 1:
                ids = ", ".join(sorted(spec.extractor_id for spec in fallback))
                raise ExtractorRegistryError(f"Ambiguous intake_only fallback extractors: {ids}")
        raise ExtractorRegistryError(
            f"No enabled extractor for role={role_id!r}, modality={modality!r}, discourse={discourse_type!r}"
        )


def _default_registry_yaml_path() -> Path:
    return Path(__file__).resolve().parents[4] / "config" / "runtime" / "extractors" / "extractor_registry.yaml"


def _default_registry_schema_path() -> Path:
    return Path(__file__).resolve().parents[4] / "config" / "runtime" / "extractors" / "extractor_registry.schema.json"


def _resolve_entrypoint(entrypoint: str) -> Callable[..., Any]:
    module_name, sep, attr_name = entrypoint.partition(":")
    if not module_name or not sep or not attr_name:
        raise ExtractorRegistryError(f"Invalid entrypoint {entrypoint!r}. Expected 'module.path:callable'.")
    if module_name.startswith(_DEPRECATED_ENTRYPOINT_PREFIXES):
        raise ExtractorRegistryError(f"Deprecated extractor entrypoint module path {module_name!r}.")
    try:
        module = import_module(module_name)
    except Exception as exc:
        raise ExtractorRegistryError(f"Failed importing extractor module {module_name!r}: {exc}") from exc
    attr = getattr(module, attr_name, None)
    if not callable(attr):
        raise ExtractorRegistryError(f"Entrypoint {entrypoint!r} did not resolve to a callable.")
    return attr


def resolve_extractor_entrypoint(entrypoint: str) -> Callable[..., Any]:
    """Public resolver used by runtime orchestration for extractor invocation."""
    return _resolve_entrypoint(entrypoint)


def _build_spec(raw: Mapping[str, Any], *, seen_ids: set[str]) -> ExtractorSpec:
    extractor_id = str(raw.get("extractor_id", "")).strip()
    role_id = str(raw.get("role_id", "")).strip()
    kind = str(raw.get("kind", "")).strip()
    entrypoint = str(raw.get("entrypoint", "")).strip()
    if not extractor_id or not role_id or not kind or not entrypoint:
        raise ExtractorRegistryError("Each extractor row must include extractor_id, role_id, kind, and entrypoint.")
    if extractor_id in seen_ids:
        raise ExtractorRegistryError(f"Duplicate extractor_id: {extractor_id}")
    seen_ids.add(extractor_id)
    if kind not in _ALLOWED_KINDS:
        kinds = ", ".join(sorted(_ALLOWED_KINDS))
        raise ExtractorRegistryError(f"Unsupported extractor kind {kind!r}. Allowed: {kinds}.")
    supports_modalities_raw = raw.get("supports_modalities", [])
    supports_discourse_raw = raw.get("supports_discourse_types", [])
    allowed_claim_families_raw = raw.get("allowed_claim_families", [])
    allowed_field_paths_raw = raw.get("allowed_field_paths", [])
    review_rules_raw = raw.get("review_rules", {})
    if not isinstance(supports_modalities_raw, list) or not supports_modalities_raw:
        raise ExtractorRegistryError(f"supports_modalities for {extractor_id} must be a non-empty list.")
    if not isinstance(supports_discourse_raw, list) or not supports_discourse_raw:
        raise ExtractorRegistryError(f"supports_discourse_types for {extractor_id} must be a non-empty list.")
    if not isinstance(allowed_claim_families_raw, list):
        raise ExtractorRegistryError(f"allowed_claim_families for {extractor_id} must be a list.")
    if not isinstance(allowed_field_paths_raw, list):
        raise ExtractorRegistryError(f"allowed_field_paths for {extractor_id} must be a list.")
    if not isinstance(review_rules_raw, Mapping):
        raise ExtractorRegistryError(f"review_rules for {extractor_id} must be an object.")
    _resolve_entrypoint(entrypoint)
    return ExtractorSpec(
        extractor_id=extractor_id,
        role_id=role_id,
        kind=kind,
        entrypoint=entrypoint,
        supports_modalities=tuple(str(item).strip() for item in supports_modalities_raw if str(item).strip()),
        supports_discourse_types=tuple(str(item).strip() for item in supports_discourse_raw if str(item).strip()),
        packet_profile=str(raw.get("packet_profile", "")).strip(),
        allowed_claim_families=tuple(str(item).strip() for item in allowed_claim_families_raw if str(item).strip()),
        allowed_field_paths=tuple(str(item).strip() for item in allowed_field_paths_raw if str(item).strip()),
        require_evidence_refs=bool(raw.get("require_evidence_refs", True)),
        review_rules={str(key): value for key, value in review_rules_raw.items()},
        emits_business_claims=bool(raw.get("emits_business_claims", False)),
        enabled=bool(raw.get("enabled", True)),
        version=str(raw.get("version")).strip() if raw.get("version") is not None else None,
    )


def _validate_no_dispatch_collisions(registry: ExtractorRegistry) -> None:
    seen: dict[tuple[str, str, str], str] = {}
    for spec in registry.all_enabled():
        for modality in spec.supports_modalities:
            for discourse_type in spec.supports_discourse_types:
                key = (spec.role_id, modality, discourse_type)
                prior = seen.get(key)
                if prior is not None:
                    raise ExtractorRegistryError(
                        f"Duplicate enabled extractor coverage for role={spec.role_id!r}, modality={modality!r}, discourse={discourse_type!r}: "
                        f"{prior}, {spec.extractor_id}"
                    )
                seen[key] = spec.extractor_id


def load_extractor_registry(path: str | Path | None = None) -> ExtractorRegistry:
    registry_path = Path(path) if path is not None else _default_registry_yaml_path()
    if not registry_path.exists():
        raise ExtractorRegistryError(f"Extractor registry config does not exist: {registry_path}")
    data = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ExtractorRegistryError(f"Extractor registry must be a mapping document: {registry_path}")

    schema_path = _default_registry_schema_path()
    if not schema_path.exists():
        raise ExtractorRegistryError(f"Extractor registry schema does not exist: {schema_path}")
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    try:
        jsonschema_validate(instance=data, schema=schema)
    except ValidationError as exc:
        path_hint = ".".join(str(part) for part in exc.path) if exc.path else "<root>"
        raise ExtractorRegistryError(f"Extractor registry schema validation failed at {path_hint}: {exc.message}") from exc

    rows = data.get("extractors")
    if not isinstance(rows, list):
        raise ExtractorRegistryError("Extractor registry must contain a top-level 'extractors' list.")

    registry = ExtractorRegistry()
    seen_ids: set[str] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ExtractorRegistryError("Each extractor row must be an object.")
        spec = _build_spec(raw, seen_ids=seen_ids)
        registry.register_spec(spec)

    _validate_no_dispatch_collisions(registry)
    return registry
