from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .load_contracts import ContractLoadError, FrozenJSONLike
from .resolve_precedence import Diagnostic, ResolvedContractsBundle, ResolutionRecord


@dataclass(frozen=True)
class CanonicalManifest:
    pack_id: str
    artifact_family: str
    role_id: str
    compiler_version: str
    admitted_modalities: tuple[str, ...]
    source_hashes: Mapping[str, str]
    source_paths: Mapping[str, str]
    fallback_used_for: tuple[str, ...]
    generated_from_resolution_records: tuple[ResolutionRecord, ...]


@dataclass(frozen=True)
class CanonicalBoundaryContract:
    authoritative_for: tuple[str, ...]
    not_authoritative_for: tuple[str, ...]
    routes_to_follow_on_packs: tuple[str, ...]
    primary_outputs: tuple[str, ...]
    auxiliary_outputs: tuple[str, ...]
    forbidden_object_families: tuple[str, ...]


@dataclass(frozen=True)
class CanonicalRoutingContract:
    candidate_domain_overlays: tuple[str, ...]
    follow_on_artifact_requests: tuple[str, ...]
    authority_needed_flags: tuple[str, ...]
    verification_needed_flags: tuple[str, ...]
    cross_pack_entity_classes: tuple[str, ...]


@dataclass(frozen=True)
class CanonicalFieldSpec:
    field_id: str
    field_path: str
    field_name: str
    group: str
    value_type: str
    repeatable: bool
    pre_or_post: str
    human_definition: str
    machine_gloss: str
    evidence_cues: tuple[str, ...]
    anti_evidence_cues: tuple[str, ...]
    confusions: tuple[str, ...]
    allowed_modalities: tuple[str, ...]
    linked_claim_family_ids: tuple[str, ...]
    linked_review_rule_ids: tuple[str, ...]
    linked_projection_rule_ids: tuple[str, ...]
    linked_example_ids: tuple[str, ...]
    linked_negative_example_ids: tuple[str, ...]
    authoritative_source_role: str
    source_paths: tuple[str, ...]
    source_hashes: tuple[str, ...]
    fallback_used: bool


@dataclass(frozen=True)
class CanonicalClaimFamilySpec:
    claim_family_id: str
    name: str
    group: str
    human_definition: str
    machine_gloss: str
    evidence_patterns: tuple[str, ...]
    negative_patterns: tuple[str, ...]
    confusions: tuple[str, ...]
    projection_target_field_ids: tuple[str, ...]
    linked_review_rule_ids: tuple[str, ...]
    linked_example_ids: tuple[str, ...]
    linked_negative_example_ids: tuple[str, ...]
    authoritative_source_role: str
    source_paths: tuple[str, ...]
    source_hashes: tuple[str, ...]
    fallback_used: bool


@dataclass(frozen=True)
class CanonicalReviewRule:
    rule_id: str
    name: str
    severity: str
    trigger_type: str
    machine_instruction: str
    applies_to_field_ids: tuple[str, ...]
    applies_to_claim_family_ids: tuple[str, ...]
    applies_to_modalities: tuple[str, ...]
    source_paths: tuple[str, ...]
    source_hashes: tuple[str, ...]
    fallback_used: bool


@dataclass(frozen=True)
class CanonicalProjectionRule:
    projection_rule_id: str
    source_claim_family_id: str
    target_field_ids: tuple[str, ...]
    projection_mode: str
    notes: str | None
    source_paths: tuple[str, ...]
    source_hashes: tuple[str, ...]
    fallback_used: bool


@dataclass(frozen=True)
class CanonicalParserProfile:
    parser_profile_id: str
    modality: str
    artifact_family: str
    role_id: str
    parser_kind: str
    structure_preservation_mode: str
    chronology_sensitive: bool
    actor_sensitive: bool
    confidence_policy: str
    allowed_field_ids: tuple[str, ...]
    allowed_claim_family_ids: tuple[str, ...]
    linked_review_rule_ids: tuple[str, ...]
    source_paths: tuple[str, ...]
    source_hashes: tuple[str, ...]
    fallback_used: bool


