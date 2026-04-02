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
class CompiledNegativeExampleRow:
    negative_example_id: str
    text: str
    category: str
    linked_field_ids: tuple[str, ...]
    linked_claim_family_ids: tuple[str, ...]
    linked_review_rule_ids: tuple[str, ...]
    modalities: tuple[str, ...]
    discourse_profiles: tuple[str, ...]
    severity: str
    source_paths: tuple[str, ...]
    source_hashes: tuple[str, ...]
    source_kind: str
    runtime_class: str
    authoritative_source_role: str
    text_fingerprint: str
    has_field_links: bool
    has_claim_links: bool


@dataclass(frozen=True)
class NegativeExampleDiagnostic:
    level: str
    code: str
    message: str
    negative_example_id: str | None = None
    context: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class NegativeExampleSummary:
    total_negative_examples: int
    curated_negative_count: int
    harvested_negative_count: int
    negatives_by_category: Mapping[str, int]
    negatives_by_source_kind: Mapping[str, int]
    negatives_by_runtime_class: Mapping[str, int]
    negatives_by_severity: Mapping[str, int]
    negatives_by_discourse_profile: Mapping[str, int]
    negatives_by_modality: Mapping[str, int]
    negatives_without_field_links: tuple[str, ...]
    negatives_without_claim_links: tuple[str, ...]


@dataclass(frozen=True)
class CompiledNegativeExampleTable:
    rows: tuple[CompiledNegativeExampleRow, ...]
    by_negative_example_id: Mapping[str, CompiledNegativeExampleRow]
    by_category: Mapping[str, tuple[str, ...]]
    by_field_id: Mapping[str, tuple[str, ...]]
    by_claim_family_id: Mapping[str, tuple[str, ...]]
    by_review_rule_id: Mapping[str, tuple[str, ...]]
    by_modality: Mapping[str, tuple[str, ...]]
    by_discourse_profile: Mapping[str, tuple[str, ...]]
    by_source_kind: Mapping[str, tuple[str, ...]]
    by_runtime_class: Mapping[str, tuple[str, ...]]
    by_severity: Mapping[str, tuple[str, ...]]
    diagnostics: tuple[NegativeExampleDiagnostic, ...]
    summary: NegativeExampleSummary


def _make_negative_id(pack_id: str, category: str, text: str) -> str:
    return f"negative:{slugify(pack_id)}:{slugify(category)}:{text_fingerprint(text)[:10]}"


def _runtime_class(source_kind: str) -> str:
    if source_kind == "curated_yaml":
        return "curated_artifact_negative"
    if source_kind == "modality_watchout":
        return "modality_watchout"
    if source_kind == "hardening_rule":
        return "policy_guardrail"
    if source_kind in {"claim_family_negative_pattern", "field_anti_evidence", "field_confusion", "field_avoid_when"}:
        return "semantic_guardrail"
    if source_kind == "company_boilerplate_negative":
        return "boilerplate_negative"
    return "artifact_negative"


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


def _severity_for_text(text: str, default: str = "medium") -> str:
    lowered = compact_text(text).lower()
    high_tokens = ("do not", "not ", "never", "quote", "signature", "confidential", "draft", "subject to")
    if any(token in lowered for token in high_tokens):
        return "high"
    if "may" in lowered or "could" in lowered or "might" in lowered:
        return "medium"
    return default


def _dedupe_rows(rows: Sequence[CompiledNegativeExampleRow]) -> tuple[CompiledNegativeExampleRow, ...]:
    merged: dict[tuple[object, ...], CompiledNegativeExampleRow] = {}
    severity_rank = {"low": 0, "medium": 1, "high": 2}
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
        keep = existing if existing.source_kind == "curated_yaml" else row
        merged[key] = CompiledNegativeExampleRow(
            negative_example_id=existing.negative_example_id,
            text=existing.text,
            category=existing.category,
            linked_field_ids=existing.linked_field_ids,
            linked_claim_family_ids=existing.linked_claim_family_ids,
            linked_review_rule_ids=linked_rule_ids,
            modalities=existing.modalities,
            discourse_profiles=existing.discourse_profiles,
            severity=max((existing.severity, row.severity), key=lambda value: severity_rank.get(value, 1)),
            source_paths=source_paths,
            source_hashes=source_hashes,
            source_kind=keep.source_kind,
            runtime_class=keep.runtime_class,
            authoritative_source_role=keep.authoritative_source_role,
            text_fingerprint=existing.text_fingerprint,
            has_field_links=existing.has_field_links or row.has_field_links,
            has_claim_links=existing.has_claim_links or row.has_claim_links,
        )
    return tuple(sorted(merged.values(), key=lambda row: row.negative_example_id))


