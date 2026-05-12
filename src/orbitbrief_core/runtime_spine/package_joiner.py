from __future__ import annotations

import json
import re
from typing import Any, Iterable, Mapping

_SPREADSHEET_MODALITIES = {"xlsx", "csv", "xls"}
_FORMAL_MODALITIES = {"docx", "pdf_text", "pdf_ocr"}
_CAD_MODALITIES = {"cad_sheet", "schematic", "floorplan", "drawing_packet", "site_schematic_pdf", "site_schematic_image"}
_COMM_MODALITIES = {"email_export", "txt", "md", "pasted_notes"}

_LIST_FIELDS = {
    "site_locations[]",
    "known_quantities[]",
    "scope_included[]",
    "assumptions[]",
    "customer_responsibilities[]",
    "risks[]",
    "dependencies[]",
    "access_and_logistics[]",
    "open_questions[]",
    "deliverables[]",
}

_FIELD_FAMILY_PRECEDENCE: dict[str, tuple[str, ...]] = {
    "site_locations[]": ("spreadsheet", "formal_doc", "cad", "communications", "unknown"),
    "site_count": ("spreadsheet", "formal_doc", "communications", "cad", "unknown"),
    "known_quantities[]": ("spreadsheet", "cad", "formal_doc", "communications", "unknown"),
    "primary_customer_contact": ("spreadsheet", "formal_doc", "communications", "cad", "unknown"),
    "customer_name": ("spreadsheet", "formal_doc", "communications", "cad", "unknown"),
    "end_customer_name": ("spreadsheet", "formal_doc", "communications", "cad", "unknown"),
    "commercial_structure.pricing_model": ("spreadsheet", "formal_doc", "communications", "cad", "unknown"),
    "scope_included[]": ("formal_doc", "communications", "cad", "spreadsheet", "unknown"),
    "scope_excluded[]": ("formal_doc", "communications", "cad", "spreadsheet", "unknown"),
    "assumptions[]": ("formal_doc", "communications", "cad", "spreadsheet", "unknown"),
    "customer_responsibilities[]": ("formal_doc", "communications", "cad", "spreadsheet", "unknown"),
    "risks[]": ("formal_doc", "communications", "cad", "spreadsheet", "unknown"),
    "dependencies[]": ("formal_doc", "communications", "cad", "spreadsheet", "unknown"),
    "deliverables[]": ("formal_doc", "communications", "cad", "spreadsheet", "unknown"),
    "schedule": ("formal_doc", "communications", "spreadsheet", "cad", "unknown"),
    "drawing_packet_metadata": ("cad", "formal_doc", "spreadsheet", "communications", "unknown"),
    "site_profile_from_drawings": ("cad", "formal_doc", "communications", "spreadsheet", "unknown"),
    "access_and_logistics[]": ("cad", "formal_doc", "communications", "spreadsheet", "unknown"),
    "open_questions[]": ("communications", "formal_doc", "cad", "spreadsheet", "unknown"),
}

_SITE_ALIAS_TOKEN_RE = re.compile(
    r"\b(?:site|location|office|hq|headquarters|branch|campus|warehouse|datacenter|data\s+center)\b",
    flags=re.IGNORECASE,
)


def _artifact_class(modality: str) -> str:
    value = str(modality or "").strip().lower()
    if value in _SPREADSHEET_MODALITIES:
        return "spreadsheet"
    if value in _FORMAL_MODALITIES:
        return "formal_doc"
    if value in _CAD_MODALITIES:
        return "cad"
    if value in _COMM_MODALITIES:
        return "communications"
    return "unknown"


