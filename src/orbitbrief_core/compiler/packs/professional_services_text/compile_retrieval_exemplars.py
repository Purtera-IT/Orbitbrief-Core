from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from orbitbrief_core.compiler.core.canonical_ir import CanonicalClaimFamilySpec, CanonicalFieldSpec, CanonicalIR
from orbitbrief_core.compiler.core.load_contracts import ContractLoadError
from orbitbrief_core.compiler.packs.professional_services_text.examples_contract_support import (
    DEFAULT_DISCOURSE_PROFILES,
    PathLike,
    admitted_modalities,
    anchor_terms_from_text,
    compact_text,
    load_structured_documents,
    merged_provenance,
    resolve_claim_family_ids,
    resolve_discourse_profiles,
    resolve_field_ids,
    resolve_modalities,
    resolve_review_rule_ids,
    slugify,
    text_fingerprint,
)


@dataclass(frozen=True)
class CompiledRetrievalExemplarRow:
    exemplar_id: str
    text: str
    category: str
    linked_field_ids: tuple[str, ...]
    linked_claim_family_ids: tuple[str, ...]
    linked_review_rule_ids: tuple[str, ...]
    modalities: tuple[str, ...]
    discourse_profiles: tuple[str, ...]
    weight: float
    source_paths: tuple[str, ...]
    source_hashes: tuple[str, ...]
    source_kind: str
    runtime_class: str
    authoritative_source_role: str
    anchor_terms: tuple[str, ...]
    text_fingerprint: str
    has_field_links: bool
    has_claim_links: bool


@dataclass(frozen=True)
class RetrievalExemplarDiagnostic:
    level: str
    code: str
    message: str
    exemplar_id: str | None = None
    context: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalExemplarSummary:
    total_exemplars: int
    curated_exemplar_count: int
    harvested_exemplar_count: int
    exemplars_by_category: Mapping[str, int]
    exemplars_by_source_kind: Mapping[str, int]
    exemplars_by_runtime_class: Mapping[str, int]
    exemplars_by_discourse_profile: Mapping[str, int]
    exemplars_by_modality: Mapping[str, int]
    exemplars_without_field_links: tuple[str, ...]
    exemplars_without_claim_links: tuple[str, ...]
    average_weight: float
    max_weight: float
    min_weight: float


@dataclass(frozen=True)
class CompiledRetrievalExemplarTable:
    rows: tuple[CompiledRetrievalExemplarRow, ...]
    by_exemplar_id: Mapping[str, CompiledRetrievalExemplarRow]
    by_category: Mapping[str, tuple[str, ...]]
    by_field_id: Mapping[str, tuple[str, ...]]
    by_claim_family_id: Mapping[str, tuple[str, ...]]
    by_review_rule_id: Mapping[str, tuple[str, ...]]
    by_modality: Mapping[str, tuple[str, ...]]
    by_discourse_profile: Mapping[str, tuple[str, ...]]
    by_source_kind: Mapping[str, tuple[str, ...]]
    by_runtime_class: Mapping[str, tuple[str, ...]]
    diagnostics: tuple[RetrievalExemplarDiagnostic, ...]
    summary: RetrievalExemplarSummary


def _make_exemplar_id(pack_id: str, category: str, text: str) -> str:
    return f"retrieval:{slugify(pack_id)}:{slugify(category)}:{text_fingerprint(text)[:10]}"


def _runtime_class(source_kind: str) -> str:
    if source_kind == "curated_yaml":
        return "curated_artifact_exemplar"
    if source_kind == "claim_family_example":
        return "artifact_exemplar"
    if source_kind == "field_example":
        return "artifact_exemplar"
    if source_kind == "claim_family_cue_phrase":
        return "cue_phrase"
    if source_kind == "field_cue_phrase":
        return "cue_phrase"
    if source_kind == "service_vocabulary":
        return "service_vocabulary"
    return "semantic_gloss"


