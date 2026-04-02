from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Generic, Literal, Mapping, TypeVar

from .load_contracts import ContractLoadError, FrozenJSONLike, RawContractsBundle

ResolutionStrategy = Literal[
    "authoritative_override",
    "fallback_merge",
    "exclusive_source",
    "conflict_error",
]
DiagnosticLevel = Literal["info", "warning", "error"]
T = TypeVar("T")

CONCERNS: tuple[str, ...] = (
    "scope",
    "handoff",
    "source_inventory",
    "modalities",
    "field_legality",
    "field_semantics",
    "claim_family_semantics",
    "parser_profiles",
    "review_rules",
    "projection_rules",
    "structural_defaults",
)

_FIELD_REF_KEYS: frozenset[str] = frozenset(
    {
        "field",
        "fields",
        "field_name",
        "field_names",
        "field_path",
        "field_paths",
        "target_field",
        "target_fields",
        "target_path",
        "target_paths",
        "emits",
        "maps_to",
    }
)

_FORBIDDEN_CATEGORY_HINTS: dict[str, tuple[str, ...]] = {
    "spreadsheet": ("spreadsheet", "row", "roster", "tabular"),
    "drawing": ("drawing", "dwg", "esx", "cad"),
    "execution": ("execution", "field execution", "authoritative report"),
}
_FORBIDDEN_FIELD_PREFIXES: dict[str, tuple[str, ...]] = {
    "spreadsheet": ("site_roster_rows",),
    "drawing": ("drawing", "diagram", "vector"),
    "execution": ("field_execution_report",),
}
_FORBIDDEN_MODALITY_NAMES: dict[str, tuple[str, ...]] = {
    "spreadsheet": ("csv", "xlsx", "xls"),
    "drawing": ("dwg_export_pdf", "esx", "cad", "dwg"),
    "execution": ("execution_report_pdf",),
}


@dataclass(frozen=True)
class ResolutionRecord:
    concern: str
    winner_role: str
    loser_roles: tuple[str, ...]
    strategy: ResolutionStrategy
    source_paths: tuple[str, ...]
    notes: str | None = None


@dataclass(frozen=True)
class Diagnostic:
    level: DiagnosticLevel
    code: str
    message: str
    concern: str | None = None
    context: Mapping[str, FrozenJSONLike] | None = None


@dataclass(frozen=True)
class ConcernResolution(Generic[T]):
    concern: str
    value: T
    record: ResolutionRecord
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True)
class ScopeContract:
    pack_id: str
    artifact_family: str
    role_id: str
    authoritative_for: tuple[str, ...]
    not_authoritative_for: tuple[str, ...]
    routes_to_follow_on_packs: tuple[str, ...]
    primary_outputs: tuple[str, ...]
    auxiliary_outputs: tuple[str, ...]
    raw: Mapping[str, FrozenJSONLike]


@dataclass(frozen=True)
class HandoffContract:
    candidate_domain_overlays: tuple[str, ...]
    follow_on_artifact_requests: tuple[str, ...]
    authority_needed_flags: tuple[str, ...]
    verification_needed_flags: tuple[str, ...]
    cross_pack_entities: tuple[str, ...]
    raw: Mapping[str, FrozenJSONLike]


@dataclass(frozen=True)
class SourceInventorySection:
    modalities: Mapping[str, FrozenJSONLike]
    sources: Mapping[str, FrozenJSONLike]
    raw: Mapping[str, FrozenJSONLike]


@dataclass(frozen=True)
class FieldCatalogSection:
    fields: Mapping[str, FrozenJSONLike]
    pre_field_definitions: Mapping[str, FrozenJSONLike]
    post_field_definitions: Mapping[str, FrozenJSONLike]
    field_paths: tuple[str, ...]
    raw: Mapping[str, FrozenJSONLike]