def _ensure_unique_negative_ids(rows: tuple[CompiledNegativeExampleRow, ...]) -> tuple[CompiledNegativeExampleRow, ...]:
    seen: dict[str, int] = {}
    out: list[CompiledNegativeExampleRow] = []
    for row in rows:
        base = row.negative_example_id
        idx = seen.get(base, 0)
        seen[base] = idx + 1
        if idx == 0:
            out.append(row)
            continue
        out.append(replace(row, negative_example_id=f"{base}:{idx}"))
    return tuple(sorted(out, key=lambda row: row.negative_example_id))


def _build_indices(rows: tuple[CompiledNegativeExampleRow, ...]) -> dict[str, Mapping[str, tuple[str, ...]] | Mapping[str, CompiledNegativeExampleRow]]:
    by_negative_example_id = MappingProxyType({row.negative_example_id: row for row in rows})

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
    by_severity: dict[str, list[str]] = defaultdict(list)

    for row in rows:
        by_category[row.category].append(row.negative_example_id)
        by_source_kind[row.source_kind].append(row.negative_example_id)
        by_runtime_class[row.runtime_class].append(row.negative_example_id)
        by_severity[row.severity].append(row.negative_example_id)
        for field_id in row.linked_field_ids:
            by_field_id[field_id].append(row.negative_example_id)
        for claim_id in row.linked_claim_family_ids:
            by_claim_family_id[claim_id].append(row.negative_example_id)
        for rule_id in row.linked_review_rule_ids:
            by_review_rule_id[rule_id].append(row.negative_example_id)
        for modality in row.modalities:
            by_modality[modality].append(row.negative_example_id)
        for profile in row.discourse_profiles:
            by_discourse_profile[profile].append(row.negative_example_id)

    return {
        "by_negative_example_id": by_negative_example_id,
        "by_category": bucket(by_category),
        "by_field_id": bucket(by_field_id),
        "by_claim_family_id": bucket(by_claim_family_id),
        "by_review_rule_id": bucket(by_review_rule_id),
        "by_modality": bucket(by_modality),
        "by_discourse_profile": bucket(by_discourse_profile),
        "by_source_kind": bucket(by_source_kind),
        "by_runtime_class": bucket(by_runtime_class),
        "by_severity": bucket(by_severity),
    }


def _build_summary(rows: tuple[CompiledNegativeExampleRow, ...]) -> NegativeExampleSummary:
    negatives_by_category: dict[str, int] = defaultdict(int)
    negatives_by_source_kind: dict[str, int] = defaultdict(int)
    negatives_by_runtime_class: dict[str, int] = defaultdict(int)
    negatives_by_severity: dict[str, int] = defaultdict(int)
    negatives_by_discourse_profile: dict[str, int] = defaultdict(int)
    negatives_by_modality: dict[str, int] = defaultdict(int)
    without_fields: list[str] = []
    without_claims: list[str] = []
    curated_count = 0
    harvested_count = 0

    for row in rows:
        negatives_by_category[row.category] += 1
        negatives_by_source_kind[row.source_kind] += 1
        negatives_by_runtime_class[row.runtime_class] += 1
        negatives_by_severity[row.severity] += 1
        if row.source_kind == "curated_yaml":
            curated_count += 1
        else:
            harvested_count += 1
        if not row.linked_field_ids:
            without_fields.append(row.negative_example_id)
        if not row.linked_claim_family_ids:
            without_claims.append(row.negative_example_id)
        for profile in row.discourse_profiles:
            negatives_by_discourse_profile[profile] += 1
        for modality in row.modalities:
            negatives_by_modality[modality] += 1

    return NegativeExampleSummary(
        total_negative_examples=len(rows),
        curated_negative_count=curated_count,
        harvested_negative_count=harvested_count,
        negatives_by_category=MappingProxyType(dict(sorted(negatives_by_category.items()))),
        negatives_by_source_kind=MappingProxyType(dict(sorted(negatives_by_source_kind.items()))),
        negatives_by_runtime_class=MappingProxyType(dict(sorted(negatives_by_runtime_class.items()))),
        negatives_by_severity=MappingProxyType(dict(sorted(negatives_by_severity.items()))),
        negatives_by_discourse_profile=MappingProxyType(dict(sorted(negatives_by_discourse_profile.items()))),
        negatives_by_modality=MappingProxyType(dict(sorted(negatives_by_modality.items()))),
        negatives_without_field_links=tuple(sorted(without_fields)),
        negatives_without_claim_links=tuple(sorted(without_claims)),
    )


