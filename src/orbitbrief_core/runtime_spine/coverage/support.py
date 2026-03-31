from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..config import allowed_business_fields, executable_pre_schema_ref, implemented_roles, post_schema_ref, supported_modalities_for_role
from ..contracts import build_professional_services_pre_draft_model


SUPPORTED_STATUSES = {
    "direct_extract",
    "heuristic_extract",
    "pass_through_chunk",
    "deferred_review_only",
}


def _field_strategy(role_id: str, field_name: str, stage: str) -> tuple[str, str]:
    direct = {
        "transcript_or_notes": {"project_summary", "scope_tasks_requested", "known_assumptions", "known_exclusions", "open_questions", "known_quantities", "location_details", "access_constraints", "testing_requirements", "deliverables_needed", "site_count"},
        "site_roster_spreadsheet": {"site_count", "location_details", "known_quantities", "scope_tasks_requested", "access_constraints", "testing_requirements", "deliverables_needed", "known_assumptions", "known_exclusions", "open_questions", "site_roster_rows"},
        "drawing_packet": {"location_details", "testing_requirements", "deliverables_needed", "known_quantities", "access_constraints", "open_questions"},
    }
    chunkish = {"scope_overview", "detailed_scope_of_services", "deliverables", "assumptions", "customer_responsibilities", "out_of_scope", "risks_or_dependencies", "completion_criteria", "open_items"}
    if field_name in direct.get(role_id, set()):
        return ("heuristic_extract" if role_id != "site_roster_spreadsheet" else "direct_extract", "Implemented in Stage 2 ingestor.")
    if field_name in chunkish:
        return ("pass_through_chunk", "Mapped through chunking/summarization lane without final canonicalization.")
    return ("deferred_review_only", "Accounted for in coverage but deferred to later extraction/review stages.")


def build_field_support_plan() -> dict[str, Any]:
    roles = []
    for role_id in implemented_roles():
        rows = []
        for modality in supported_modalities_for_role(role_id):
            pre_ref = executable_pre_schema_ref(role_id, modality)
            post_ref = post_schema_ref(role_id, modality)
            pre_fields = [
                {"field_name": field, "support_status": _field_strategy(role_id, field, "PRE")[0], "notes": _field_strategy(role_id, field, "PRE")[1]}
                for field in allowed_business_fields(pre_ref)
            ]
            post_fields = [
                {"field_name": field, "support_status": _field_strategy(role_id, field, "POST")[0], "notes": _field_strategy(role_id, field, "POST")[1]}
                for field in allowed_business_fields(post_ref)
            ]
            rows.append(
                {
                    "modality": modality,
                    "pre_source_schema_ref": pre_ref,
                    "post_source_schema_ref": post_ref,
                    "pre_fields": pre_fields,
                    "post_fields": post_fields,
                }
            )
        roles.append({"role_id": role_id, "rows": rows})
    draft_fields = list(build_professional_services_pre_draft_model().model_fields.keys())
    return {
        "domain_id": "professional_services",
        "runtime_scope": sorted(implemented_roles()),
        "runtime_draft_fields": draft_fields,
        "roles": roles,
    }


def validate_field_support_plan(plan: dict[str, Any]) -> None:
    for role in plan["roles"]:
        for row in role["rows"]:
            for group in ("pre_fields", "post_fields"):
                for item in row[group]:
                    if item["support_status"] not in SUPPORTED_STATUSES:
                        raise ValueError(f"Unsupported coverage status: {item['support_status']}")


def write_field_support_artifacts(yaml_path: Path, markdown_path: Path) -> dict[str, Any]:
    plan = build_field_support_plan()
    validate_field_support_plan(plan)
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(yaml.safe_dump(plan, sort_keys=False, width=120))

    lines = [
        "# Professional Services Stage 2 Coverage",
        "",
        "This report is derived from workbook-backed Stage 1 source schemas and the Stage 2 runtime support plan.",
        "",
    ]
    for role in plan["roles"]:
        lines.append(f"## {role['role_id']}")
        lines.append("")
        for row in role["rows"]:
            lines.append(f"### {row['modality']}")
            lines.append("")
            lines.append(f"- PRE source: `{row['pre_source_schema_ref']}`")
            lines.append(f"- POST source: `{row['post_source_schema_ref']}`")
            lines.append("")
            lines.append("| Field | Layer | Support | Notes |")
            lines.append("|---|---|---|---|")
            for item in row["pre_fields"]:
                lines.append(f"| `{item['field_name']}` | PRE | `{item['support_status']}` | {item['notes']} |")
            for item in row["post_fields"]:
                lines.append(f"| `{item['field_name']}` | POST | `{item['support_status']}` | {item['notes']} |")
            lines.append("")
    markdown_path.write_text("\n".join(lines) + "\n")
    return plan
