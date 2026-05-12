from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Iterable, Mapping


_RUNTIME_PROJECTION_TARGET_OVERRIDES: dict[str, tuple[str, ...]] = {
    "customer_identity": ("customer_name", "end_customer_name"),
    "project_summary": ("project_summary", "scope_overview"),
    "site_count_claim": ("site_count",),
    "contact_claim": ("primary_customer_contact",),
    "commercial_structure_claim": ("commercial_structure.pricing_model",),
    "customer_responsibility_claim": ("customer_responsibilities[]",),
}


@dataclass(frozen=True, slots=True)
class CompiledPackRuntimePolicy:
    role_id: str
    parser_profile_by_modality: Mapping[str, str]
    allowed_claim_families_by_role: Mapping[str, frozenset[str]]
    allowed_field_paths_by_role: Mapping[str, frozenset[str]]
    claim_family_table: tuple[Mapping[str, Any], ...]
    field_table: tuple[Mapping[str, Any], ...]
    projection_rule_table: tuple[Mapping[str, Any], ...]
    review_rule_table: tuple[Mapping[str, Any], ...]
    retrieval_exemplars: tuple[Mapping[str, Any], ...]
    negative_examples: tuple[Mapping[str, Any], ...]
    review_rules_by_name: Mapping[str, Mapping[str, Any]]
    projection_targets_by_claim_family: Mapping[str, tuple[str, ...]]
    consumption_audit: Mapping[str, Any] = field(default_factory=dict)

    def allowed_claim_families_for_role(self, role_id: str) -> frozenset[str]:
        return self.allowed_claim_families_by_role.get(role_id, frozenset())

    def allowed_field_paths_for_role(self, role_id: str) -> frozenset[str]:
        return self.allowed_field_paths_by_role.get(role_id, frozenset())

    def projection_targets_for_claim_family(self, claim_family: str) -> tuple[str, ...]:
        return self.projection_targets_by_claim_family.get(claim_family, ())

    def projection_targets_for_claim_families(self, claim_families: Iterable[str]) -> frozenset[str]:
        selected = {str(family).strip() for family in claim_families if str(family).strip()}
        if not selected:
            return frozenset()
        out: set[str] = set()
        for family in selected:
            out.update(self.projection_targets_by_claim_family.get(family, ()))
        return frozenset(out)

    def canonicalize_requested_field_paths(
        self,
        requested_paths: Iterable[str],
        *,
        candidate_pool: Iterable[str] | None = None,
    ) -> frozenset[str]:
        requested = [str(path).strip() for path in requested_paths if str(path).strip()]
        if not requested:
            return frozenset()
        pool = tuple(candidate_pool) if candidate_pool is not None else tuple(self.allowed_field_paths)
        out: set[str] = set()
        for requested_path in requested:
            requested_norm = _normalize_field_text(requested_path)
            requested_tokens = _field_tokens(requested_norm)
            for candidate in pool:
                candidate_text = str(candidate).strip()
                if not candidate_text:
                    continue
                candidate_norm = _normalize_field_text(candidate_text)
                candidate_tokens = _field_tokens(candidate_norm)
                top_level = candidate_norm.split(".", 1)[0]
                if (
                    requested_path == candidate_text
                    or requested_norm == candidate_norm
                    or requested_norm == top_level
                    or candidate_norm.startswith(requested_norm + ".")
                ):
                    out.add(candidate_text)
                    continue
                if requested_tokens and requested_tokens.issubset(candidate_tokens):
                    out.add(candidate_text)
        return frozenset(out)

    @property
    def allowed_claim_families(self) -> frozenset[str]:
        return self.allowed_claim_families_for_role(self.role_id)

    @property
    def allowed_field_paths(self) -> frozenset[str]:
        return self.allowed_field_paths_for_role(self.role_id)

    @property
    def review_rules(self) -> Mapping[str, Any]:
        # Backward-compatible scalar review rules used in postprocess thresholds.
        out: dict[str, Any] = {}
        for name, row in self.review_rules_by_name.items():
            if name:
                out[name] = row.get(
                    "rule_value",
                    row.get("value", row.get("machine_instruction", row.get("severity", "info"))),
                )
        return out


