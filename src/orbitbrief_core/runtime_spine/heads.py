from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import IMPLEMENTED_RUNTIME_ROLES, load_role_registry, modality_key, role_config, supported_modalities_for_role
from .contracts import AuthorityWeight, ReviewFlag
from .file_utils import pdf_page_count, sha256_file, sniff_modality
from .shared import make_id, utc_now


def integrity_head(path: Path) -> dict[str, Any]:
    flags: list[ReviewFlag] = []
    readable = path.exists() and path.is_file()
    size_bytes = path.stat().st_size if readable else 0
    fingerprint = sha256_file(path) if readable else ""
    container_hints: list[str] = []
    if path.suffix.lower() in {".docx", ".xlsx"}:
        container_hints.append("zip_container")
    if path.suffix.lower() == ".pdf":
        container_hints.append("pdf_container")
    if not readable:
        flags.append(
            ReviewFlag(
                id=make_id("review"),
                domain_id="professional_services",
                role_id="unknown",
                modality="unknown",
                severity="high",
                code="file_missing",
                message=f"Input file does not exist: {path}",
                requires_human=True,
                created_at=utc_now(),
            )
        )
    elif size_bytes == 0:
        flags.append(
            ReviewFlag(
                id=make_id("review"),
                domain_id="professional_services",
                role_id="unknown",
                modality="unknown",
                severity="high",
                code="file_empty",
                message=f"Input file is empty: {path.name}",
                requires_human=True,
                created_at=utc_now(),
            )
        )
    return {
        "status": "ok" if readable and size_bytes > 0 else "failed",
        "exists": path.exists(),
        "readable": readable,
        "size_bytes": size_bytes,
        "fingerprint": fingerprint,
        "container_hints": container_hints,
        "review_flags": flags,
        "debug": [f"exists={path.exists()}", f"size_bytes={size_bytes}", f"suffix={path.suffix.lower()}"],
    }


def modality_head(path: Path) -> dict[str, Any]:
    modality, rationale = sniff_modality(path)
    return {
        "modality": modality,
        "confidence": 0.95 if modality != "unknown" else 0.2,
        "rationale": rationale,
    }


def role_head(path: Path, modality: str) -> dict[str, Any]:
    filename = path.name.lower()
    candidates = []
    incoming_modality = modality_key(modality)
    for role_id in sorted(load_role_registry().keys()):
        allowed = [modality_key(m) for m in supported_modalities_for_role(role_id)]
        if incoming_modality in allowed:
            candidates.append(role_id)
    scored: list[tuple[float, str, str]] = []
    for role_id in candidates:
        score = 0.25
        why = "registry modality match"
        role_tokens = role_id.replace("_", " ")
        if all(token in filename for token in role_tokens.split()):
            score = 0.96
            why = "filename contains role identifier tokens"
        if role_id == "transcript_or_notes" and any(k in filename for k in ["transcript", "notes", "email", "meeting"]):
            score = 0.9
            why = "filename hints narrative transcript/notes"
        elif role_id == "site_roster_spreadsheet" and any(k in filename for k in ["roster", "site", "rollout"]):
            score = 0.9
            why = "filename hints roster/spreadsheet"
        elif role_id == "drawing_packet" and any(k in filename for k in ["drawing", "plan", "floor", "dwg"]):
            score = 0.95
            why = "filename hints drawing packet"
        elif role_id == "audit_site_review" and "audit" in filename:
            score = 0.8
            why = "filename hints audit"
        scored.append((score, role_id, why))
    scored.sort(reverse=True)
    if not scored:
        return {"role_id": None, "confidence": 0.0, "alternative_roles": [], "implemented": False, "status": "unresolved", "rationale": ["no registry role matched modality"]}
    best = scored[0]
    alternatives = [{"role_id": r, "confidence": s} for s, r, _ in scored[1:4]]
    selected_role = best[1]
    runtime_status = "implemented" if selected_role in IMPLEMENTED_RUNTIME_ROLES else ("parked" if role_config(selected_role)["status"] == "parked" else "not_implemented")
    return {
        "role_id": selected_role,
        "confidence": best[0],
        "alternative_roles": alternatives,
        "implemented": runtime_status == "implemented",
        "status": runtime_status,
        "rationale": [best[2]],
    }


