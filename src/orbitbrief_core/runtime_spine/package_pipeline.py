from __future__ import annotations

from dataclasses import dataclass
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from .package_joiner import deterministic_mixed_package_join
from .pipeline import run_pipeline

_SPREADSHEET_MODALITIES = {"xlsx", "csv", "xls"}
_SITE_ALIAS_TOKEN_RE = re.compile(r"\b(?:site|location|office|hq|headquarters|branch|campus|warehouse|datacenter|data\s+center)\b", flags=re.IGNORECASE)
_PACKAGE_TOKEN_STOPWORDS = frozenset({
    "the",
    "and",
    "for",
    "from",
    "with",
    "that",
    "this",
    "will",
    "shall",
    "provide",
    "provides",
    "support",
    "service",
    "services",
    "resource",
    "resources",
    "customer",
    "customer's",
    "customer",
    "purtera",
    "dedicated",
    "full",
    "time",
    "onsite",
    "remote",
    "technical",
    "it",
    "under",
})


def _pricing_alias_key(value: Any) -> str:
    text = " ".join(str(value or "").split()).strip().lower()
    text = text.replace("fixed fee", "fixed_fee")
    text = re.sub(r"[^a-z0-9_]+", " ", text)
    return " ".join(text.split())


def _pricing_values_compatible(left: Any, right: Any) -> bool:
    left_key = _pricing_alias_key(left)
    right_key = _pricing_alias_key(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    left_tokens = set(left_key.split())
    right_tokens = set(right_key.split())
    shared = left_tokens & right_tokens
    if {"monthly", "billing"}.issubset(shared):
        return True
    return False


@dataclass(frozen=True, slots=True)
class PackageArtifactResult:
    path: str
    runtime_result: Any


@dataclass(frozen=True, slots=True)
class PackagePipelineResult:
    artifact_results: tuple[PackageArtifactResult, ...]
    joined_field_claims: tuple[dict[str, Any], ...]
    review_flags: tuple[dict[str, Any], ...]
    summary: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_results": [{"path": item.path, "pipeline_state": item.runtime_result.pipeline_state} for item in self.artifact_results],
            "joined_field_claims": [dict(item) for item in self.joined_field_claims],
            "review_flags": [dict(item) for item in self.review_flags],
            "summary": dict(self.summary),
        }