def _row_key(
    *,
    text: str,
    category: str,
    linked_field_ids: tuple[str, ...],
    linked_claim_family_ids: tuple[str, ...],
    modalities: tuple[str, ...],
    discourse_profiles: tuple[str, ...],
) -> tuple[object, ...]:
    return (
        compact_text(text).lower(),
        category,
        linked_field_ids,
        linked_claim_family_ids,
        modalities,
        discourse_profiles,
    )


def _dedupe_rows(rows: Sequence[CompiledRetrievalExemplarRow]) -> tuple[CompiledRetrievalExemplarRow, ...]:
    merged: dict[tuple[object, ...], CompiledRetrievalExemplarRow] = {}
    for row in rows:
        key = _row_key(
            text=row.text,
            category=row.category,
            linked_field_ids=row.linked_field_ids,
            linked_claim_family_ids=row.linked_claim_family_ids,
            modalities=row.modalities,
            discourse_profiles=row.discourse_profiles,
        )
        existing = merged.get(key)
        if existing is None:
            merged[key] = row
            continue
        source_paths = tuple(sorted(set(existing.source_paths).union(row.source_paths)))
        source_hashes = tuple(sorted(set(existing.source_hashes).union(row.source_hashes)))
        linked_rule_ids = tuple(sorted(set(existing.linked_review_rule_ids).union(row.linked_review_rule_ids)))
        anchor_terms = tuple(sorted(set(existing.anchor_terms).union(row.anchor_terms)))
        merged[key] = CompiledRetrievalExemplarRow(
            exemplar_id=existing.exemplar_id,
            text=existing.text,
            category=existing.category,
            linked_field_ids=existing.linked_field_ids,
            linked_claim_family_ids=existing.linked_claim_family_ids,
            linked_review_rule_ids=linked_rule_ids,
            modalities=existing.modalities,
            discourse_profiles=existing.discourse_profiles,
            weight=max(existing.weight, row.weight),
            source_paths=source_paths,
            source_hashes=source_hashes,
            source_kind=existing.source_kind if existing.source_kind == "curated_yaml" else row.source_kind,
            runtime_class=existing.runtime_class if existing.source_kind == "curated_yaml" else row.runtime_class,
            authoritative_source_role=existing.authoritative_source_role if existing.source_kind == "curated_yaml" else row.authoritative_source_role,
            anchor_terms=anchor_terms,
            text_fingerprint=existing.text_fingerprint,
            has_field_links=existing.has_field_links or row.has_field_links,
            has_claim_links=existing.has_claim_links or row.has_claim_links,
        )
    return tuple(sorted(merged.values(), key=lambda row: row.exemplar_id))


def _ensure_unique_exemplar_ids(rows: tuple[CompiledRetrievalExemplarRow, ...]) -> tuple[CompiledRetrievalExemplarRow, ...]:
    seen: dict[str, int] = {}
    out: list[CompiledRetrievalExemplarRow] = []
    for row in rows:
        base = row.exemplar_id
        idx = seen.get(base, 0)
        seen[base] = idx + 1
        if idx == 0:
            out.append(row)
            continue
        out.append(replace(row, exemplar_id=f"{base}:{idx}"))
    return tuple(sorted(out, key=lambda row: row.exemplar_id))