@dataclass(frozen=True)
class CanonicalEdge:
    edge_type: str
    source_id: str
    target_id: str
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class CanonicalIR:
    manifest: CanonicalManifest
    boundary: CanonicalBoundaryContract
    routing: CanonicalRoutingContract | None
    fields: Mapping[str, CanonicalFieldSpec]
    claim_families: Mapping[str, CanonicalClaimFamilySpec]
    review_rules: Mapping[str, CanonicalReviewRule]
    projection_rules: Mapping[str, CanonicalProjectionRule]
    parser_profiles: Mapping[str, CanonicalParserProfile]
    edges: tuple[CanonicalEdge, ...]
    diagnostics: tuple[Diagnostic, ...]


def _slugify(value: str) -> str:
    lowered = value.strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", lowered)
    return normalized.strip("_") or "unknown"


def _make_id(kind: str, pack_id: str, slug: str) -> str:
    return f"{kind}:{_slugify(pack_id)}:{_slugify(slug)}"


def _coerce_tuple_str(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value if isinstance(v, (str, int, float)))
    return ()


def _as_mapping(value: Any) -> Mapping[str, FrozenJSONLike]:
    if isinstance(value, Mapping):
        return value
    return MappingProxyType({})


def _extract_machine_gloss(raw: Mapping[str, Any], fallback_text: str = "") -> str:
    for key in ("machine_gloss", "gloss", "machine_instruction", "desc", "description", "definition"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback_text.strip()


def _extract_evidence_cues(raw: Mapping[str, Any]) -> tuple[str, ...]:
    return _coerce_tuple_str(raw.get("evidence_cues") or raw.get("strong_cues") or raw.get("evidence_patterns"))


def _extract_anti_evidence_cues(raw: Mapping[str, Any]) -> tuple[str, ...]:
    return _coerce_tuple_str(raw.get("anti_evidence_cues") or raw.get("anti_confusions") or raw.get("negative_patterns"))


def _extract_confusions(raw: Mapping[str, Any]) -> tuple[str, ...]:
    return _coerce_tuple_str(raw.get("confusions"))


def _source_paths_and_hashes(
    resolved: ResolvedContractsBundle, preferred_role: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    paths: list[str] = []
    for record in resolved.resolution_records:
        if record.winner_role == preferred_role:
            paths.extend(record.source_paths)
    if not paths and resolved.resolution_records:
        for record in resolved.resolution_records:
            if record.concern == preferred_role:
                paths.extend(record.source_paths)
    dedup_paths = tuple(sorted(set(paths)))
    hashes: list[str] = []
    for path in dedup_paths:
        p = Path(path)
        if p.exists() and p.is_file():
            hashes.append(hashlib.sha256(p.read_bytes()).hexdigest())
        else:
            hashes.append(hashlib.sha256(path.encode("utf-8")).hexdigest())
    return dedup_paths, tuple(hashes)


def _build_manifest(resolved: ResolvedContractsBundle) -> CanonicalManifest:
    fallback_used_for = tuple(sorted({record.concern for record in resolved.resolution_records if record.strategy == "fallback_merge"}))
    source_paths: dict[str, str] = {}
    source_hashes: dict[str, str] = {}
    for record in resolved.resolution_records:
        if not record.source_paths:
            continue
        source_paths[record.concern] = record.source_paths[0]
        p = Path(record.source_paths[0])
        if p.exists() and p.is_file():
            source_hashes[record.concern] = hashlib.sha256(p.read_bytes()).hexdigest()
        else:
            source_hashes[record.concern] = hashlib.sha256(record.source_paths[0].encode("utf-8")).hexdigest()
    return CanonicalManifest(
        pack_id=resolved.pack_id,
        artifact_family=resolved.resolved_scope.artifact_family,
        role_id=resolved.resolved_scope.role_id,
        compiler_version="canonical_ir.v1",
        admitted_modalities=tuple(sorted(str(m) for m in resolved.resolved_modalities.keys())),
        source_hashes=MappingProxyType(source_hashes),
        source_paths=MappingProxyType(source_paths),
        fallback_used_for=fallback_used_for,
        generated_from_resolution_records=resolved.resolution_records,
    )


def _build_boundary(resolved: ResolvedContractsBundle) -> CanonicalBoundaryContract:
    forbidden: set[str] = set()
    text = " ".join(resolved.resolved_scope.not_authoritative_for).lower()
    if any(token in text for token in ("spreadsheet", "row", "roster", "tabular")):
        forbidden.add("spreadsheet_row_native")
    if any(token in text for token in ("drawing", "dwg", "esx", "cad")):
        forbidden.add("drawing_native")
    if any(token in text for token in ("execution", "field execution", "closeout")):
        forbidden.add("execution_authority_native")
    return CanonicalBoundaryContract(
        authoritative_for=resolved.resolved_scope.authoritative_for,
        not_authoritative_for=resolved.resolved_scope.not_authoritative_for,
        routes_to_follow_on_packs=resolved.resolved_scope.routes_to_follow_on_packs,
        primary_outputs=resolved.resolved_scope.primary_outputs,
        auxiliary_outputs=resolved.resolved_scope.auxiliary_outputs,
        forbidden_object_families=tuple(sorted(forbidden)),
    )


def _build_routing(resolved: ResolvedContractsBundle) -> CanonicalRoutingContract | None:
    handoff = resolved.resolved_handoff
    if handoff is None:
        return None
    return CanonicalRoutingContract(
        candidate_domain_overlays=handoff.candidate_domain_overlays,
        follow_on_artifact_requests=handoff.follow_on_artifact_requests,
        authority_needed_flags=handoff.authority_needed_flags,
        verification_needed_flags=handoff.verification_needed_flags,
        cross_pack_entity_classes=handoff.cross_pack_entities,
    )


def _build_fields(
    resolved: ResolvedContractsBundle,
    boundary: CanonicalBoundaryContract,
) -> Mapping[str, CanonicalFieldSpec]:
    legal = resolved.resolved_field_legality
    field_semantics = resolved.resolved_field_semantics
    legal_field_names: set[str] = set(legal.field_paths) | set(str(k) for k in legal.fields.keys()) | set(
        str(k) for k in legal.pre_field_definitions.keys()
    ) | set(str(k) for k in legal.post_field_definitions.keys())
    allowed_modalities = tuple(sorted(str(k) for k in resolved.resolved_modalities.keys()))

    fields: dict[str, CanonicalFieldSpec] = {}
    for field_path in sorted(name for name in legal_field_names if name):
        field_name = field_path.split(".")[-1].replace("[]", "")
        field_group = field_path.split(".")[0].replace("[]", "")
        sem_raw = _as_mapping(field_semantics.get(field_path))
        if not sem_raw:
            sem_raw = _as_mapping(legal.pre_field_definitions.get(field_path)) or _as_mapping(legal.post_field_definitions.get(field_path))
        value_type = str(
            sem_raw.get("value_type")
            or sem_raw.get("kind")
            or sem_raw.get("type")
            or "unknown"
        )
        repeatable = "[]" in field_path or value_type.lower() in {"array", "list"}
        pre_or_post = "post" if field_path in legal.post_field_definitions else "pre"
        role = "field_catalog"
        source_paths, source_hashes = _source_paths_and_hashes(resolved, role)
        field_id = _make_id("field", resolved.pack_id, field_path)
        fields[field_id] = CanonicalFieldSpec(
            field_id=field_id,
            field_path=field_path,
            field_name=field_name,
            group=field_group,
            value_type=value_type,
            repeatable=repeatable,
            pre_or_post=pre_or_post,
            human_definition=str(sem_raw.get("desc") or sem_raw.get("definition") or ""),
            machine_gloss=_extract_machine_gloss(sem_raw, fallback_text=field_name),
            evidence_cues=_extract_evidence_cues(sem_raw),
            anti_evidence_cues=_extract_anti_evidence_cues(sem_raw),
            confusions=_extract_confusions(sem_raw),
            allowed_modalities=allowed_modalities,
            linked_claim_family_ids=(),
            linked_review_rule_ids=(),
            linked_projection_rule_ids=(),
            linked_example_ids=(),
            linked_negative_example_ids=(),
            authoritative_source_role=role,
            source_paths=source_paths,
            source_hashes=source_hashes,
            fallback_used="field_semantics" in {r.concern for r in resolved.resolution_records if r.strategy == "fallback_merge"},
        )
    return MappingProxyType(fields)


def _build_claim_families(
    resolved: ResolvedContractsBundle,
    fields: Mapping[str, CanonicalFieldSpec],
) -> Mapping[str, CanonicalClaimFamilySpec]:
    by_path = {spec.field_path: spec.field_id for spec in fields.values()}
    out: dict[str, CanonicalClaimFamilySpec] = {}
    raw_map = resolved.resolved_claim_family_semantics
    for name, payload in raw_map.items():
        if not isinstance(name, str):
            continue
        data = _as_mapping(payload)
        cid = _make_id("claim", resolved.pack_id, name)
        source_paths, source_hashes = _source_paths_and_hashes(resolved, "enhanced_machine")
        target_ids = tuple(
            sorted(
                by_path[path]
                for path in _coerce_tuple_str(data.get("projection_targets") or data.get("maps_to"))
                if path in by_path
            )
        )
        out[cid] = CanonicalClaimFamilySpec(
            claim_family_id=cid,
            name=name,
            group=str(data.get("group") or "default"),
            human_definition=str(data.get("desc") or data.get("definition") or ""),
            machine_gloss=_extract_machine_gloss(data, fallback_text=name),
            evidence_patterns=_coerce_tuple_str(data.get("evidence_patterns") or data.get("strong_cues")),
            negative_patterns=_coerce_tuple_str(data.get("negative_patterns") or data.get("anti_confusions")),
            confusions=_extract_confusions(data),
            projection_target_field_ids=target_ids,
            linked_review_rule_ids=(),
            linked_example_ids=(),
            linked_negative_example_ids=(),
            authoritative_source_role="enhanced_machine",
            source_paths=source_paths,
            source_hashes=source_hashes,
            fallback_used="claim_family_semantics" in {r.concern for r in resolved.resolution_records if r.strategy == "fallback_merge"},
        )
    return MappingProxyType(out)


def _build_review_rules(
    resolved: ResolvedContractsBundle,
    fields: Mapping[str, CanonicalFieldSpec],
    claim_families: Mapping[str, CanonicalClaimFamilySpec],
) -> Mapping[str, CanonicalReviewRule]:
    path_to_id = {f.field_path: f.field_id for f in fields.values()}
    name_to_claim_id = {c.name: c.claim_family_id for c in claim_families.values()}
    out: dict[str, CanonicalReviewRule] = {}
    for name, payload in resolved.resolved_review_rules.items():
        if not isinstance(name, str):
            continue
        data = payload if isinstance(payload, Mapping) else {"message": str(payload)}
        rid = _make_id("rule", resolved.pack_id, name)
        applies_fields = tuple(
            sorted(path_to_id[p] for p in _coerce_tuple_str(data.get("field_paths") or data.get("fields")) if p in path_to_id)
        )
        applies_claims = tuple(
            sorted(name_to_claim_id[n] for n in _coerce_tuple_str(data.get("claim_families")) if n in name_to_claim_id)
        )
        source_paths, source_hashes = _source_paths_and_hashes(resolved, "enhanced_machine")
        out[rid] = CanonicalReviewRule(
            rule_id=rid,
            name=name,
            severity=str(data.get("severity") or "warning"),
            trigger_type=str(data.get("trigger_type") or "rule"),
            machine_instruction=str(data.get("machine_instruction") or data.get("message") or ""),
            applies_to_field_ids=applies_fields,
            applies_to_claim_family_ids=applies_claims,
            applies_to_modalities=tuple(sorted(str(k) for k in resolved.resolved_modalities.keys())),
            source_paths=source_paths,
            source_hashes=source_hashes,
            fallback_used="review_rules" in {r.concern for r in resolved.resolution_records if r.strategy == "fallback_merge"},
        )
    return MappingProxyType(out)


def _build_projection_rules(
    resolved: ResolvedContractsBundle,
    fields: Mapping[str, CanonicalFieldSpec],
    claim_families: Mapping[str, CanonicalClaimFamilySpec],
) -> Mapping[str, CanonicalProjectionRule]:
    path_to_id = {f.field_path: f.field_id for f in fields.values()}
    name_to_claim_id = {c.name: c.claim_family_id for c in claim_families.values()}
    out: dict[str, CanonicalProjectionRule] = {}
    rules = resolved.resolved_projection_rules

    if isinstance(rules.get("emits"), (list, tuple)):
        rules = {"default_projection": rules}

    for name, payload in rules.items():
        if not isinstance(name, str):
            continue
        data = payload if isinstance(payload, Mapping) else {"emits": [str(payload)]}
        targets = _coerce_tuple_str(
            data.get("target_field_paths")
            or data.get("target_fields")
            or data.get("field_paths")
            or data.get("emits")
        )
        unknown_targets = tuple(sorted(t for t in targets if t not in path_to_id))
        if unknown_targets:
            raise ContractLoadError(f"Projection rule '{name}' references unknown target fields: {unknown_targets}")
        target_ids = tuple(path_to_id[t] for t in targets)
        source_claim_name = str(data.get("claim_family") or data.get("source_claim_family") or "unknown_claim_family")
        if source_claim_name not in name_to_claim_id:
            raise ContractLoadError(
                f"Projection rule '{name}' references unknown source claim family: '{source_claim_name}'"
            )
        source_claim_id = name_to_claim_id[source_claim_name]
        source_paths, source_hashes = _source_paths_and_hashes(resolved, "enhanced_machine")
        pid = _make_id("projection", resolved.pack_id, name)
        out[pid] = CanonicalProjectionRule(
            projection_rule_id=pid,
            source_claim_family_id=source_claim_id,
            target_field_ids=target_ids,
            projection_mode=str(data.get("projection_mode") or "direct"),
            notes=str(data.get("notes")) if data.get("notes") is not None else None,
            source_paths=source_paths,
            source_hashes=source_hashes,
            fallback_used="projection_rules" in {r.concern for r in resolved.resolution_records if r.strategy == "fallback_merge"},
        )
    return MappingProxyType(out)


def _build_parser_profiles(
    resolved: ResolvedContractsBundle,
    boundary: CanonicalBoundaryContract,
    fields: Mapping[str, CanonicalFieldSpec],
    claim_families: Mapping[str, CanonicalClaimFamilySpec],
    review_rules: Mapping[str, CanonicalReviewRule],
) -> Mapping[str, CanonicalParserProfile]:
    parser_profiles_raw = _as_mapping(resolved.resolved_parser_profiles)
    admitted_modalities = tuple(sorted(str(m) for m in resolved.resolved_modalities.keys()))
    all_field_ids = tuple(sorted(fields.keys()))
    all_claim_ids = tuple(sorted(claim_families.keys()))
    all_rule_ids = tuple(sorted(review_rules.keys()))
    field_path_to_id = {spec.field_path: spec.field_id for spec in fields.values()}
    claim_name_to_id = {spec.name: spec.claim_family_id for spec in claim_families.values()}
    rule_name_to_id = {spec.name: spec.rule_id for spec in review_rules.values()}
    field_to_rules: dict[str, set[str]] = {field_id: set() for field_id in fields}
    for rule in review_rules.values():
        for field_id in rule.applies_to_field_ids:
            if field_id in field_to_rules:
                field_to_rules[field_id].add(rule.rule_id)
    claim_to_rules: dict[str, set[str]] = {claim_id: set() for claim_id in claim_families}
    for rule in review_rules.values():
        for claim_id in rule.applies_to_claim_family_ids:
            if claim_id in claim_to_rules:
                claim_to_rules[claim_id].add(rule.rule_id)
    source_paths, source_hashes = _source_paths_and_hashes(resolved, "enhanced_machine")
    out: dict[str, CanonicalParserProfile] = {}
    fallback_concerns = {r.concern for r in resolved.resolution_records if r.strategy == "fallback_merge"}
    for modality in admitted_modalities:
        payload = _as_mapping(parser_profiles_raw.get(modality))
        allowed_field_paths = _coerce_tuple_str(payload.get("allowed_field_paths") or payload.get("allowed_fields"))
        allowed_field_ids = (
            tuple(sorted(field_path_to_id[path] for path in allowed_field_paths if path in field_path_to_id))
            if allowed_field_paths
            else all_field_ids
        )
        allowed_claim_names = _coerce_tuple_str(payload.get("allowed_claim_families") or payload.get("claim_families"))
        allowed_claim_ids = (
            tuple(sorted(claim_name_to_id[name] for name in allowed_claim_names if name in claim_name_to_id))
            if allowed_claim_names
            else all_claim_ids
        )
        explicit_rule_names = _coerce_tuple_str(payload.get("linked_review_rules") or payload.get("review_rules"))
        if explicit_rule_names:
            linked_rule_ids = tuple(sorted(rule_name_to_id[name] for name in explicit_rule_names if name in rule_name_to_id))
        else:
            inferred_rules: set[str] = set()
            for field_id in allowed_field_ids:
                inferred_rules.update(field_to_rules.get(field_id, set()))
            for claim_id in allowed_claim_ids:
                inferred_rules.update(claim_to_rules.get(claim_id, set()))
            linked_rule_ids = tuple(sorted(inferred_rules)) or all_rule_ids
        profile_id = _make_id("parser", resolved.pack_id, modality)
        out[profile_id] = CanonicalParserProfile(
            parser_profile_id=profile_id,
            modality=modality,
            artifact_family=resolved.manifest.artifact_family if hasattr(resolved, "manifest") else resolved.resolved_scope.artifact_family,
            role_id=resolved.resolved_scope.role_id,
            parser_kind=str(payload.get("parser_kind") or payload.get("pre_parser") or "text_parser"),
            structure_preservation_mode=str(payload.get("structure_preservation_mode") or "preserve"),
            chronology_sensitive=bool(payload.get("chronology_sensitive", True)),
            actor_sensitive=bool(payload.get("actor_sensitive", True)),
            confidence_policy=str(payload.get("confidence_policy") or "review_first"),
            allowed_field_ids=allowed_field_ids,
            allowed_claim_family_ids=allowed_claim_ids,
            linked_review_rule_ids=linked_rule_ids,
            source_paths=source_paths,
            source_hashes=source_hashes,
            fallback_used="parser_profiles" in fallback_concerns,
        )
    return MappingProxyType(out)


def _build_edges(
    fields: Mapping[str, CanonicalFieldSpec],
    claim_families: Mapping[str, CanonicalClaimFamilySpec],
    review_rules: Mapping[str, CanonicalReviewRule],
    projection_rules: Mapping[str, CanonicalProjectionRule],
    parser_profiles: Mapping[str, CanonicalParserProfile],
    routing: CanonicalRoutingContract | None,
) -> tuple[CanonicalEdge, ...]:
    edges: list[CanonicalEdge] = []
    for claim in claim_families.values():
        for field_id in claim.projection_target_field_ids:
            edges.append(CanonicalEdge("claim_to_field", claim.claim_family_id, field_id, {}))
    for rule in review_rules.values():
        for field_id in rule.applies_to_field_ids:
            edges.append(CanonicalEdge("rule_to_field", rule.rule_id, field_id, {}))
        for claim_id in rule.applies_to_claim_family_ids:
            edges.append(CanonicalEdge("rule_to_claim", rule.rule_id, claim_id, {}))
    for projection in projection_rules.values():
        edges.append(
            CanonicalEdge(
                "projection_from_claim",
                projection.source_claim_family_id,
                projection.projection_rule_id,
                {"mode": projection.projection_mode},
            )
        )
        for target_field_id in projection.target_field_ids:
            edges.append(CanonicalEdge("projection_to_field", projection.projection_rule_id, target_field_id, {}))
    for parser in parser_profiles.values():
        edges.append(CanonicalEdge("modality_to_parser", parser.modality, parser.parser_profile_id, {}))
        for field_id in parser.allowed_field_ids:
            edges.append(CanonicalEdge("parser_to_field", parser.parser_profile_id, field_id, {}))
    if routing is not None:
        for overlay in routing.candidate_domain_overlays:
            edges.append(CanonicalEdge("routing_overlay", "routing", overlay, {}))
        for request in routing.follow_on_artifact_requests:
            edges.append(CanonicalEdge("routing_request", "routing", request, {}))
    return tuple(edges)


def _link_canonical_objects(
    fields: Mapping[str, CanonicalFieldSpec],
    claim_families: Mapping[str, CanonicalClaimFamilySpec],
    review_rules: Mapping[str, CanonicalReviewRule],
    projection_rules: Mapping[str, CanonicalProjectionRule],
) -> tuple[
    Mapping[str, CanonicalFieldSpec],
    Mapping[str, CanonicalClaimFamilySpec],
]:
    field_to_claims: dict[str, set[str]] = {field_id: set() for field_id in fields}
    field_to_rules: dict[str, set[str]] = {field_id: set() for field_id in fields}
    field_to_projections: dict[str, set[str]] = {field_id: set() for field_id in fields}
    claim_to_rules: dict[str, set[str]] = {claim_id: set() for claim_id in claim_families}

    for claim in claim_families.values():
        for field_id in claim.projection_target_field_ids:
            if field_id in field_to_claims:
                field_to_claims[field_id].add(claim.claim_family_id)

    for rule in review_rules.values():
        for field_id in rule.applies_to_field_ids:
            if field_id in field_to_rules:
                field_to_rules[field_id].add(rule.rule_id)
        for claim_id in rule.applies_to_claim_family_ids:
            if claim_id in claim_to_rules:
                claim_to_rules[claim_id].add(rule.rule_id)

    for projection in projection_rules.values():
        for field_id in projection.target_field_ids:
            if field_id in field_to_projections:
                field_to_projections[field_id].add(projection.projection_rule_id)

    linked_fields: dict[str, CanonicalFieldSpec] = {}
    for field_id, spec in fields.items():
        linked_fields[field_id] = replace(
            spec,
            linked_claim_family_ids=tuple(sorted(field_to_claims[field_id])),
            linked_review_rule_ids=tuple(sorted(field_to_rules[field_id])),
            linked_projection_rule_ids=tuple(sorted(field_to_projections[field_id])),
        )

    linked_claims: dict[str, CanonicalClaimFamilySpec] = {}
    for claim_id, spec in claim_families.items():
        linked_claims[claim_id] = replace(
            spec,
            linked_review_rule_ids=tuple(sorted(claim_to_rules[claim_id])),
        )

    return MappingProxyType(linked_fields), MappingProxyType(linked_claims)


def _validate_canonical_ir(ir: CanonicalIR) -> None:
    field_ids = set(ir.fields.keys())
    claim_ids = set(ir.claim_families.keys())
    rule_ids = set(ir.review_rules.keys())
    parser_ids = set(ir.parser_profiles.keys())
    projection_ids = set(ir.projection_rules.keys())

    if len(field_ids) != len(ir.fields):
        raise ContractLoadError("Duplicate field IDs detected in Canonical IR.")
    if len(claim_ids) != len(ir.claim_families):
        raise ContractLoadError("Duplicate claim family IDs detected in Canonical IR.")
    if len(rule_ids) != len(ir.review_rules):
        raise ContractLoadError("Duplicate review rule IDs detected in Canonical IR.")
    if len(parser_ids) != len(ir.parser_profiles):
        raise ContractLoadError("Duplicate parser profile IDs detected in Canonical IR.")
    if len(projection_ids) != len(ir.projection_rules):
        raise ContractLoadError("Duplicate projection rule IDs detected in Canonical IR.")

    admitted = set(ir.manifest.admitted_modalities)
    profile_modalities = {profile.modality for profile in ir.parser_profiles.values()}
    unknown_profile_modalities = sorted(profile_modalities - admitted)
    if unknown_profile_modalities:
        raise ContractLoadError(
            "Parser profiles include modalities not admitted by source inventory: "
            f"{unknown_profile_modalities}"
        )

    for projection in ir.projection_rules.values():
        if projection.source_claim_family_id not in claim_ids:
            raise ContractLoadError(
                f"Projection rule {projection.projection_rule_id} references unknown claim family "
                f"{projection.source_claim_family_id}."
            )
        unknown_targets = [t for t in projection.target_field_ids if t not in field_ids]
        if unknown_targets:
            raise ContractLoadError(
                f"Projection rule {projection.projection_rule_id} references unknown target fields: "
                f"{unknown_targets}"
            )

    for rule in ir.review_rules.values():
        unknown_fields = [f for f in rule.applies_to_field_ids if f not in field_ids]
        if unknown_fields:
            raise ContractLoadError(f"Review rule {rule.rule_id} references unknown fields: {unknown_fields}")
        unknown_claims = [c for c in rule.applies_to_claim_family_ids if c not in claim_ids]
        if unknown_claims:
            raise ContractLoadError(f"Review rule {rule.rule_id} references unknown claim families: {unknown_claims}")

    forbidden = set(ir.boundary.forbidden_object_families)
    if "spreadsheet_row_native" in forbidden:
        if any("site_roster_rows" in field.field_path for field in ir.fields.values()):
            raise ContractLoadError("Boundary violation: spreadsheet row-native fields appear as primary schema objects.")
    if "drawing_native" in forbidden:
        if any(any(token in field.field_path for token in ("drawing", "dwg", "esx", "cad")) for field in ir.fields.values()):
            raise ContractLoadError("Boundary violation: drawing-native fields appear as primary schema objects.")
    if "execution_authority_native" in forbidden:
        if any("field_execution_report" in field.field_path for field in ir.fields.values()):
            raise ContractLoadError("Boundary violation: execution-authority-native fields appear as primary schema objects.")


def build_canonical_ir(resolved: ResolvedContractsBundle) -> CanonicalIR:
    manifest = _build_manifest(resolved)
    boundary = _build_boundary(resolved)
    routing = _build_routing(resolved)

    fields = _build_fields(resolved, boundary)
    claim_families = _build_claim_families(resolved, fields)
    review_rules = _build_review_rules(resolved, fields, claim_families)
    projection_rules = _build_projection_rules(resolved, fields, claim_families)
    parser_profiles = _build_parser_profiles(resolved, boundary, fields, claim_families, review_rules)
    fields, claim_families = _link_canonical_objects(fields, claim_families, review_rules, projection_rules)
    edges = _build_edges(fields, claim_families, review_rules, projection_rules, parser_profiles, routing)

    ir = CanonicalIR(
        manifest=manifest,
        boundary=boundary,
        routing=routing,
        fields=fields,
        claim_families=claim_families,
        review_rules=review_rules,
        projection_rules=projection_rules,
        parser_profiles=parser_profiles,
        edges=edges,
        diagnostics=resolved.diagnostics,
    )
    _validate_canonical_ir(ir)
    return ir