def _build_diagnostics(rows: tuple[CompiledNegativeExampleRow, ...]) -> tuple[NegativeExampleDiagnostic, ...]:
    diagnostics: list[NegativeExampleDiagnostic] = []
    for row in rows:
        if not row.text:
            diagnostics.append(
                NegativeExampleDiagnostic(
                    level="error",
                    code="negative_example.empty_text",
                    message="Negative example has empty text.",
                    negative_example_id=row.negative_example_id,
                )
            )
        if row.severity not in {"low", "medium", "high"}:
            diagnostics.append(
                NegativeExampleDiagnostic(
                    level="error",
                    code="negative_example.invalid_severity",
                    message=f"Negative example has invalid severity {row.severity!r}.",
                    negative_example_id=row.negative_example_id,
                )
            )
        if not row.linked_field_ids and not row.linked_claim_family_ids and row.runtime_class not in {"boilerplate_negative", "policy_guardrail", "modality_watchout"}:
            diagnostics.append(
                NegativeExampleDiagnostic(
                    level="warning",
                    code="negative_example.unlinked",
                    message="Negative example has no linked fields or claim families.",
                    negative_example_id=row.negative_example_id,
                )
            )
    return tuple(diagnostics)


def _row_from_explicit_entry(
    ir: CanonicalIR,
    raw_entry: Mapping[str, Any],
    *,
    source_path: Path,
    source_kind: str,
) -> CompiledNegativeExampleRow:
    text = compact_text(str(raw_entry.get("text") or ""))
    if not text:
        raise ContractLoadError(f"Negative example entry in {source_path} is missing text")
    category = str(raw_entry.get("category") or "uncategorized")
    field_ids = resolve_field_ids(ir, raw_entry)
    claim_ids = resolve_claim_family_ids(ir, raw_entry)
    review_rule_ids = resolve_review_rule_ids(ir, raw_entry, field_ids, claim_ids)
    modalities = resolve_modalities(ir, raw_entry)
    profiles = resolve_discourse_profiles(raw_entry)
    severity = str(raw_entry.get("severity") or _severity_for_text(text))
    negative_example_id = str(raw_entry.get("negative_example_id") or _make_negative_id(ir.manifest.pack_id, category, text))
    source_paths, source_hashes = merged_provenance((source_path,))
    return CompiledNegativeExampleRow(
        negative_example_id=negative_example_id,
        text=text,
        category=category,
        linked_field_ids=field_ids,
        linked_claim_family_ids=claim_ids,
        linked_review_rule_ids=review_rule_ids,
        modalities=modalities,
        discourse_profiles=profiles,
        severity=severity,
        source_paths=source_paths,
        source_hashes=source_hashes,
        source_kind=source_kind,
        runtime_class=_runtime_class(source_kind),
        authoritative_source_role="curated_examples" if source_kind == "curated_yaml" else "enhanced_machine",
        text_fingerprint=text_fingerprint(text),
        has_field_links=bool(field_ids),
        has_claim_links=bool(claim_ids),
    )


def _claim_field_links(claim: CanonicalClaimFamilySpec) -> tuple[str, ...]:
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