def _serialize_key(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except TypeError:
        return str(value)


def _site_alias_key(value: Any) -> str:
    text = " ".join(str(value or "").split()).strip().lower()
    text = _SITE_ALIAS_TOKEN_RE.sub(" ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


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
    union = left_tokens | right_tokens
    if "monthly" in shared and ("billing" in union or "arrears" in union):
        return True
    if "fixed_fee" in union and "monthly" in union:
        return True
    return False


def _precedence_rank(path: str, modality: str) -> int:
    order = _FIELD_FAMILY_PRECEDENCE.get(path, ("formal_doc", "spreadsheet", "communications", "cad", "unknown"))
    cls = _artifact_class(modality)
    try:
        return order.index(cls)
    except ValueError:
        return len(order)


def _candidate_score(claim: Mapping[str, Any]) -> float:
    metadata = claim.get("metadata", {}) if isinstance(claim.get("metadata"), Mapping) else {}
    modality = str(metadata.get("artifact_modality") or "")
    path = str(claim.get("target_field_path") or "")
    rank = _precedence_rank(path, modality)
    confidence = float(claim.get("confidence", 0.0) or 0.0)
    support = len(claim.get("source_claim_ids", ())) + len(claim.get("evidence_span_ids", ()))
    # Lower rank means stronger precedence.
    return (10.0 - float(rank)) + confidence + min(2.0, support * 0.1)


def _merge_claims(base: Mapping[str, Any], support: Mapping[str, Any], *, reason: str) -> dict[str, Any]:
    merged = dict(base)
    merged["confidence"] = max(float(base.get("confidence", 0.0) or 0.0), float(support.get("confidence", 0.0) or 0.0))
    merged["evidence_span_ids"] = sorted(set([*base.get("evidence_span_ids", ()), *support.get("evidence_span_ids", ())]))
    merged["source_claim_ids"] = sorted(set([*base.get("source_claim_ids", ()), *support.get("source_claim_ids", ())]))
    base_meta = dict(base.get("metadata", {})) if isinstance(base.get("metadata"), Mapping) else {}
    support_meta = dict(support.get("metadata", {})) if isinstance(support.get("metadata"), Mapping) else {}
    support_paths = list(
        dict.fromkeys(
            [
                *base_meta.get("package_support_paths", []),
                str(support.get("target_field_path") or ""),
                *support_meta.get("package_support_paths", []),
            ]
        )
    )
    support_artifacts = list(
        dict.fromkeys(
            [
                *base_meta.get("package_support_artifacts", []),
                str(support_meta.get("artifact_path") or ""),
                *support_meta.get("package_support_artifacts", []),
            ]
        )
    )
    conflict_paths = list(dict.fromkeys([*base_meta.get("package_conflicting_paths", []), *support_meta.get("package_conflicting_paths", [])]))
    merged_meta = dict(base_meta)
    merged_meta["package_joined"] = True
    merged_meta.setdefault("package_join_reason", reason)
    merged_meta["package_support_paths"] = support_paths
    merged_meta["package_support_artifacts"] = support_artifacts
    if conflict_paths:
        merged_meta["package_conflicting_paths"] = conflict_paths
    merged_meta.setdefault("package_winner_artifact_path", str(base_meta.get("artifact_path") or ""))
    merged_meta.setdefault("package_winner_modality", str(base_meta.get("artifact_modality") or ""))
    merged["metadata"] = merged_meta
    return merged


def _same_fact(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    path = str(left.get("target_field_path") or "")
    if path != str(right.get("target_field_path") or ""):
        return False
    lv = left.get("candidate_value")
    rv = right.get("candidate_value")
    if path == "site_locations[]":
        return _site_alias_key(lv) == _site_alias_key(rv) and _site_alias_key(lv) != ""
    if path == "commercial_structure.pricing_model":
        return _pricing_values_compatible(lv, rv)
    return _serialize_key(lv) == _serialize_key(rv)


def _group_by_path(claims: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for claim in claims:
        path = str(claim.get("target_field_path") or "")
        out.setdefault(path, []).append(dict(claim))
    return out


def deterministic_mixed_package_join(claims: Iterable[Mapping[str, Any]]) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...], Mapping[str, Any]]:
    grouped = _group_by_path(claims)
    joined: list[dict[str, Any]] = []
    review_flags: list[dict[str, Any]] = []
    contradiction_count = 0

    for path, path_claims in sorted(grouped.items()):
        if path in _LIST_FIELDS:
            # For list paths, keep distinct canonical values and merge support across artifacts.
            kept: list[dict[str, Any]] = []
            for claim in sorted(path_claims, key=_candidate_score, reverse=True):
                existing_idx = next((idx for idx, item in enumerate(kept) if _same_fact(item, claim)), None)
                if existing_idx is None:
                    payload = dict(claim)
                    meta = dict(payload.get("metadata", {})) if isinstance(payload.get("metadata"), Mapping) else {}
                    meta.setdefault("package_joined", False)
                    meta.setdefault("package_winner_artifact_path", str(meta.get("artifact_path") or ""))
                    meta.setdefault("package_winner_modality", str(meta.get("artifact_modality") or ""))
                    payload["metadata"] = meta
                    kept.append(payload)
                else:
                    reason = "site_alias_canonicalized_from_spreadsheet" if path == "site_locations[]" else "multi_artifact_support"
                    kept[existing_idx] = _merge_claims(kept[existing_idx], claim, reason=reason)
            joined.extend(kept)
            continue

        ordered = sorted(path_claims, key=_candidate_score, reverse=True)
        winner = dict(ordered[0])
        winner_meta = dict(winner.get("metadata", {})) if isinstance(winner.get("metadata"), Mapping) else {}
        winner_meta.setdefault("package_winner_artifact_path", str(winner_meta.get("artifact_path") or ""))
        winner_meta.setdefault("package_winner_modality", str(winner_meta.get("artifact_modality") or ""))
        winner["metadata"] = winner_meta

        for contender in ordered[1:]:
            if _same_fact(winner, contender):
                reason = "pricing_model_canonicalized_from_spreadsheet" if path == "commercial_structure.pricing_model" else "scalar_value_confirmed_by_support"
                winner = _merge_claims(winner, contender, reason=reason)
            else:
                contradiction_count += 1
                winner_meta = dict(winner.get("metadata", {}))
                conflict_paths = list(dict.fromkeys([*winner_meta.get("package_conflicting_paths", []), str(contender.get("metadata", {}).get("artifact_path") or "")]))
                winner_meta["package_conflicting_paths"] = conflict_paths
                winner_meta["package_joined"] = True
                winner["metadata"] = winner_meta
                review_flags.append(
                    {
                        "flag_id": f"package_join_conflict:{path}:{contradiction_count:04d}",
                        "code": "package_conflict",
                        "severity": "warning",
                        "message": f"Conflicting values detected for {path}; strongest source selected deterministically.",
                        "claim_ids": list(
                            dict.fromkeys(
                                [
                                    str(winner.get("claim_id") or ""),
                                    str(contender.get("claim_id") or ""),
                                ]
                            )
                        ),
                        "metadata": {
                            "target_field_path": path,
                            "winner_value": winner.get("candidate_value"),
                            "contender_value": contender.get("candidate_value"),
                            "winner_artifact": str(winner.get("metadata", {}).get("artifact_path") or ""),
                            "contender_artifact": str(contender.get("metadata", {}).get("artifact_path") or ""),
                        },
                    }
                )
        joined.append(winner)

    # Stable deterministic ordering.
    ordered_joined = tuple(
        sorted(
            joined,
            key=lambda claim: (
                str(claim.get("target_field_path") or ""),
                _serialize_key(claim.get("candidate_value")),
                str(claim.get("claim_id") or ""),
            ),
        )
    )
    summary = {
        "joined_field_claim_count": len(ordered_joined),
        "join_conflict_count": contradiction_count,
        "join_review_flag_count": len(review_flags),
        "artifact_class_counts": {
            "spreadsheet": sum(1 for claim in ordered_joined if _artifact_class(str(claim.get("metadata", {}).get("artifact_modality") or "")) == "spreadsheet"),
            "formal_doc": sum(1 for claim in ordered_joined if _artifact_class(str(claim.get("metadata", {}).get("artifact_modality") or "")) == "formal_doc"),
            "cad": sum(1 for claim in ordered_joined if _artifact_class(str(claim.get("metadata", {}).get("artifact_modality") or "")) == "cad"),
            "communications": sum(1 for claim in ordered_joined if _artifact_class(str(claim.get("metadata", {}).get("artifact_modality") or "")) == "communications"),
        },
    }
    return ordered_joined, tuple(review_flags), summary