def _rows(payload: Any) -> tuple[Mapping[str, Any], ...]:
    if isinstance(payload, Mapping):
        raw = payload.get("rows", ())
        if isinstance(raw, list):
            return tuple(row for row in raw if isinstance(row, Mapping))
    return ()


def _tail_id(value: Any) -> str:
    text = str(value or "").strip()
    if ":" in text:
        return text.rsplit(":", 1)[-1]
    return text


def _normalize_field_text(value: Any) -> str:
    return str(value or "").strip().lower().replace("[]", "")


def _field_tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", value) if token}


def _allowed_field_paths_for_claim_families(
    *,
    claim_families: frozenset[str],
    projection_targets_by_claim_family: Mapping[str, tuple[str, ...]],
    fallback_field_paths: frozenset[str],
) -> frozenset[str]:
    projected: set[str] = set()
    for family in claim_families:
        projected.update(projection_targets_by_claim_family.get(family, ()))
    return frozenset(projected) if projected else fallback_field_paths


def load_compiled_pack_runtime_policy(*, compiled_pack: Any) -> CompiledPackRuntimePolicy:
    manifest = getattr(compiled_pack, "manifest", None)
    role_id = str(getattr(manifest, "role_id", "transcript_or_notes"))
    parser_profile_rows = _rows(getattr(compiled_pack, "parser_profiles", None))
    claim_family_rows = _rows(getattr(compiled_pack, "claim_family_table", None))
    field_rows = _rows(getattr(compiled_pack, "field_table", None))
    projection_rows = _rows(getattr(compiled_pack, "projection_rule_table", None)) or _rows(
        getattr(compiled_pack, "projection_rules", None)
    )
    review_rows = _rows(getattr(compiled_pack, "review_rule_table", None)) or _rows(getattr(compiled_pack, "review_rules", None))
    retrieval_rows = _rows(getattr(compiled_pack, "retrieval_exemplars", None))
    negative_rows = _rows(getattr(compiled_pack, "negative_examples", None))

    parser_profile_by_modality: dict[str, str] = {}
    for row in parser_profile_rows:
        modality = str(row.get("modality", "")).strip()
        profile_id = str(row.get("parser_profile_id", "")).strip()
        if modality and profile_id:
            parser_profile_by_modality[modality] = profile_id

    allowed_claim_families = frozenset(
        _tail_id(row.get("claim_family_name", row.get("claim_family_id", row.get("name", ""))))
        for row in claim_family_rows
        if _tail_id(row.get("claim_family_name", row.get("claim_family_id", row.get("name", ""))))
    )
    field_path_by_id = {
        str(row.get("field_id", "")).strip(): str(row.get("field_path", row.get("path", ""))).strip()
        for row in field_rows
        if str(row.get("field_id", "")).strip() and str(row.get("field_path", row.get("path", ""))).strip()
    }
    fallback_field_paths = frozenset(
        str(row.get("field_path", row.get("path", row.get("field_id", "")))).strip()
        for row in field_rows
        if str(row.get("field_path", row.get("path", row.get("field_id", "")))).strip()
    )

    review_rules_by_name: dict[str, Mapping[str, Any]] = {}
    for row in review_rows:
        key = str(row.get("name", row.get("rule_key", row.get("code", "")))).strip()
        if key:
            review_rules_by_name[key] = row

    projection_targets_by_claim_family: dict[str, set[str]] = {}
    for row in projection_rows:
        claim_family = _tail_id(row.get("source_claim_family_id", row.get("claim_family_id", row.get("claim_family", ""))))
        if not claim_family:
            continue
        targets_raw = row.get("target_field_ids", ())
        if isinstance(targets_raw, list):
            for target in targets_raw:
                path = field_path_by_id.get(str(target).strip(), str(target).strip())
                if path:
                    projection_targets_by_claim_family.setdefault(claim_family, set()).add(path)
        field_path = str(row.get("field_path", "")).strip()
        if field_path:
            projection_targets_by_claim_family.setdefault(claim_family, set()).add(field_path)

    # Fallback projection hints from claim-family table when explicit projection table is empty.
    if not projection_targets_by_claim_family:
        for row in claim_family_rows:
            claim_family = _tail_id(row.get("name", row.get("claim_family_id", "")))
            if not claim_family:
                continue
            targets = row.get("projection_target_field_ids", ())
            if isinstance(targets, list):
                for target in targets:
                    path = field_path_by_id.get(str(target).strip(), str(target).strip())
                    if path:
                        projection_targets_by_claim_family.setdefault(claim_family, set()).add(path)

    for claim_family, override_targets in _RUNTIME_PROJECTION_TARGET_OVERRIDES.items():
        existing = {str(path).strip() for path in projection_targets_by_claim_family.get(claim_family, set()) if str(path).strip()}
        if claim_family == "commercial_structure_claim":
            suspicious = existing and existing.issubset({"assumptions[]", "risks_or_dependencies[]"})
            if not existing or suspicious:
                projection_targets_by_claim_family[claim_family] = set(override_targets)
            continue
        if claim_family == "customer_responsibility_claim":
            filtered = {path for path in existing if path == "customer_responsibilities[]"}
            if filtered:
                projection_targets_by_claim_family[claim_family] = filtered
                continue
        if claim_family == "customer_identity":
            filtered = {path for path in existing if path in {"customer_name", "end_customer_name"}}
            if filtered:
                projection_targets_by_claim_family[claim_family] = filtered
                continue
        if not existing:
            projection_targets_by_claim_family[claim_family] = set(override_targets)

    projected_allowed_field_paths = _allowed_field_paths_for_claim_families(
        claim_families=allowed_claim_families,
        projection_targets_by_claim_family={
            claim_family: tuple(sorted(paths)) for claim_family, paths in projection_targets_by_claim_family.items()
        },
        fallback_field_paths=fallback_field_paths,
    )

    consumption_audit = {
        "parser_profile_rows": len(parser_profile_rows),
        "claim_family_rows": len(claim_family_rows),
        "field_rows": len(field_rows),
        "projection_rule_rows": len(projection_rows),
        "review_rule_rows": len(review_rows),
        "retrieval_exemplar_rows": len(retrieval_rows),
        "negative_example_rows": len(negative_rows),
        "consumption_matrix": {
            "router": ["parser_profiles"],
            "extractor": ["claim_family_table", "retrieval_exemplars", "negative_examples"],
            "projector": ["projection_rules", "field_table"],
            "postprocess": ["field_table", "review_rules"],
            "planner_review": ["review_rules", "negative_examples"],
        },
        "consumed_artifacts": [
            "parser_profiles",
            "claim_family_table",
            "field_table",
            "projection_rules",
            "review_rules",
            "retrieval_exemplars",
            "negative_examples",
        ],
    }

    return CompiledPackRuntimePolicy(
        role_id=role_id,
        parser_profile_by_modality=parser_profile_by_modality,
        allowed_claim_families_by_role={role_id: allowed_claim_families},
        allowed_field_paths_by_role={role_id: projected_allowed_field_paths},
        claim_family_table=claim_family_rows,
        field_table=field_rows,
        projection_rule_table=projection_rows,
        review_rule_table=review_rows,
        retrieval_exemplars=retrieval_rows,
        negative_examples=negative_rows,
        review_rules_by_name=review_rules_by_name,
        projection_targets_by_claim_family={
            claim_family: tuple(sorted(paths))
            for claim_family, paths in projection_targets_by_claim_family.items()
        },
        consumption_audit=consumption_audit,
    )