@dataclass(frozen=True)
class StructuralSections:
    structural_defaults: Mapping[str, FrozenJSONLike]
    modality_profiles: Mapping[str, FrozenJSONLike]
    allowed_field_paths: tuple[str, ...]
    parser_sandwich: Mapping[str, FrozenJSONLike]
    raw: Mapping[str, FrozenJSONLike]


@dataclass(frozen=True)
class SemanticSections:
    field_semantics: Mapping[str, FrozenJSONLike]
    claim_family_semantics: Mapping[str, FrozenJSONLike]
    parser_profiles: Mapping[str, FrozenJSONLike]
    review_rules: Mapping[str, FrozenJSONLike]
    projection_rules: Mapping[str, FrozenJSONLike]
    conversation_rules: Mapping[str, FrozenJSONLike]
    authority_rules: Mapping[str, FrozenJSONLike]
    raw: Mapping[str, FrozenJSONLike]


@dataclass(frozen=True)
class ResolvedContractsBundle:
    pack_id: str
    resolved_scope: ScopeContract
    resolved_handoff: HandoffContract | None
    resolved_source_inventory: SourceInventorySection
    resolved_modalities: Mapping[str, FrozenJSONLike]
    resolved_field_legality: FieldCatalogSection
    resolved_field_semantics: Mapping[str, FrozenJSONLike]
    resolved_claim_family_semantics: Mapping[str, FrozenJSONLike]
    resolved_parser_profiles: Mapping[str, FrozenJSONLike]
    resolved_review_rules: Mapping[str, FrozenJSONLike]
    resolved_projection_rules: Mapping[str, FrozenJSONLike]
    resolved_semantic_sections: SemanticSections
    resolved_structural_defaults: StructuralSections
    resolution_records: tuple[ResolutionRecord, ...] = field(default_factory=tuple)
    diagnostics: tuple[Diagnostic, ...] = field(default_factory=tuple)

    @property
    def resolved_field_catalog(self) -> Mapping[str, FrozenJSONLike]:
        return self.resolved_field_legality.raw


def _freeze(value: Any) -> FrozenJSONLike:
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, tuple):
        return tuple(_freeze(v) for v in value)
    return value


def _as_mapping(value: Any) -> Mapping[str, FrozenJSONLike]:
    return value if isinstance(value, Mapping) else MappingProxyType({})


def _as_tuple_str(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value if isinstance(v, (str, int, float)))
    return ()


