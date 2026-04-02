from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence, TypeAlias

import yaml

from orbitbrief_core.compiler.core.canonical_ir import CanonicalIR
from orbitbrief_core.compiler.core.load_contracts import ContractLoadError

PathLike: TypeAlias = str | Path
DEFAULT_DISCOURSE_PROFILES: tuple[str, ...] = (
    "call_transcript",
    "meeting_notes",
    "email_thread",
    "project_memo",
    "hybrid_notes_memo",
)


def compact_text(text: str) -> str:
    return " ".join(str(text).split()).strip()


def slugify(value: str) -> str:
    lowered = compact_text(value).lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", lowered)
    return normalized.strip("_") or "unknown"


def text_fingerprint(text: str) -> str:
    return hashlib.sha256(compact_text(text).encode("utf-8")).hexdigest()


def path_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_path(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        raise ContractLoadError(f"Structured document path does not exist: {path}")
    if not path.is_file():
        raise ContractLoadError(f"Expected a file path, got non-file: {path}")
    suffix = path.suffix.lower()
    raw_text = path.read_text(encoding="utf-8")
    if suffix == ".json":
        data = json.loads(raw_text)
    elif suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(raw_text)
    else:
        raise ContractLoadError(f"Unsupported structured document format: {path}")
    if not isinstance(data, Mapping):
        raise ContractLoadError(f"Expected top-level mapping in {path}, got {type(data).__name__}")
    return data


def load_structured_documents(paths: Sequence[PathLike]) -> tuple[tuple[Path, Mapping[str, Any]], ...]:
    docs: list[tuple[Path, Mapping[str, Any]]] = []
    for raw_path in paths:
        path = Path(raw_path)
        docs.append((path, _read_path(path)))
    return tuple(docs)


def admitted_modalities(ir: CanonicalIR) -> tuple[str, ...]:
    return tuple(sorted(ir.manifest.admitted_modalities))


def resolve_modalities(ir: CanonicalIR, raw_entry: Mapping[str, Any], default_modalities: Sequence[str] | None = None) -> tuple[str, ...]:
    default = tuple(default_modalities or admitted_modalities(ir))
    value = raw_entry.get("modalities") or raw_entry.get("supported_modalities") or default
    if isinstance(value, str):
        modalities = (value,)
    elif isinstance(value, Sequence):
        modalities = tuple(str(v) for v in value if v is not None)
    else:
        modalities = default
    allowed = set(admitted_modalities(ir))
    unknown = sorted(set(modalities) - allowed)
    if unknown:
        raise ContractLoadError(f"Example entry references unknown modalities: {unknown}")
    return tuple(sorted(set(modalities))) or default


def resolve_discourse_profiles(raw_entry: Mapping[str, Any], default_profiles: Sequence[str] | None = None) -> tuple[str, ...]:
    default = tuple(default_profiles or DEFAULT_DISCOURSE_PROFILES)
    value = raw_entry.get("discourse_profiles") or raw_entry.get("profiles") or default
    if isinstance(value, str):
        profiles = (value,)
    elif isinstance(value, Sequence):
        profiles = tuple(str(v) for v in value if v is not None)
    else:
        profiles = default
    return tuple(sorted(set(profiles))) or default


def field_path_to_id_map(ir: CanonicalIR) -> dict[str, str]:
    return {field.field_path: field.field_id for field in ir.fields.values()}


def field_name_to_id_map(ir: CanonicalIR) -> dict[str, tuple[str, ...]]:
    buckets: dict[str, list[str]] = {}
    for field in ir.fields.values():
        buckets.setdefault(field.field_name, []).append(field.field_id)
    return {name: tuple(sorted(ids)) for name, ids in buckets.items()}


def claim_name_to_id_map(ir: CanonicalIR) -> dict[str, str]:
    return {claim.name: claim.claim_family_id for claim in ir.claim_families.values()}


def review_name_to_id_map(ir: CanonicalIR) -> dict[str, str]:
    return {rule.name: rule.rule_id for rule in ir.review_rules.values()}


def resolve_field_ids(ir: CanonicalIR, raw_entry: Mapping[str, Any]) -> tuple[str, ...]:
    valid_ids = set(ir.fields.keys())
    by_path = field_path_to_id_map(ir)
    by_name = field_name_to_id_map(ir)
    out: set[str] = set()

    for maybe_id in raw_entry.get("linked_field_ids", ()) or ():
        field_id = str(maybe_id)
        if field_id not in valid_ids:
            raise ContractLoadError(f"Unknown linked_field_id: {field_id}")
        out.add(field_id)

    for maybe_path in raw_entry.get("linked_field_paths", ()) or ():
        field_path = str(maybe_path)
        if field_path.endswith(".*"):
            prefix = field_path[:-2]
            matches = [field_id for path, field_id in by_path.items() if path == prefix or path.startswith(prefix + ".")]
            if not matches:
                raise ContractLoadError(f"Unknown linked_field_path wildcard: {field_path}")
            out.update(matches)
            continue
        field_id = by_path.get(field_path)
        if field_id is None:
            raise ContractLoadError(f"Unknown linked_field_path: {field_path}")
        out.add(field_id)

    for maybe_name in raw_entry.get("linked_field_names", ()) or ():
        field_name = str(maybe_name)
        matches = by_name.get(field_name, ())
        if not matches:
            raise ContractLoadError(f"Unknown linked_field_name: {field_name}")
        if len(matches) > 1:
            raise ContractLoadError(
                f"Ambiguous linked_field_name {field_name!r}; resolves to multiple field IDs: {matches}"
            )
        out.add(matches[0])

    return tuple(sorted(out))


def resolve_claim_family_ids(ir: CanonicalIR, raw_entry: Mapping[str, Any]) -> tuple[str, ...]:
    valid_ids = set(ir.claim_families.keys())
    by_name = claim_name_to_id_map(ir)
    out: set[str] = set()

    for maybe_id in raw_entry.get("linked_claim_family_ids", ()) or ():
        claim_id = str(maybe_id)
        if claim_id not in valid_ids:
            raise ContractLoadError(f"Unknown linked_claim_family_id: {claim_id}")
        out.add(claim_id)

    name_keys = ("linked_claim_families", "linked_claim_family_names")
    for key in name_keys:
        for maybe_name in raw_entry.get(key, ()) or ():
            claim_name = str(maybe_name)
            claim_id = by_name.get(claim_name)
            if claim_id is None:
                raise ContractLoadError(f"Unknown linked claim-family name: {claim_name}")
            out.add(claim_id)

    return tuple(sorted(out))


def resolve_review_rule_ids(ir: CanonicalIR, raw_entry: Mapping[str, Any], field_ids: Sequence[str], claim_ids: Sequence[str]) -> tuple[str, ...]:
    valid_ids = set(ir.review_rules.keys())
    by_name = review_name_to_id_map(ir)
    explicit: set[str] = set()

    for maybe_id in raw_entry.get("linked_review_rule_ids", ()) or ():
        rule_id = str(maybe_id)
        if rule_id not in valid_ids:
            raise ContractLoadError(f"Unknown linked_review_rule_id: {rule_id}")
        explicit.add(rule_id)

    for maybe_name in raw_entry.get("linked_review_rules", ()) or ():
        rule_name = str(maybe_name)
        rule_id = by_name.get(rule_name)
        if rule_id is None:
            raise ContractLoadError(f"Unknown linked review-rule name: {rule_name}")
        explicit.add(rule_id)

    if explicit:
        return tuple(sorted(explicit))

    field_set = set(field_ids)
    claim_set = set(claim_ids)
    derived: set[str] = set()
    for rule_id, rule in ir.review_rules.items():
        if field_set.intersection(rule.applies_to_field_ids) or claim_set.intersection(rule.applies_to_claim_family_ids):
            derived.add(rule_id)
    return tuple(sorted(derived))


def merged_provenance(paths: Sequence[PathLike]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    unique_paths = tuple(sorted({str(Path(p)) for p in paths}))
    hashes = tuple(path_sha256(Path(p)) for p in unique_paths)
    return unique_paths, hashes


def anchor_terms_from_text(text: str, max_terms: int = 8) -> tuple[str, ...]:
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-/+]{1,}", compact_text(text).lower())
    stop = {
        "the", "and", "for", "with", "that", "this", "from", "will", "must", "need", "into",
        "after", "before", "only", "when", "what", "where", "which", "while", "plus", "across",
        "into", "site", "sites", "customer", "project", "scope", "work", "required",
    }
    out: list[str] = []
    for token in tokens:
        if token in stop:
            continue
        if token not in out:
            out.append(token)
        if len(out) >= max_terms:
            break
    return tuple(out)