def _site_alias_key(value: Any) -> str:
    text = " ".join(str(value or "").split()).strip().lower()
    text = _SITE_ALIAS_TOKEN_RE.sub(" ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _semantic_tokens(value: Any) -> tuple[str, ...]:
    text = " ".join(str(value or "").split()).strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = [token for token in text.split() if token and token not in _PACKAGE_TOKEN_STOPWORDS]
    return tuple(dict.fromkeys(tokens))


def _semantic_overlap(left: Any, right: Any) -> float:
    left_tokens = set(_semantic_tokens(left))
    right_tokens = set(_semantic_tokens(right))
    if not left_tokens or not right_tokens:
        return 0.0
    shared = left_tokens & right_tokens
    return len(shared) / min(len(left_tokens), len(right_tokens))


def _serialize_key(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except TypeError:
        return str(value)


def _clone_claim(claim: Mapping[str, Any], *, path: str, modality: str) -> dict[str, Any]:
    payload = dict(claim)
    payload["evidence_span_ids"] = list(claim.get("evidence_span_ids", ()))
    payload["source_claim_ids"] = list(claim.get("source_claim_ids", ()))
    metadata = dict(claim.get("metadata", {}))
    metadata.setdefault("artifact_path", path)
    metadata.setdefault("artifact_modality", modality)
    payload["metadata"] = metadata
    return payload


def _iter_claims(artifact_results: Iterable[PackageArtifactResult]) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for item in artifact_results:
        runtime = item.runtime_result
        field_claims = runtime.postprocess_result.get("normalized_output", {}).get("field_claims", ())
        modality = str(runtime.parse_runtime_result.document_parse.modality)
        for claim in field_claims:
            if isinstance(claim, Mapping):
                claims.append(_clone_claim(claim, path=item.path, modality=modality))
    return claims


def _spreadsheet_support_index(claims: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    sites_by_key: dict[str, dict[str, Any]] = {}
    scalar_support: dict[str, list[dict[str, Any]]] = {}
    scope_claims: list[dict[str, Any]] = []
    summary_claims: list[dict[str, Any]] = []
    for claim in claims:
        metadata = claim.get("metadata", {}) if isinstance(claim.get("metadata"), Mapping) else {}
        modality = str(metadata.get("artifact_modality") or "")
        if modality not in _SPREADSHEET_MODALITIES:
            continue
        path = str(claim.get("target_field_path") or "")
        if path == "site_locations[]":
            key = _site_alias_key(claim.get("candidate_value"))
            if key:
                sites_by_key[key] = dict(claim)
        elif path in {"site_count", "commercial_structure.pricing_model", "customer_name", "end_customer_name", "project_summary", "scope_overview", "scope_included[].quantity", "scope_included[].unit"}:
            scalar_support.setdefault(path, []).append(dict(claim))
            if path in {"project_summary", "scope_overview"}:
                summary_claims.append(dict(claim))
        elif path == "scope_included[]":
            scope_claims.append(dict(claim))
    return {"sites_by_key": sites_by_key, "scalar_support": scalar_support, "scope_claims": scope_claims, "summary_claims": summary_claims}


def _merge_support(claim: dict[str, Any], support_claim: Mapping[str, Any], *, reason: str) -> dict[str, Any]:
    merged = dict(claim)
    merged["confidence"] = max(float(claim.get("confidence", 0.0) or 0.0), float(support_claim.get("confidence", 0.0) or 0.0))
    merged["evidence_span_ids"] = sorted(set([*claim.get("evidence_span_ids", ()), *support_claim.get("evidence_span_ids", ())]))
    merged["source_claim_ids"] = sorted(set([*claim.get("source_claim_ids", ()), *support_claim.get("source_claim_ids", ())]))
    metadata = dict(claim.get("metadata", {}))
    support_paths = list(dict.fromkeys([*metadata.get("package_support_paths", []), str(support_claim.get("target_field_path") or "")]))
    support_artifacts = list(dict.fromkeys([*metadata.get("package_support_artifacts", []), str(support_claim.get("metadata", {}).get("artifact_path") or "")]))
    metadata.update(
        {
            "package_joined": True,
            "package_join_reason": reason,
            "package_support_paths": support_paths,
            "package_support_artifacts": support_artifacts,
        }
    )
    merged["metadata"] = metadata
    return merged


def _apply_support(claims: list[dict[str, Any]], support_index: Mapping[str, Any]) -> list[dict[str, Any]]:
    sites_by_key = support_index.get("sites_by_key", {}) if isinstance(support_index.get("sites_by_key"), Mapping) else {}
    scalar_support = support_index.get("scalar_support", {}) if isinstance(support_index.get("scalar_support"), Mapping) else {}
    scope_claims = support_index.get("scope_claims", ()) if isinstance(support_index.get("scope_claims"), list) else ()
    summary_claims = support_index.get("summary_claims", ()) if isinstance(support_index.get("summary_claims"), list) else ()
    enriched: list[dict[str, Any]] = []
    for claim in claims:
        metadata = claim.get("metadata", {}) if isinstance(claim.get("metadata"), Mapping) else {}
        modality = str(metadata.get("artifact_modality") or "")
        path = str(claim.get("target_field_path") or "")
        if modality not in _SPREADSHEET_MODALITIES and path == "site_locations[]":
            key = _site_alias_key(claim.get("candidate_value"))
            support_claim = sites_by_key.get(key)
            if support_claim is not None:
                claim = dict(claim)
                claim["candidate_value"] = support_claim.get("candidate_value")
                claim = _merge_support(claim, support_claim, reason="site_alias_canonicalized_from_spreadsheet")
        if modality not in _SPREADSHEET_MODALITIES and path in {"site_count", "commercial_structure.pricing_model", "customer_name", "end_customer_name"}:
            support_claims = scalar_support.get(path, ())
            if support_claims:
                support_claim = support_claims[0]
                if path == "commercial_structure.pricing_model":
                    for candidate in support_claims:
                        if _pricing_values_compatible(claim.get("candidate_value"), candidate.get("candidate_value")):
                            claim = dict(claim)
                            claim["candidate_value"] = candidate.get("candidate_value")
                            claim = _merge_support(claim, candidate, reason="pricing_model_canonicalized_from_spreadsheet")
                            break
                elif str(claim.get("candidate_value")) == str(support_claim.get("candidate_value")):
                    claim = _merge_support(claim, support_claim, reason="scalar_value_confirmed_by_spreadsheet")
        if modality not in _SPREADSHEET_MODALITIES and path in {"project_summary", "scope_overview"}:
            for support_path in ("project_summary", "scope_overview", "site_count", "commercial_structure.pricing_model"):
                support_claims = scalar_support.get(support_path, ())
                if support_claims:
                    claim = _merge_support(claim, support_claims[0], reason="summary_supported_by_spreadsheet")
        if modality not in _SPREADSHEET_MODALITIES and path in {"scope_included[].quantity", "scope_included[].unit"}:
            for support_claim in scalar_support.get(path, ()):  # exact path only
                if str(claim.get("candidate_value")) == str(support_claim.get("candidate_value")):
                    claim = _merge_support(claim, support_claim, reason="quantity_supported_by_spreadsheet")
                    break
        if modality not in _SPREADSHEET_MODALITIES and path == "scope_included[]":
            best_match: dict[str, Any] | None = None
            best_score = 0.0
            for support_claim in scope_claims:
                score = _semantic_overlap(claim.get("candidate_value"), support_claim.get("candidate_value"))
                if score > best_score:
                    best_match = support_claim
                    best_score = score
            if best_match is None:
                for support_claim in summary_claims:
                    score = _semantic_overlap(claim.get("candidate_value"), support_claim.get("candidate_value"))
                    if score > best_score:
                        best_match = support_claim
                        best_score = score
            if best_match is not None and best_score >= 0.45:
                claim = _merge_support(claim, best_match, reason="scope_item_supported_by_spreadsheet")
        enriched.append(claim)
    return enriched


def _dedupe_claims(claims: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for claim in claims:
        key = (str(claim.get("target_field_path") or ""), _serialize_key(claim.get("candidate_value")))
        current = merged.get(key)
        if current is None:
            merged[key] = dict(claim)
            continue
        current["confidence"] = max(float(current.get("confidence", 0.0) or 0.0), float(claim.get("confidence", 0.0) or 0.0))
        current["evidence_span_ids"] = sorted(set([*current.get("evidence_span_ids", ()), *claim.get("evidence_span_ids", ())]))
        current["source_claim_ids"] = sorted(set([*current.get("source_claim_ids", ()), *claim.get("source_claim_ids", ())]))
        current_meta = dict(current.get("metadata", {}))
        claim_meta = dict(claim.get("metadata", {}))
        current_meta["package_joined"] = bool(current_meta.get("package_joined")) or bool(claim_meta.get("package_joined"))
        current_meta["package_support_paths"] = list(dict.fromkeys([*current_meta.get("package_support_paths", []), *claim_meta.get("package_support_paths", [])]))
        current_meta["package_support_artifacts"] = list(dict.fromkeys([*current_meta.get("package_support_artifacts", []), *claim_meta.get("package_support_artifacts", [])]))
        current["metadata"] = current_meta
        merged[key] = current
    return tuple(merged[key] for key in sorted(merged))


def run_package_pipeline(
    paths: Iterable[str | Path],
    *,
    compiled_pack: Any | None = None,
) -> PackagePipelineResult:
    artifact_results: list[PackageArtifactResult] = []
    for raw_path in paths:
        path = str(Path(raw_path).resolve())
        envelope = run_pipeline(path, compiled_pack=compiled_pack, include_runtime_result=True)
        artifact_results.append(PackageArtifactResult(path=path, runtime_result=envelope["runtime_result"]))

    claims = _iter_claims(artifact_results)
    support_index = _spreadsheet_support_index(claims)
    support_joined_claims = _dedupe_claims(_apply_support(claims, support_index))
    joined_claims, join_review_flags, join_summary = deterministic_mixed_package_join(support_joined_claims)

    review_flags: list[dict[str, Any]] = []
    for item in artifact_results:
        for flag in item.runtime_result.postprocess_result.get("review_flags", ()):  # type: ignore[attr-defined]
            if isinstance(flag, Mapping):
                review_flags.append(dict(flag))
    review_flags.extend(dict(flag) for flag in join_review_flags)

    summary = {
        "artifact_count": len(artifact_results),
        "joined_field_claim_count": len(joined_claims),
        "spreadsheet_support_sites": len(support_index.get("sites_by_key", {})),
        "review_flag_count": len(review_flags),
        "join_conflict_count": int(join_summary.get("join_conflict_count", 0)),
        "artifact_class_counts": dict(join_summary.get("artifact_class_counts", {})),
    }
    return PackagePipelineResult(
        artifact_results=tuple(artifact_results),
        joined_field_claims=joined_claims,
        review_flags=tuple(review_flags),
        summary=summary,
    )