def _collect_field_refs(node: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(node, Mapping):
        for key, value in node.items():
            if str(key).lower() in _FIELD_REF_KEYS:
                if isinstance(value, str):
                    refs.add(value)
                elif isinstance(value, (list, tuple)):
                    refs.update(str(v) for v in value if isinstance(v, str))
            refs.update(_collect_field_refs(value))
    elif isinstance(node, (list, tuple)):
        for item in node:
            refs.update(_collect_field_refs(item))
    return refs


def _normalize_scope_contract(bundle: RawContractsBundle) -> tuple[ScopeContract, str, bool]:
    external = bundle.scope_contract is not None
    source_doc = bundle.scope_contract if external else bundle.enhanced_machine
    embedded = _as_mapping(source_doc.data.get("scope"))
    body = embedded or source_doc.data
    if not external and not embedded:
        raise ContractLoadError("No scope definition found (external scope_contract or embedded scope).")
    pack_id = str(body.get("pack_id", "")).strip()
    role_id = str(body.get("role_id", "")).strip()
    if not pack_id or not role_id:
        raise ContractLoadError("Scope contract must include pack_id and role_id.")
    scope = ScopeContract(
        pack_id=pack_id,
        artifact_family=str(body.get("artifact_family", bundle.pack_id)).strip() or bundle.pack_id,
        role_id=role_id,
        authoritative_for=_as_tuple_str(body.get("authoritative_for")),
        not_authoritative_for=_as_tuple_str(body.get("not_authoritative_for")),
        routes_to_follow_on_packs=_as_tuple_str(body.get("routes_to_follow_on_packs")),
        primary_outputs=_as_tuple_str(body.get("primary_outputs")),
        auxiliary_outputs=_as_tuple_str(body.get("auxiliary_outputs")),
        raw=_freeze(dict(body)),
    )
    return scope, str(source_doc.metadata.path), external


def _normalize_handoff_contract(bundle: RawContractsBundle) -> tuple[HandoffContract | None, str | None, bool]:
    external = bundle.handoff_contract is not None
    if external:
        source_doc = bundle.handoff_contract
        body = _as_mapping(source_doc.data.get("routing_handoff_contract")) or source_doc.data
    else:
        source_doc = bundle.enhanced_machine
        body = _as_mapping(source_doc.data.get("routing_handoff_contract"))
        if not body:
            return None, None, False
    handoff = HandoffContract(
        candidate_domain_overlays=_as_tuple_str(body.get("candidate_domain_overlays")),
        follow_on_artifact_requests=_as_tuple_str(body.get("follow_on_artifact_requests")),
        authority_needed_flags=_as_tuple_str(body.get("authority_needed_flags")),
        verification_needed_flags=_as_tuple_str(body.get("verification_needed_flags")),
        cross_pack_entities=_as_tuple_str(body.get("cross_pack_entities")),
        raw=_freeze(dict(body)),
    )
    return handoff, str(source_doc.metadata.path), external


def _normalize_source_inventory(bundle: RawContractsBundle) -> SourceInventorySection:
    raw = bundle.source_contracts.data
    return SourceInventorySection(
        modalities=_as_mapping(raw.get("modalities")) or _as_mapping(raw.get("narrative_modalities")),
        sources=_as_mapping(raw.get("sources")) or _as_mapping(raw.get("source_contracts")),
        raw=raw,
    )


def _normalize_field_catalog(bundle: RawContractsBundle) -> FieldCatalogSection:
    raw = bundle.field_catalog.data
    fields = _as_mapping(raw.get("fields")) or _as_mapping(raw.get("field_catalog"))
    pre = _as_mapping(raw.get("pre_field_definitions")) or _as_mapping(raw.get("rich_base_pre"))
    post = _as_mapping(raw.get("post_field_definitions")) or _as_mapping(raw.get("fixed_post"))
    if not fields:
        derived_fields: dict[str, FrozenJSONLike] = {}
        for name, payload in pre.items():
            payload_map = _as_mapping(payload)
            merged = dict(payload_map)
            merged.setdefault("pre_or_post", "pre")
            derived_fields[str(name)] = _freeze(merged)
        for name, payload in post.items():
            payload_map = _as_mapping(payload)
            merged = dict(payload_map)
            merged.setdefault("pre_or_post", "post")
            derived_fields[str(name)] = _freeze(merged)
        fields = MappingProxyType(derived_fields)
    paths = set(str(k) for k in fields.keys())
    paths.update(str(k) for k in pre.keys())
    paths.update(str(k) for k in post.keys())
    for key in ("field_paths", "allowed_field_paths"):
        value = raw.get(key)
        if isinstance(value, (list, tuple)):
            paths.update(str(v) for v in value if isinstance(v, str))
    return FieldCatalogSection(fields=fields, pre_field_definitions=pre, post_field_definitions=post, field_paths=tuple(sorted(paths)), raw=raw)


def _normalize_structural_sections(bundle: RawContractsBundle) -> StructuralSections:
    raw = bundle.rich_modalities.data
    modality_profiles = _as_mapping(raw.get("modality_profiles")) or _as_mapping(raw.get("modalities"))
    field_index = _as_mapping(raw.get("field_path_index"))
    allowed: set[str] = set()
    for value in field_index.values():
        if isinstance(value, (list, tuple)):
            allowed.update(str(v) for v in value if isinstance(v, str))
    return StructuralSections(
        structural_defaults=_as_mapping(raw.get("structural_defaults")) or _as_mapping(raw.get("schema_views")) or field_index,
        modality_profiles=modality_profiles,
        allowed_field_paths=tuple(sorted(allowed)),
        parser_sandwich=_as_mapping(raw.get("parser_sandwich")),
        raw=raw,
    )


def _normalize_semantic_sections(bundle: RawContractsBundle) -> SemanticSections:
    raw = bundle.enhanced_machine.data
    field_semantics = (
        _as_mapping(raw.get("field_semantics"))
        or _as_mapping(raw.get("pre_field_definitions"))
        or _as_mapping(raw.get("field_definitions"))
    )
    claim_family_semantics = (
        _as_mapping(raw.get("claim_family_semantics"))
        or _as_mapping(raw.get("claim_family_definitions"))
    )
    parser_profiles = (
        _as_mapping(raw.get("parser_profiles"))
        or _as_mapping(raw.get("modality_profiles"))
        or _as_mapping(raw.get("modalities"))
    )
    review_rules = _as_mapping(raw.get("review_rules")) or _as_mapping(raw.get("review_triggers"))
    projection_rules = (
        _as_mapping(raw.get("projection_rules"))
        or _as_mapping(raw.get("projection"))
        or _as_mapping(raw.get("post_projection_rules"))
    )
    return SemanticSections(
        field_semantics=field_semantics,
        claim_family_semantics=claim_family_semantics,
        parser_profiles=parser_profiles,
        review_rules=review_rules,
        projection_rules=projection_rules,
        conversation_rules=_as_mapping(raw.get("conversation_rules")),
        authority_rules=_as_mapping(raw.get("authority_rules")),
        raw=raw,
    )


def _extract_legal_fields(section: FieldCatalogSection) -> set[str]:
    legal = set(str(k) for k in section.fields.keys())
    legal.update(str(k) for k in section.pre_field_definitions.keys())
    legal.update(str(k) for k in section.post_field_definitions.keys())
    legal.update(section.field_paths)
    return {v for v in legal if v}


def _is_legal_field_ref(ref: str, legal_fields: set[str]) -> bool:
    if ref in legal_fields:
        return True
    if ref.endswith("[]") and ref[:-2] in legal_fields:
        return True
    if not ref.endswith("[]") and f"{ref}[]" in legal_fields:
        return True
    if ref.endswith(".*"):
        prefix = ref[:-2]
        return any(field == prefix or field.startswith(prefix + ".") for field in legal_fields)
    return False


def _resolve_mapping(concern: str, primary: Mapping[str, FrozenJSONLike], fallback: Mapping[str, FrozenJSONLike], primary_path: str, fallback_path: str, fallback_note: str) -> ConcernResolution[Mapping[str, FrozenJSONLike]]:
    if primary:
        return ConcernResolution(concern, primary, ResolutionRecord(concern, "enhanced_machine", ("rich_modalities",), "authoritative_override", (primary_path,)))
    if fallback:
        return ConcernResolution(
            concern,
            fallback,
            ResolutionRecord(concern, "rich_modalities", ("enhanced_machine",), "fallback_merge", (fallback_path,), fallback_note),
            diagnostics=(Diagnostic("warning", f"resolve_precedence.{concern}.fallback_used", fallback_note, concern=concern),),
        )
    return ConcernResolution(concern, MappingProxyType({}), ResolutionRecord(concern, "none", ("enhanced_machine", "rich_modalities"), "exclusive_source", ()))


def _resolve_top_level_concerns(
    bundle: RawContractsBundle,
) -> tuple[
    ScopeContract,
    HandoffContract | None,
    SourceInventorySection,
    Mapping[str, FrozenJSONLike],
    FieldCatalogSection,
    StructuralSections,
    list[ResolutionRecord],
    list[Diagnostic],
]:
    records: list[ResolutionRecord] = []
    diagnostics: list[Diagnostic] = []
    scope, scope_path, scope_external = _normalize_scope_contract(bundle)
    records.append(
        ResolutionRecord(
            "scope",
            "scope_contract" if scope_external else "enhanced_machine",
            ("enhanced_machine",) if scope_external else (),
            "authoritative_override" if scope_external else "exclusive_source",
            (scope_path,),
        )
    )

    handoff, handoff_path, handoff_external = _normalize_handoff_contract(bundle)
    if handoff is None:
        records.append(ResolutionRecord("handoff", "none", (), "exclusive_source", (), "No handoff contract supplied."))
        diagnostics.append(
            Diagnostic(
                "warning",
                "resolve_precedence.handoff_missing",
                "No handoff contract present; routing metadata will be absent.",
                concern="handoff",
            )
        )
    else:
        records.append(
            ResolutionRecord(
                "handoff",
                "handoff_contract" if handoff_external else "enhanced_machine",
                ("enhanced_machine",) if handoff_external else (),
                "authoritative_override" if handoff_external else "exclusive_source",
                (handoff_path,) if handoff_path else (),
            )
        )

    source = _normalize_source_inventory(bundle)
    modalities = source.modalities
    records.append(
        ResolutionRecord(
            "source_inventory",
            "source_contracts",
            (),
            "exclusive_source",
            (str(bundle.source_contracts.metadata.path),),
        )
    )
    records.append(
        ResolutionRecord(
            "modalities",
            "source_contracts",
            ("enhanced_machine", "rich_modalities"),
            "authoritative_override",
            (str(bundle.source_contracts.metadata.path),),
        )
    )

    legality = _normalize_field_catalog(bundle)
    records.append(
        ResolutionRecord(
            "field_legality",
            "field_catalog",
            ("enhanced_machine", "rich_modalities"),
            "authoritative_override",
            (str(bundle.field_catalog.metadata.path),),
        )
    )
    structural = _normalize_structural_sections(bundle)
    records.append(
        ResolutionRecord(
            "structural_defaults",
            "rich_modalities",
            (),
            "exclusive_source",
            (str(bundle.rich_modalities.metadata.path),),
        )
    )
    return scope, handoff, source, modalities, legality, structural, records, diagnostics


def _resolve_semantic_concerns(
    bundle: RawContractsBundle,
    structural: StructuralSections,
) -> tuple[
    ConcernResolution[Mapping[str, FrozenJSONLike]],
    ConcernResolution[Mapping[str, FrozenJSONLike]],
    ConcernResolution[Mapping[str, FrozenJSONLike]],
    ConcernResolution[Mapping[str, FrozenJSONLike]],
    ConcernResolution[Mapping[str, FrozenJSONLike]],
]:
    semantic_sections = _normalize_semantic_sections(bundle)
    field_sem = _resolve_mapping(
        "field_semantics",
        semantic_sections.field_semantics,
        structural.structural_defaults,
        str(bundle.enhanced_machine.metadata.path),
        str(bundle.rich_modalities.metadata.path),
        "Used structural defaults as fallback for field semantics.",
    )
    claim_sem = _resolve_mapping(
        "claim_family_semantics",
        semantic_sections.claim_family_semantics,
        _as_mapping(structural.raw.get("claim_family_definitions")),
        str(bundle.enhanced_machine.metadata.path),
        str(bundle.rich_modalities.metadata.path),
        "Used structural claim-family fallback because enhanced machine was silent.",
    )
    parser_primary = semantic_sections.parser_profiles
    parser_profiles = dict(parser_primary)
    fallback_used = False
    for k, v in structural.modality_profiles.items():
        if k not in parser_profiles:
            parser_profiles[str(k)] = v
            fallback_used = True
    parser_result = ConcernResolution(
        "parser_profiles",
        _freeze(parser_profiles),
        ResolutionRecord(
            "parser_profiles",
            "enhanced_machine" if parser_primary else "rich_modalities",
            ("rich_modalities",) if parser_primary else ("enhanced_machine",),
            "fallback_merge" if fallback_used else ("authoritative_override" if parser_primary else "exclusive_source"),
            (str(bundle.enhanced_machine.metadata.path), str(bundle.rich_modalities.metadata.path)),
        ),
        diagnostics=(
            (
                Diagnostic(
                    "warning",
                    "resolve_precedence.parser_profiles.fallback_used",
                    "Fallback parser profiles filled missing semantic profiles.",
                    concern="parser_profiles",
                ),
            )
            if fallback_used
            else ()
        ),
    )
    review_sem = _resolve_mapping(
        "review_rules",
        semantic_sections.review_rules,
        _as_mapping(structural.raw.get("review_triggers")),
        str(bundle.enhanced_machine.metadata.path),
        str(bundle.rich_modalities.metadata.path),
        "Enhanced review rules missing; used structural review fallback.",
    )
    projection_sem = _resolve_mapping(
        "projection_rules",
        semantic_sections.projection_rules,
        _as_mapping(structural.raw.get("projection_rules")) or _as_mapping(structural.raw.get("post_projection_rules")),
        str(bundle.enhanced_machine.metadata.path),
        str(bundle.rich_modalities.metadata.path),
        "Enhanced projection rules missing; used structural fallback.",
    )
    return field_sem, claim_sem, parser_result, review_sem, projection_sem


def _build_resolution_summary_diagnostic(
    *,
    scope: ScopeContract,
    modalities: Mapping[str, FrozenJSONLike],
    legality: FieldCatalogSection,
    parser_profiles: Mapping[str, FrozenJSONLike],
    fallback_concerns: list[str],
    missing_optional: list[str],
) -> Diagnostic:
    legal_fields = _extract_legal_fields(legality)
    referenced_fields = len(_collect_field_refs(parser_profiles))
    return Diagnostic(
        level="info",
        code="resolve_precedence.v2.summary",
        message="Resolution summary for managed services text pack.",
        concern="summary",
        context=_freeze(
            {
                "scope_pack_id": scope.pack_id,
                "admitted_modalities": len(modalities),
                "specialized_modalities": len(parser_profiles),
                "legal_fields": len(legal_fields),
                "referenced_fields": referenced_fields,
                "fallback_used_for": fallback_concerns,
                "missing_optional_concerns": missing_optional,
            }
        ),
    )


def resolve_precedence(bundle: RawContractsBundle) -> ResolvedContractsBundle:
    records: list[ResolutionRecord] = []
    diagnostics: list[Diagnostic] = []

    scope, handoff, source, modalities, legality, structural, base_records, base_diagnostics = _resolve_top_level_concerns(bundle)
    records.extend(base_records)
    diagnostics.extend(base_diagnostics)

    field_sem, claim_sem, parser_result, review_sem, projection_sem = _resolve_semantic_concerns(bundle, structural)
    records.extend([field_sem.record, claim_sem.record, parser_result.record, review_sem.record, projection_sem.record])
    diagnostics.extend(field_sem.diagnostics + claim_sem.diagnostics + parser_result.diagnostics + review_sem.diagnostics + projection_sem.diagnostics)

    if scope.pack_id != bundle.pack_id:
        raise ContractLoadError(
            f"Scope pack_id '{scope.pack_id}' does not match resolved pack_id '{bundle.pack_id}'."
        )
    if not modalities:
        raise ContractLoadError("No admitted modalities resolved from source inventory.")
    parser_keys = {str(k) for k in parser_result.value.keys()}
    invalid_parser = sorted(parser_keys - set(modalities.keys()))
    if invalid_parser:
        raise ContractLoadError(f"Parser profiles reference unknown modalities: {invalid_parser}")

    forbidden_phrase = " ".join(scope.not_authoritative_for).lower()
    active_categories = [cat for cat, hints in _FORBIDDEN_CATEGORY_HINTS.items() if any(h in forbidden_phrase for h in hints)]
    refs = _collect_field_refs(field_sem.value) | _collect_field_refs(claim_sem.value) | _collect_field_refs(review_sem.value) | _collect_field_refs(projection_sem.value) | set(field_sem.value.keys())
    if active_categories:
        for category in active_categories:
            if any(any(ref.startswith(prefix) for prefix in _FORBIDDEN_FIELD_PREFIXES[category]) for ref in refs):
                raise ContractLoadError(f"Boundary violation: {category} authority leaked through field references.")
            parser_modalities = {str(k).lower() for k in parser_result.value.keys()}
            if any(name in parser_modalities for name in _FORBIDDEN_MODALITY_NAMES[category]):
                raise ContractLoadError(f"Boundary violation: {category} authority leaked through parser modalities.")

    legal = _extract_legal_fields(legality)
    illegal = sorted(ref for ref in refs if not _is_legal_field_ref(ref, legal))
    if illegal:
        raise ContractLoadError(f"Illegal field references detected in resolved sections: {illegal}")

    illegal_paths = sorted(path for path in structural.allowed_field_paths if not _is_legal_field_ref(path, legal))
    if illegal_paths:
        diagnostics.append(
            Diagnostic(
                "warning",
                "resolve_precedence.structural_defaults.illegal_paths",
                "Structural fallback includes paths not present in legal field set.",
                concern="structural_defaults",
                context=_freeze({"illegal_paths": illegal_paths}),
            )
        )

    extras = sorted(set(str(k) for k in structural.modality_profiles.keys()) - parser_keys)
    if extras:
        diagnostics.append(Diagnostic("warning", "resolve_precedence.structural_defaults.unused_modalities", "Structural defaults contain modality profiles not used by resolved parser profiles.", concern="structural_defaults", context=_freeze({"unused_modalities": extras})))
    unspecialized = sorted(set(str(k) for k in modalities.keys()) - parser_keys)
    if unspecialized:
        diagnostics.append(Diagnostic("warning", "resolve_precedence.modalities.unspecialized", "Some admitted modalities are not specialized in parser profiles.", concern="modalities", context=_freeze({"modalities": unspecialized})))
    if handoff is not None:
        overlap = set(scope.primary_outputs) & set(handoff.follow_on_artifact_requests)
        if overlap:
            raise ContractLoadError(f"Cross-concern conflict: primary outputs overlap follow-on requests: {sorted(overlap)}")

    fallback_concerns = [r.concern for r in records if r.strategy == "fallback_merge"]
    missing_optional = ["handoff"] if handoff is None else []
    diagnostics.append(
        _build_resolution_summary_diagnostic(
            scope=scope,
            modalities=modalities,
            legality=legality,
            parser_profiles=parser_result.value,
            fallback_concerns=fallback_concerns,
            missing_optional=missing_optional,
        )
    )
    diagnostics.append(Diagnostic("info", "resolve_precedence.v2.ok", "Section-level precedence resolution completed successfully."))

    normalized_semantic = _normalize_semantic_sections(bundle)
    semantic_sections = SemanticSections(
        field_semantics=field_sem.value,
        claim_family_semantics=claim_sem.value,
        parser_profiles=parser_result.value,
        review_rules=review_sem.value,
        projection_rules=projection_sem.value,
        conversation_rules=normalized_semantic.conversation_rules,
        authority_rules=normalized_semantic.authority_rules,
        raw=bundle.enhanced_machine.data,
    )

    return ResolvedContractsBundle(
        pack_id=bundle.pack_id,
        resolved_scope=scope,
        resolved_handoff=handoff,
        resolved_source_inventory=source,
        resolved_modalities=modalities,
        resolved_field_legality=legality,
        resolved_field_semantics=field_sem.value,
        resolved_claim_family_semantics=claim_sem.value,
        resolved_parser_profiles=parser_result.value,
        resolved_review_rules=review_sem.value,
        resolved_projection_rules=projection_sem.value,
        resolved_semantic_sections=semantic_sections,
        resolved_structural_defaults=structural,
        resolution_records=tuple(records),
        diagnostics=tuple(diagnostics),
    )
