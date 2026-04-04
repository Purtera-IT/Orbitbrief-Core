from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from orbitbrief_core.parser.runtime import ParseExtractionResult


@dataclass(frozen=True, slots=True)
class LegacyRoleGraph:
    summary: str


@dataclass(frozen=True, slots=True)
class LegacyPlannerOutput:
    canonical_pre_draft: Mapping[str, Any]
    review_flags: tuple[str, ...]


def adapt_parse_extraction_result(
    result: ParseExtractionResult,
    *,
    artifact_path: Path,
    target_role_id: str | None = None,
    include_runtime_result: bool = False,
) -> dict[str, Any]:
    """Translate canonical runtime result into legacy pipeline envelope."""
    postprocess = result.postprocess_result if isinstance(result.postprocess_result, Mapping) else {}
    extraction = result.extraction_result if isinstance(result.extraction_result, Mapping) else {}
    normalized_output = postprocess.get("normalized_output") if isinstance(postprocess.get("normalized_output"), Mapping) else {}
    normalized_claims = normalized_output.get("field_claims")
    claims = normalized_claims if isinstance(normalized_claims, list) else []
    review_flags = postprocess.get("review_flags")
    review_flag_codes = tuple(_extract_review_flag_codes(review_flags))
    if not review_flag_codes and result.pipeline_state in {"intake_only", "parked", "unsupported"}:
        review_flag_codes = ("fallback_required",)

    role_id = str(target_role_id or extraction.get("role_id") or "transcript_or_notes")
    status = "implemented" if result.pipeline_state == "extract" else "not_implemented"
    role_graph_summary = _build_role_graph_summary(result.pipeline_state, result.reason_codes)

    envelope: dict[str, Any] = {
        "planner_output": LegacyPlannerOutput(
            canonical_pre_draft={
                "claims": claims,
                "pipeline_state": result.pipeline_state,
                "reason_codes": list(result.reason_codes),
            },
            review_flags=review_flag_codes,
        ),
        "provenance": {
            "records": [{"artifact_path": str(artifact_path), "doc_id": result.parse_runtime_result.parse_plan.doc_id}],
            "events": list(result.diagnostics),
        },
        "review_decision": {"decision": _review_decision(result.review_required, review_flag_codes)},
        "role_result": {"role_id": role_id, "status": status},
        "ingested": {
            "review_flags": list(review_flag_codes),
            "role_graph": LegacyRoleGraph(summary=role_graph_summary),
            "pipeline_state": result.pipeline_state,
        },
    }
    if include_runtime_result:
        envelope["runtime_result"] = result
    return envelope


def _extract_review_flag_codes(review_flags: Any) -> list[str]:
    if not isinstance(review_flags, list):
        return []
    out: list[str] = []
    for item in review_flags:
        if isinstance(item, Mapping):
            code = item.get("code")
            if isinstance(code, str) and code.strip():
                out.append(code.strip())
    return out


def _review_decision(review_required: bool, review_flags: tuple[str, ...]) -> str:
    if review_required:
        return "needs_human_review"
    if "verification_needed" in review_flags:
        return "needs_32b"
    return "auto_accept"


def _build_role_graph_summary(pipeline_state: str, reason_codes: tuple[str, ...]) -> str:
    if pipeline_state in {"intake_only", "parked", "unsupported"}:
        joined = ", ".join(reason_codes) if reason_codes else "fallback_policy"
        return f"Intake-only fallback executed ({joined})"
    return "Extraction flow executed"