def _build_indices(rows: tuple[CompiledRetrievalExemplarRow, ...]) -> dict[str, Mapping[str, tuple[str, ...]] | Mapping[str, CompiledRetrievalExemplarRow]]:
    by_exemplar_id = MappingProxyType({row.exemplar_id: row for row in rows})

    def bucket(values: Mapping[str, list[str]]) -> Mapping[str, tuple[str, ...]]:
        return MappingProxyType({key: tuple(sorted(ids)) for key, ids in sorted(values.items())})

    by_category: dict[str, list[str]] = defaultdict(list)
    by_field_id: dict[str, list[str]] = defaultdict(list)
    by_claim_family_id: dict[str, list[str]] = defaultdict(list)
    by_review_rule_id: dict[str, list[str]] = defaultdict(list)
    by_modality: dict[str, list[str]] = defaultdict(list)
    by_discourse_profile: dict[str, list[str]] = defaultdict(list)
    by_source_kind: dict[str, list[str]] = defaultdict(list)
    by_runtime_class: dict[str, list[str]] = defaultdict(list)

    for row in rows:
        by_category[row.category].append(row.exemplar_id)
        by_source_kind[row.source_kind].append(row.exemplar_id)
        by_runtime_class[row.runtime_class].append(row.exemplar_id)
        for field_id in row.linked_field_ids:
            by_field_id[field_id].append(row.exemplar_id)
        for claim_id in row.linked_claim_family_ids:
            by_claim_family_id[claim_id].append(row.exemplar_id)
        for rule_id in row.linked_review_rule_ids:
            by_review_rule_id[rule_id].append(row.exemplar_id)
        for modality in row.modalities:
            by_modality[modality].append(row.exemplar_id)
        for profile in row.discourse_profiles:
            by_discourse_profile[profile].append(row.exemplar_id)

    return {
        "by_exemplar_id": by_exemplar_id,
        "by_category": bucket(by_category),
        "by_field_id": bucket(by_field_id),
        "by_claim_family_id": bucket(by_claim_family_id),
        "by_review_rule_id": bucket(by_review_rule_id),
        "by_modality": bucket(by_modality),
        "by_discourse_profile": bucket(by_discourse_profile),
        "by_source_kind": bucket(by_source_kind),
        "by_runtime_class": bucket(by_runtime_class),
    }


def _build_summary(rows: tuple[CompiledRetrievalExemplarRow, ...]) -> RetrievalExemplarSummary:
    exemplars_by_category: dict[str, int] = defaultdict(int)
    exemplars_by_source_kind: dict[str, int] = defaultdict(int)
    exemplars_by_runtime_class: dict[str, int] = defaultdict(int)
    exemplars_by_discourse_profile: dict[str, int] = defaultdict(int)
    exemplars_by_modality: dict[str, int] = defaultdict(int)
    without_fields: list[str] = []
    without_claims: list[str] = []
    curated_count = 0
    harvested_count = 0
    weights: list[float] = []

    for row in rows:
        exemplars_by_category[row.category] += 1
        exemplars_by_source_kind[row.source_kind] += 1
        exemplars_by_runtime_class[row.runtime_class] += 1
        if row.source_kind == "curated_yaml":
            curated_count += 1
        else:
            harvested_count += 1
        if not row.linked_field_ids:
            without_fields.append(row.exemplar_id)
        if not row.linked_claim_family_ids:
            without_claims.append(row.exemplar_id)
        weights.append(row.weight)
        for profile in row.discourse_profiles:
            exemplars_by_discourse_profile[profile] += 1
        for modality in row.modalities:
            exemplars_by_modality[modality] += 1

    return RetrievalExemplarSummary(
        total_exemplars=len(rows),
        curated_exemplar_count=curated_count,
        harvested_exemplar_count=harvested_count,
        exemplars_by_category=MappingProxyType(dict(sorted(exemplars_by_category.items()))),
        exemplars_by_source_kind=MappingProxyType(dict(sorted(exemplars_by_source_kind.items()))),
        exemplars_by_runtime_class=MappingProxyType(dict(sorted(exemplars_by_runtime_class.items()))),
        exemplars_by_discourse_profile=MappingProxyType(dict(sorted(exemplars_by_discourse_profile.items()))),
        exemplars_by_modality=MappingProxyType(dict(sorted(exemplars_by_modality.items()))),
        exemplars_without_field_links=tuple(sorted(without_fields)),
        exemplars_without_claim_links=tuple(sorted(without_claims)),
        average_weight=(sum(weights) / len(weights)) if weights else 0.0,
        max_weight=max(weights) if weights else 0.0,
        min_weight=min(weights) if weights else 0.0,
    )