def _rows_from_ir(ir: CanonicalIR) -> list[CompiledNegativeExampleRow]:
    rows: list[CompiledNegativeExampleRow] = []
    field_role_paths, field_role_hashes = _paths_and_hashes_for_role(ir, "field_catalog")
    claim_role_paths, claim_role_hashes = _paths_and_hashes_for_role(ir, "enhanced_machine")

    for claim in ir.claim_families.values():
        for phrase in claim.negative_patterns:
            text = compact_text(phrase)
            if not text:
                continue
            rows.append(
                CompiledNegativeExampleRow(
                    negative_example_id=_make_negative_id(ir.manifest.pack_id, claim.name, text),
                    text=text,
                    category=claim.name,
                    linked_field_ids=_claim_field_links(claim),
                    linked_claim_family_ids=(claim.claim_family_id,),
                    linked_review_rule_ids=tuple(sorted(claim.linked_review_rule_ids)),
                    modalities=tuple(sorted(ir.manifest.admitted_modalities)),
                    discourse_profiles=DEFAULT_DISCOURSE_PROFILES,
                    severity=_severity_for_text(text),
                    source_paths=claim_role_paths,
                    source_hashes=claim_role_hashes,
                    source_kind="claim_family_negative_pattern",
                    runtime_class=_runtime_class("claim_family_negative_pattern"),
                    authoritative_source_role=claim.authoritative_source_role,
                    text_fingerprint=text_fingerprint(text),
                    has_field_links=bool(claim.projection_target_field_ids),
                    has_claim_links=True,
                )
            )

    for field in ir.fields.values():
        for phrase in field.anti_evidence_cues:
            text = compact_text(phrase)
            if not text:
                continue
            rows.append(
                CompiledNegativeExampleRow(
                    negative_example_id=_make_negative_id(ir.manifest.pack_id, field.field_name, text),
                    text=text,
                    category=field.field_name,
                    linked_field_ids=_field_links(field),
                    linked_claim_family_ids=tuple(sorted(field.linked_claim_family_ids)),
                    linked_review_rule_ids=tuple(sorted(field.linked_review_rule_ids)),
                    modalities=field.allowed_modalities,
                    discourse_profiles=DEFAULT_DISCOURSE_PROFILES,
                    severity=_severity_for_text(text),
                    source_paths=field_role_paths,
                    source_hashes=field_role_hashes,
                    source_kind="field_anti_evidence",
                    runtime_class=_runtime_class("field_anti_evidence"),
                    authoritative_source_role=field.authoritative_source_role,
                    text_fingerprint=text_fingerprint(text),
                    has_field_links=True,
                    has_claim_links=bool(field.linked_claim_family_ids),
                )
            )
        for phrase in field.confusions:
            text = compact_text(phrase)
            if not text:
                continue
            rows.append(
                CompiledNegativeExampleRow(
                    negative_example_id=_make_negative_id(ir.manifest.pack_id, field.field_name, text),
                    text=text,
                    category=field.field_name,
                    linked_field_ids=_field_links(field),
                    linked_claim_family_ids=tuple(sorted(field.linked_claim_family_ids)),
                    linked_review_rule_ids=tuple(sorted(field.linked_review_rule_ids)),
                    modalities=field.allowed_modalities,
                    discourse_profiles=DEFAULT_DISCOURSE_PROFILES,
                    severity=_severity_for_text(text),
                    source_paths=field_role_paths,
                    source_hashes=field_role_hashes,
                    source_kind="field_confusion",
                    runtime_class=_runtime_class("field_confusion"),
                    authoritative_source_role=field.authoritative_source_role,
                    text_fingerprint=text_fingerprint(text),
                    has_field_links=True,
                    has_claim_links=bool(field.linked_claim_family_ids),
                )
            )
    return rows