def authority_head(role_id: str, modality: str) -> list[AuthorityWeight]:
    cfg = role_config(role_id)
    weights: list[AuthorityWeight] = []
    for field_name in cfg.get("authoritative_fields", []):
        weights.append(
            AuthorityWeight(
                id=make_id("authority"),
                domain_id="professional_services",
                role_id=role_id,
                modality=modality,
                field_name=field_name,
                weight=1.0,
                basis="role_registry.authoritative_fields",
                created_at=utc_now(),
            )
        )
    for field_name in cfg.get("supporting_fields", []):
        weights.append(
            AuthorityWeight(
                id=make_id("authority"),
                domain_id="professional_services",
                role_id=role_id,
                modality=modality,
                field_name=field_name,
                weight=0.5,
                basis="role_registry.supporting_fields",
                created_at=utc_now(),
            )
        )
    return weights


def complexity_head(path: Path, role_id: str, modality: str) -> dict[str, Any]:
    cfg = role_config(role_id)
    mode_32b = cfg["default_32b_mode"]
    page_like_count = pdf_page_count(path) if modality in {"pdf", "image_pdf", "dwg_export_pdf"} else 1
    size_mb = path.stat().st_size / (1024 * 1024)
    score = 1
    if size_mb > 2:
        score += 1
    if page_like_count > 3:
        score += 1
    if mode_32b == "required":
        score += 2
    flags: list[ReviewFlag] = []
    if mode_32b == "required":
        flags.append(
            ReviewFlag(
                id=make_id("review"),
                domain_id="professional_services",
                role_id=role_id,
                modality=modality,
                severity="medium",
                code="policy_requires_32b",
                message=f"Role policy marks {role_id}/{modality} as 32B-required.",
                requires_32b=True,
                created_at=utc_now(),
            )
        )
    return {
        "needs_32b_policy": mode_32b == "required",
        "complexity_score": score,
        "debug": [f"default_32b_mode={mode_32b}", f"size_mb={size_mb:.2f}", f"page_like_count={page_like_count}"],
        "review_flags": flags,
    }


def site_head(field_claims: list[Any]) -> dict[str, Any]:
    site_count_values = [claim.normalized_value for claim in field_claims if claim.field_name == "site_count" and claim.claim_status in {"asserted", "inferred"}]
    location_values = [claim.normalized_value for claim in field_claims if claim.field_name in {"location_details", "site_locations"}]
    return {
        "site_count_prior": site_count_values[0] if site_count_values else None,
        "location_structure_hints": location_values[:5],
        "site_variance_flags": ["site_count_conflict"] if len({str(v) for v in site_count_values}) > 1 else [],
    }


def review_calibrator(
    integrity: dict[str, Any],
    role_result: dict[str, Any],
    complexity: dict[str, Any],
    review_flags: list[ReviewFlag],
) -> dict[str, Any]:
    reasons = []
    if integrity["status"] != "ok":
        reasons.append("integrity_failed")
        return {"decision": "needs_human_review", "reasons": reasons}
    if role_result["status"] in {"parked", "not_implemented"}:
        reasons.append(role_result["status"])
        return {"decision": "needs_human_review", "reasons": reasons}
    if complexity["needs_32b_policy"]:
        reasons.append("32b_policy_required")
        return {"decision": "needs_32b", "reasons": reasons}
    if any(flag.requires_human for flag in review_flags):
        reasons.append("review_flags_require_human")
        return {"decision": "needs_human_review", "reasons": reasons}
    return {"decision": "auto_accept", "reasons": ["deterministic_policy_clear"]}