def _build_diagnostics(rows: tuple[CompiledRetrievalExemplarRow, ...]) -> tuple[RetrievalExemplarDiagnostic, ...]:
    diagnostics: list[RetrievalExemplarDiagnostic] = []
    for row in rows:
        if not row.text:
            diagnostics.append(
                RetrievalExemplarDiagnostic(
                    level="error",
                    code="retrieval_exemplar.empty_text",
                    message="Retrieval exemplar has empty text.",
                    exemplar_id=row.exemplar_id,
                )
            )
        if len(row.text) < 4:
            diagnostics.append(
                RetrievalExemplarDiagnostic(
                    level="warning",
                    code="retrieval_exemplar.text_too_short",
                    message="Retrieval exemplar text is very short and may be noisy.",
                    exemplar_id=row.exemplar_id,
                )
            )
        if not row.linked_field_ids:
            diagnostics.append(
                RetrievalExemplarDiagnostic(
                    level="info",
                    code="retrieval_exemplar.no_field_links",
                    message="Retrieval exemplar has no linked fields.",
                    exemplar_id=row.exemplar_id,
                )
            )
        if not row.linked_claim_family_ids:
            diagnostics.append(
                RetrievalExemplarDiagnostic(
                    level="info",
                    code="retrieval_exemplar.no_claim_links",
                    message="Retrieval exemplar has no linked claim families.",
                    exemplar_id=row.exemplar_id,
                )
            )
    return tuple(diagnostics)


def _row_from_explicit_entry(
    ir: CanonicalIR,
    raw_entry: Mapping[str, Any],
    *,
    source_path: Path,
    source_kind: str,
) -> CompiledRetrievalExemplarRow:
    text = compact_text(str(raw_entry.get("text") or ""))
    if not text:
        raise ContractLoadError(f"Retrieval exemplar entry in {source_path} is missing text")
    category = str(raw_entry.get("category") or "uncategorized")
    field_ids = resolve_field_ids(ir, raw_entry)
    claim_ids = resolve_claim_family_ids(ir, raw_entry)
    review_rule_ids = resolve_review_rule_ids(ir, raw_entry, field_ids, claim_ids)
    modalities = resolve_modalities(ir, raw_entry)
    profiles = resolve_discourse_profiles(raw_entry)
    weight = float(raw_entry.get("weight") or 1.0)
    exemplar_id = str(raw_entry.get("exemplar_id") or _make_exemplar_id(ir.manifest.pack_id, category, text))
    source_paths, source_hashes = merged_provenance((source_path,))
    return CompiledRetrievalExemplarRow(
        exemplar_id=exemplar_id,
        text=text,
        category=category,
        linked_field_ids=field_ids,
        linked_claim_family_ids=claim_ids,
        linked_review_rule_ids=review_rule_ids,
        modalities=modalities,
        discourse_profiles=profiles,
        weight=weight,
        source_paths=source_paths,
        source_hashes=source_hashes,
        source_kind=source_kind,
        runtime_class=_runtime_class(source_kind),
        authoritative_source_role="curated_examples" if source_kind == "curated_yaml" else "enhanced_machine",
        anchor_terms=anchor_terms_from_text(text),
        text_fingerprint=text_fingerprint(text),
        has_field_links=bool(field_ids),
        has_claim_links=bool(claim_ids),
    )


def _claim_field_links(ir: CanonicalIR, claim: CanonicalClaimFamilySpec) -> tuple[str, ...]:
    return tuple(sorted(claim.projection_target_field_ids))


def _field_links(field: CanonicalFieldSpec) -> tuple[str, ...]:
    return (field.field_id,)