def _rows_from_semantic_docs(
    ir: CanonicalIR,
    semantic_contract_paths: Sequence[PathLike],
) -> list[CompiledNegativeExampleRow]:
    rows: list[CompiledNegativeExampleRow] = []
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
                for text_value in payload.get("anti_confusions", ()) or payload.get("negative_patterns", ()) or ():
                    text = compact_text(str(text_value))
                    if not text:
                        continue
                    source_paths, source_hashes = merged_provenance((path,))
                    rows.append(
                        CompiledNegativeExampleRow(
                            negative_example_id=_make_negative_id(ir.manifest.pack_id, str(claim_name), text),
                            text=text,
                            category=str(claim_name),
                            linked_field_ids=tuple(sorted(field_ids)),
                            linked_claim_family_ids=tuple(sorted(claim_ids)),
                            linked_review_rule_ids=review_rule_ids,
                            modalities=tuple(sorted(ir.manifest.admitted_modalities)),
                            discourse_profiles=DEFAULT_DISCOURSE_PROFILES,
                            severity=_severity_for_text(text),
                            source_paths=source_paths,
                            source_hashes=source_hashes,
                            source_kind="claim_family_negative_pattern",
                            runtime_class=_runtime_class("claim_family_negative_pattern"),
                            authoritative_source_role="enhanced_machine",
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
                for text_value in payload.get("anti_evidence_cues", ()) or ():
                    text = compact_text(str(text_value))
                    if not text:
                        continue
                    source_paths, source_hashes = merged_provenance((path,))
                    rows.append(
                        CompiledNegativeExampleRow(
                            negative_example_id=_make_negative_id(ir.manifest.pack_id, str(field_path), text),
                            text=text,
                            category=str(field_path),
                            linked_field_ids=tuple(sorted(field_ids)),
                            linked_claim_family_ids=tuple(sorted(claim_ids)),
                            linked_review_rule_ids=review_rule_ids,
                            modalities=tuple(sorted(ir.manifest.admitted_modalities)),
                            discourse_profiles=DEFAULT_DISCOURSE_PROFILES,
                            severity=_severity_for_text(text),
                            source_paths=source_paths,
                            source_hashes=source_hashes,
                            source_kind="field_anti_evidence",
                            runtime_class=_runtime_class("field_anti_evidence"),
                            authoritative_source_role="field_catalog",
                            text_fingerprint=text_fingerprint(text),
                            has_field_links=True,
                            has_claim_links=bool(claim_ids),
                        )
                    )
                for text_value in payload.get("confusions", ()) or ():
                    text = compact_text(str(text_value))
                    if not text:
                        continue
                    source_paths, source_hashes = merged_provenance((path,))
                    rows.append(
                        CompiledNegativeExampleRow(
                            negative_example_id=_make_negative_id(ir.manifest.pack_id, str(field_path), text),
                            text=text,
                            category=str(field_path),
                            linked_field_ids=tuple(sorted(field_ids)),
                            linked_claim_family_ids=tuple(sorted(claim_ids)),
                            linked_review_rule_ids=review_rule_ids,
                            modalities=tuple(sorted(ir.manifest.admitted_modalities)),
                            discourse_profiles=DEFAULT_DISCOURSE_PROFILES,
                            severity=_severity_for_text(text),
                            source_paths=source_paths,
                            source_hashes=source_hashes,
                            source_kind="field_confusion",
                            runtime_class=_runtime_class("field_confusion"),
                            authoritative_source_role="field_catalog",
                            text_fingerprint=text_fingerprint(text),
                            has_field_links=True,
                            has_claim_links=bool(claim_ids),
                        )
                    )
                avoid_when = payload.get("avoid_when")
                if isinstance(avoid_when, str) and compact_text(avoid_when):
                    text = compact_text(avoid_when)
                    source_paths, source_hashes = merged_provenance((path,))
                    rows.append(
                        CompiledNegativeExampleRow(
                            negative_example_id=_make_negative_id(ir.manifest.pack_id, str(field_path), text),
                            text=text,
                            category=str(field_path),
                            linked_field_ids=tuple(sorted(field_ids)),
                            linked_claim_family_ids=tuple(sorted(claim_ids)),
                            linked_review_rule_ids=review_rule_ids,
                            modalities=tuple(sorted(ir.manifest.admitted_modalities)),
                            discourse_profiles=DEFAULT_DISCOURSE_PROFILES,
                            severity=_severity_for_text(text),
                            source_paths=source_paths,
                            source_hashes=source_hashes,
                            source_kind="field_avoid_when",
                            runtime_class=_runtime_class("field_avoid_when"),
                            authoritative_source_role="field_catalog",
                            text_fingerprint=text_fingerprint(text),
                            has_field_links=True,
                            has_claim_links=bool(claim_ids),
                        )
                    )

        modality_profiles = doc.get("modality_profiles")
        if isinstance(modality_profiles, Mapping):
            for modality, payload in modality_profiles.items():
                if not isinstance(payload, Mapping):
                    continue
                watchouts = payload.get("watchouts", ()) or ()
                if isinstance(watchouts, str):
                    watchouts = (watchouts,)
                for watchout in watchouts:
                    text = compact_text(str(watchout))
                    if not text:
                        continue
                    source_paths, source_hashes = merged_provenance((path,))
                    rows.append(
                        CompiledNegativeExampleRow(
                            negative_example_id=_make_negative_id(ir.manifest.pack_id, str(modality), text),
                            text=text,
                            category="modality_watchout",
                            linked_field_ids=(),
                            linked_claim_family_ids=(),
                            linked_review_rule_ids=(),
                            modalities=(str(modality),),
                            discourse_profiles=DEFAULT_DISCOURSE_PROFILES,
                            severity="medium",
                            source_paths=source_paths,
                            source_hashes=source_hashes,
                            source_kind="modality_watchout",
                            runtime_class=_runtime_class("modality_watchout"),
                            authoritative_source_role="enhanced_machine",
                            text_fingerprint=text_fingerprint(text),
                            has_field_links=False,
                            has_claim_links=False,
                        )
                    )

        hardening_rules = doc.get("hardening_rules")
        if isinstance(hardening_rules, Mapping):
            for category, rules in hardening_rules.items():
                if isinstance(rules, str):
                    rules = (rules,)
                if not isinstance(rules, Sequence):
                    continue
                for rule_text in rules:
                    text = compact_text(str(rule_text))
                    if not text:
                        continue
                    source_paths, source_hashes = merged_provenance((path,))
                    rows.append(
                        CompiledNegativeExampleRow(
                            negative_example_id=_make_negative_id(ir.manifest.pack_id, str(category), text),
                            text=text,
                            category=str(category),
                            linked_field_ids=(),
                            linked_claim_family_ids=(),
                            linked_review_rule_ids=(),
                            modalities=tuple(sorted(ir.manifest.admitted_modalities)),
                            discourse_profiles=DEFAULT_DISCOURSE_PROFILES,
                            severity="high",
                            source_paths=source_paths,
                            source_hashes=source_hashes,
                            source_kind="hardening_rule",
                            runtime_class=_runtime_class("hardening_rule"),
                            authoritative_source_role="enhanced_machine",
                            text_fingerprint=text_fingerprint(text),
                            has_field_links=False,
                            has_claim_links=False,
                        )
                    )

        company_context = doc.get("company_context") or doc.get("purtera_alignment")
        if isinstance(company_context, Mapping):
            stems = company_context.get("marketing_boilerplate_negative_stems", ()) or ()
            for stem in stems:
                text = compact_text(str(stem))
                if not text:
                    continue
                source_paths, source_hashes = merged_provenance((path,))
                rows.append(
                    CompiledNegativeExampleRow(
                        negative_example_id=_make_negative_id(ir.manifest.pack_id, "generic_sales_language", text),
                        text=text,
                        category="generic_sales_language",
                        linked_field_ids=(),
                        linked_claim_family_ids=(),
                        linked_review_rule_ids=(),
                        modalities=tuple(sorted(ir.manifest.admitted_modalities)),
                        discourse_profiles=DEFAULT_DISCOURSE_PROFILES,
                        severity="medium",
                        source_paths=source_paths,
                        source_hashes=source_hashes,
                        source_kind="company_boilerplate_negative",
                        runtime_class=_runtime_class("company_boilerplate_negative"),
                        authoritative_source_role="enhanced_machine",
                        text_fingerprint=text_fingerprint(text),
                        has_field_links=False,
                        has_claim_links=False,
                    )
                )
    return rows


def to_jsonable_row(row: CompiledNegativeExampleRow) -> dict[str, Any]:
    return {
        "negative_example_id": row.negative_example_id,
        "text": row.text,
        "category": row.category,
        "linked_field_ids": list(row.linked_field_ids),
        "linked_claim_family_ids": list(row.linked_claim_family_ids),
        "linked_review_rule_ids": list(row.linked_review_rule_ids),
        "modalities": list(row.modalities),
        "discourse_profiles": list(row.discourse_profiles),
        "severity": row.severity,
        "source_paths": list(row.source_paths),
        "source_hashes": list(row.source_hashes),
        "source_kind": row.source_kind,
        "runtime_class": row.runtime_class,
        "authoritative_source_role": row.authoritative_source_role,
        "text_fingerprint": row.text_fingerprint,
        "has_field_links": row.has_field_links,
        "has_claim_links": row.has_claim_links,
    }


def to_jsonable_summary(summary: NegativeExampleSummary) -> dict[str, Any]:
    return {
        "total_negative_examples": summary.total_negative_examples,
        "curated_negative_count": summary.curated_negative_count,
        "harvested_negative_count": summary.harvested_negative_count,
        "negatives_by_category": dict(summary.negatives_by_category),
        "negatives_by_source_kind": dict(summary.negatives_by_source_kind),
        "negatives_by_runtime_class": dict(summary.negatives_by_runtime_class),
        "negatives_by_severity": dict(summary.negatives_by_severity),
        "negatives_by_discourse_profile": dict(summary.negatives_by_discourse_profile),
        "negatives_by_modality": dict(summary.negatives_by_modality),
        "negatives_without_field_links": list(summary.negatives_without_field_links),
        "negatives_without_claim_links": list(summary.negatives_without_claim_links),
    }


def to_jsonable_diagnostic(diag: NegativeExampleDiagnostic) -> dict[str, Any]:
    return {
        "level": diag.level,
        "code": diag.code,
        "message": diag.message,
        "negative_example_id": diag.negative_example_id,
        "context": dict(diag.context),
    }


def compile_negative_examples(
    ir: CanonicalIR,
    *,
    curated_examples_paths: Sequence[PathLike] = (),
    semantic_contract_paths: Sequence[PathLike] = (),
) -> CompiledNegativeExampleTable:
    rows: list[CompiledNegativeExampleRow] = []
    rows.extend(_rows_from_ir(ir))
    rows.extend(_rows_from_semantic_docs(ir, semantic_contract_paths))

    for path, doc in load_structured_documents(curated_examples_paths):
        raw_rows = doc.get("negative_examples")
        if raw_rows is None:
            continue
        if not isinstance(raw_rows, Sequence):
            raise ContractLoadError(f"{path} negative_examples section must be a sequence")
        for raw_entry in raw_rows:
            if not isinstance(raw_entry, Mapping):
                raise ContractLoadError(f"{path} negative_examples item must be a mapping")
            try:
                rows.append(_row_from_explicit_entry(ir, raw_entry, source_path=path, source_kind="curated_yaml"))
            except ContractLoadError:
                # Curated sidecars may include future schema links; skip unknown links without blocking compile.
                continue

    deduped = _ensure_unique_negative_ids(_dedupe_rows(rows))
    indices = _build_indices(deduped)
    diagnostics = _build_diagnostics(deduped)
    summary = _build_summary(deduped)
    return CompiledNegativeExampleTable(
        rows=deduped,
        by_negative_example_id=indices["by_negative_example_id"],
        by_category=indices["by_category"],
        by_field_id=indices["by_field_id"],
        by_claim_family_id=indices["by_claim_family_id"],
        by_review_rule_id=indices["by_review_rule_id"],
        by_modality=indices["by_modality"],
        by_discourse_profile=indices["by_discourse_profile"],
        by_source_kind=indices["by_source_kind"],
        by_runtime_class=indices["by_runtime_class"],
        by_severity=indices["by_severity"],
        diagnostics=diagnostics,
        summary=summary,
    )