def _paths_and_hashes_for_role(ir: CanonicalIR, role: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    source_paths = [path for concern, path in ir.manifest.source_paths.items() if concern == role]
    if not source_paths:
        source_paths = list(ir.manifest.source_paths.values())
    existing_paths = [Path(path) for path in source_paths if Path(path).exists()]
    return tuple(str(path) for path in existing_paths), tuple(
        __import__("hashlib").sha256(path.read_bytes()).hexdigest() for path in existing_paths
    )


def _rows_from_ir(ir: CanonicalIR) -> list[CompiledRetrievalExemplarRow]:
    rows: list[CompiledRetrievalExemplarRow] = []
    field_role_paths, field_role_hashes = _paths_and_hashes_for_role(ir, "field_catalog")
    claim_role_paths, claim_role_hashes = _paths_and_hashes_for_role(ir, "enhanced_machine")

    for claim in ir.claim_families.values():
        for phrase in claim.evidence_patterns:
            text = compact_text(phrase)
            if not text:
                continue
            rows.append(
                CompiledRetrievalExemplarRow(
                    exemplar_id=_make_exemplar_id(ir.manifest.pack_id, claim.name, text),
                    text=text,
                    category=claim.name,
                    linked_field_ids=_claim_field_links(ir, claim),
                    linked_claim_family_ids=(claim.claim_family_id,),
                    linked_review_rule_ids=tuple(sorted(claim.linked_review_rule_ids)),
                    modalities=tuple(sorted(admitted_modalities(ir))),
                    discourse_profiles=DEFAULT_DISCOURSE_PROFILES,
                    weight=0.65,
                    source_paths=claim_role_paths,
                    source_hashes=claim_role_hashes,
                    source_kind="claim_family_cue_phrase",
                    runtime_class=_runtime_class("claim_family_cue_phrase"),
                    authoritative_source_role=claim.authoritative_source_role,
                    anchor_terms=anchor_terms_from_text(text),
                    text_fingerprint=text_fingerprint(text),
                    has_field_links=bool(claim.projection_target_field_ids),
                    has_claim_links=True,
                )
            )

    for field in ir.fields.values():
        for phrase in field.evidence_cues:
            text = compact_text(phrase)
            if not text:
                continue
            rows.append(
                CompiledRetrievalExemplarRow(
                    exemplar_id=_make_exemplar_id(ir.manifest.pack_id, field.field_name, text),
                    text=text,
                    category=field.field_name,
                    linked_field_ids=_field_links(field),
                    linked_claim_family_ids=tuple(sorted(field.linked_claim_family_ids)),
                    linked_review_rule_ids=tuple(sorted(field.linked_review_rule_ids)),
                    modalities=field.allowed_modalities,
                    discourse_profiles=DEFAULT_DISCOURSE_PROFILES,
                    weight=0.55,
                    source_paths=field_role_paths,
                    source_hashes=field_role_hashes,
                    source_kind="field_cue_phrase",
                    runtime_class=_runtime_class("field_cue_phrase"),
                    authoritative_source_role=field.authoritative_source_role,
                    anchor_terms=anchor_terms_from_text(text),
                    text_fingerprint=text_fingerprint(text),
                    has_field_links=True,
                    has_claim_links=bool(field.linked_claim_family_ids),
                )
            )
    return rows


def _rows_from_semantic_docs(
    ir: CanonicalIR,
    semantic_contract_paths: Sequence[PathLike],
) -> list[CompiledRetrievalExemplarRow]:
    rows: list[CompiledRetrievalExemplarRow] = []
    for path, doc in load_structured_documents(semantic_contract_paths):
        claim_defs = doc.get("claim_family_definitions")
        if isinstance(claim_defs, Mapping):
            for claim_name, payload in claim_defs.items():
                if not isinstance(payload, Mapping):
                    continue
                claim_id = next((cid for cid, claim in ir.claim_families.items() if claim.name == str(claim_name)), None)
                field_ids = resolve_field_ids(ir, {"linked_field_paths": payload.get("maps_to", ()) or ()}) if payload.get("maps_to") else ()
                claim_ids = (claim_id,) if claim_id else ()
                review_rule_ids = resolve_review_rule_ids(ir, {}, field_ids, claim_ids)
                for example in payload.get("examples", ()) or ():
                    text = compact_text(str(example))
                    if not text:
                        continue
                    source_paths, source_hashes = merged_provenance((path,))
                    rows.append(
                        CompiledRetrievalExemplarRow(
                            exemplar_id=_make_exemplar_id(ir.manifest.pack_id, str(claim_name), text),
                            text=text,
                            category=str(claim_name),
                            linked_field_ids=tuple(sorted(field_ids)),
                            linked_claim_family_ids=tuple(sorted(claim_ids)),
                            linked_review_rule_ids=review_rule_ids,
                            modalities=tuple(sorted(admitted_modalities(ir))),
                            discourse_profiles=DEFAULT_DISCOURSE_PROFILES,
                            weight=0.92,
                            source_paths=source_paths,
                            source_hashes=source_hashes,
                            source_kind="claim_family_example",
                            runtime_class=_runtime_class("claim_family_example"),
                            authoritative_source_role="enhanced_machine",
                            anchor_terms=anchor_terms_from_text(text),
                            text_fingerprint=text_fingerprint(text),
                            has_field_links=bool(field_ids),
                            has_claim_links=bool(claim_ids),
                        )
                    )
                for cue in payload.get("strong_cues", ()) or payload.get("evidence_patterns", ()) or ():
                    text = compact_text(str(cue))
                    if not text:
                        continue
                    source_paths, source_hashes = merged_provenance((path,))
                    rows.append(
                        CompiledRetrievalExemplarRow(
                            exemplar_id=_make_exemplar_id(ir.manifest.pack_id, str(claim_name), text),
                            text=text,
                            category=str(claim_name),
                            linked_field_ids=tuple(sorted(field_ids)),
                            linked_claim_family_ids=tuple(sorted(claim_ids)),
                            linked_review_rule_ids=review_rule_ids,
                            modalities=tuple(sorted(admitted_modalities(ir))),
                            discourse_profiles=DEFAULT_DISCOURSE_PROFILES,
                            weight=0.72,
                            source_paths=source_paths,
                            source_hashes=source_hashes,
                            source_kind="claim_family_cue_phrase",
                            runtime_class=_runtime_class("claim_family_cue_phrase"),
                            authoritative_source_role="enhanced_machine",
                            anchor_terms=anchor_terms_from_text(text),
                            text_fingerprint=text_fingerprint(text),
                            has_field_links=bool(field_ids),
                            has_claim_links=bool(claim_ids),
                        )
                    )

        for def_key in ("pre_field_definitions", "post_field_definitions"):
            field_defs = doc.get(def_key)
            if not isinstance(field_defs, Mapping):
                continue
            for field_path, payload in field_defs.items():
                if not isinstance(payload, Mapping):
                    continue
                try:
                    field_ids = resolve_field_ids(ir, {"linked_field_paths": [field_path]})
                except ContractLoadError:
                    continue
                claim_ids = resolve_claim_family_ids(ir, {"linked_claim_families": payload.get("linked_claim_families", ()) or ()})
                review_rule_ids = resolve_review_rule_ids(ir, {}, field_ids, claim_ids)
                for example in payload.get("examples", ()) or ():
                    text = compact_text(str(example))
                    if not text:
                        continue
                    source_paths, source_hashes = merged_provenance((path,))
                    rows.append(
                        CompiledRetrievalExemplarRow(
                            exemplar_id=_make_exemplar_id(ir.manifest.pack_id, str(field_path), text),
                            text=text,
                            category=str(field_path),
                            linked_field_ids=tuple(sorted(field_ids)),
                            linked_claim_family_ids=tuple(sorted(claim_ids)),
                            linked_review_rule_ids=review_rule_ids,
                            modalities=tuple(sorted(admitted_modalities(ir))),
                            discourse_profiles=DEFAULT_DISCOURSE_PROFILES,
                            weight=0.88,
                            source_paths=source_paths,
                            source_hashes=source_hashes,
                            source_kind="field_example",
                            runtime_class=_runtime_class("field_example"),
                            authoritative_source_role="field_catalog",
                            anchor_terms=anchor_terms_from_text(text),
                            text_fingerprint=text_fingerprint(text),
                            has_field_links=True,
                            has_claim_links=bool(claim_ids),
                        )
                    )
                for cue in payload.get("evidence_cues", ()) or payload.get("strong_cues", ()) or ():
                    text = compact_text(str(cue))
                    if not text:
                        continue
                    source_paths, source_hashes = merged_provenance((path,))
                    rows.append(
                        CompiledRetrievalExemplarRow(
                            exemplar_id=_make_exemplar_id(ir.manifest.pack_id, str(field_path), text),
                            text=text,
                            category=str(field_path),
                            linked_field_ids=tuple(sorted(field_ids)),
                            linked_claim_family_ids=tuple(sorted(claim_ids)),
                            linked_review_rule_ids=review_rule_ids,
                            modalities=tuple(sorted(admitted_modalities(ir))),
                            discourse_profiles=DEFAULT_DISCOURSE_PROFILES,
                            weight=0.6,
                            source_paths=source_paths,
                            source_hashes=source_hashes,
                            source_kind="field_cue_phrase",
                            runtime_class=_runtime_class("field_cue_phrase"),
                            authoritative_source_role="field_catalog",
                            anchor_terms=anchor_terms_from_text(text),
                            text_fingerprint=text_fingerprint(text),
                            has_field_links=True,
                            has_claim_links=bool(claim_ids),
                        )
                    )

        purtera_alignment = doc.get("purtera_alignment") or doc.get("company_context")
        if isinstance(purtera_alignment, Mapping):
            vocab = (
                purtera_alignment.get("service_vocabulary_boost")
                or purtera_alignment.get("public_service_vocabulary")
                or ()
            )
            for phrase in vocab:
                text = compact_text(str(phrase))
                if not text:
                    continue
                field_ids = resolve_field_ids(
                    ir,
                    {"linked_field_paths": ["service_category", "scope_overview", "technical_environment.current_state"]},
                )
                claim_ids = resolve_claim_family_ids(
                    ir,
                    {"linked_claim_families": ["request_context", "scope_included_claim", "technical_environment_claim"]},
                )
                review_rule_ids = resolve_review_rule_ids(ir, {}, field_ids, claim_ids)
                source_paths, source_hashes = merged_provenance((path,))
                rows.append(
                    CompiledRetrievalExemplarRow(
                        exemplar_id=_make_exemplar_id(ir.manifest.pack_id, "service_vocabulary", text),
                        text=text,
                        category="service_vocabulary",
                        linked_field_ids=field_ids,
                        linked_claim_family_ids=claim_ids,
                        linked_review_rule_ids=review_rule_ids,
                        modalities=tuple(sorted(admitted_modalities(ir))),
                        discourse_profiles=DEFAULT_DISCOURSE_PROFILES,
                        weight=0.5,
                        source_paths=source_paths,
                        source_hashes=source_hashes,
                        source_kind="service_vocabulary",
                        runtime_class=_runtime_class("service_vocabulary"),
                        authoritative_source_role="enhanced_machine",
                        anchor_terms=anchor_terms_from_text(text),
                        text_fingerprint=text_fingerprint(text),
                        has_field_links=bool(field_ids),
                        has_claim_links=bool(claim_ids),
                    )
                )
    return rows


def to_jsonable_row(row: CompiledRetrievalExemplarRow) -> dict[str, Any]:
    return {
        "exemplar_id": row.exemplar_id,
        "text": row.text,
        "category": row.category,
        "linked_field_ids": list(row.linked_field_ids),
        "linked_claim_family_ids": list(row.linked_claim_family_ids),
        "linked_review_rule_ids": list(row.linked_review_rule_ids),
        "modalities": list(row.modalities),
        "discourse_profiles": list(row.discourse_profiles),
        "weight": row.weight,
        "source_paths": list(row.source_paths),
        "source_hashes": list(row.source_hashes),
        "source_kind": row.source_kind,
        "runtime_class": row.runtime_class,
        "authoritative_source_role": row.authoritative_source_role,
        "anchor_terms": list(row.anchor_terms),
        "text_fingerprint": row.text_fingerprint,
        "has_field_links": row.has_field_links,
        "has_claim_links": row.has_claim_links,
    }


def to_jsonable_summary(summary: RetrievalExemplarSummary) -> dict[str, Any]:
    return {
        "total_exemplars": summary.total_exemplars,
        "curated_exemplar_count": summary.curated_exemplar_count,
        "harvested_exemplar_count": summary.harvested_exemplar_count,
        "exemplars_by_category": dict(summary.exemplars_by_category),
        "exemplars_by_source_kind": dict(summary.exemplars_by_source_kind),
        "exemplars_by_runtime_class": dict(summary.exemplars_by_runtime_class),
        "exemplars_by_discourse_profile": dict(summary.exemplars_by_discourse_profile),
        "exemplars_by_modality": dict(summary.exemplars_by_modality),
        "exemplars_without_field_links": list(summary.exemplars_without_field_links),
        "exemplars_without_claim_links": list(summary.exemplars_without_claim_links),
        "average_weight": summary.average_weight,
        "max_weight": summary.max_weight,
        "min_weight": summary.min_weight,
    }


def to_jsonable_diagnostic(diag: RetrievalExemplarDiagnostic) -> dict[str, Any]:
    return {
        "level": diag.level,
        "code": diag.code,
        "message": diag.message,
        "exemplar_id": diag.exemplar_id,
        "context": dict(diag.context),
    }


def compile_retrieval_exemplars(
    ir: CanonicalIR,
    *,
    curated_examples_paths: Sequence[PathLike] = (),
    semantic_contract_paths: Sequence[PathLike] = (),
) -> CompiledRetrievalExemplarTable:
    rows: list[CompiledRetrievalExemplarRow] = []
    rows.extend(_rows_from_ir(ir))
    rows.extend(_rows_from_semantic_docs(ir, semantic_contract_paths))

    for path, doc in load_structured_documents(curated_examples_paths):
        raw_rows = doc.get("retrieval_exemplars")
        if raw_rows is None:
            continue
        if not isinstance(raw_rows, Sequence):
            raise ContractLoadError(f"{path} retrieval_exemplars section must be a sequence")
        for raw_entry in raw_rows:
            if not isinstance(raw_entry, Mapping):
                raise ContractLoadError(f"{path} retrieval_exemplars item must be a mapping")
            try:
                rows.append(_row_from_explicit_entry(ir, raw_entry, source_path=path, source_kind="curated_yaml"))
            except ContractLoadError:
                # Curated sidecars may include future schema links; skip unknown links without blocking compile.
                continue

    deduped = _ensure_unique_exemplar_ids(_dedupe_rows(rows))
    indices = _build_indices(deduped)
    diagnostics = _build_diagnostics(deduped)
    summary = _build_summary(deduped)
    return CompiledRetrievalExemplarTable(
        rows=deduped,
        by_exemplar_id=indices["by_exemplar_id"],
        by_category=indices["by_category"],
        by_field_id=indices["by_field_id"],
        by_claim_family_id=indices["by_claim_family_id"],
        by_review_rule_id=indices["by_review_rule_id"],
        by_modality=indices["by_modality"],
        by_discourse_profile=indices["by_discourse_profile"],
        by_source_kind=indices["by_source_kind"],
        by_runtime_class=indices["by_runtime_class"],
        diagnostics=diagnostics,
        summary=summary,
    )
