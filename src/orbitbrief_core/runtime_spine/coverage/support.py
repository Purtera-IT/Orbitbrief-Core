from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml


SUPPORTED_STATUSES = {
    "direct_extract",
    "heuristic_extract",
    "pass_through_chunk",
    "deferred_review_only",
}


def _default_plan_path() -> Path:
    return Path(__file__).with_name("field_support_plan.yaml")


def build_field_support_plan(plan_path: Path | None = None) -> dict[str, Any]:
    """Load the checked-in field support plan.

    The old implementation depended on internal runtime_spine config modules that
    are no longer present in the cutover architecture. For compatibility, this
    function now treats the bundled YAML artifact as the canonical source.
    """

    path = plan_path or _default_plan_path()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError(f"Coverage support plan must be a mapping document: {path}")
    plan = dict(data)
    validate_field_support_plan(plan)
    return plan


def validate_field_support_plan(plan: dict[str, Any]) -> None:
    roles = plan.get("roles")
    if not isinstance(roles, list):
        raise ValueError("Coverage support plan must contain a top-level 'roles' list.")
    for role in roles:
        if not isinstance(role, Mapping):
            raise ValueError("Each role row in the coverage support plan must be an object.")
        rows = role.get("rows")
        if not isinstance(rows, list):
            raise ValueError("Each role row must include a 'rows' list.")
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError("Coverage modality rows must be objects.")
            for group in ("pre_fields", "post_fields"):
                items = row.get(group)
                if not isinstance(items, list):
                    raise ValueError(f"Coverage row missing list field: {group}")
                for item in items:
                    if not isinstance(item, Mapping):
                        raise ValueError(f"Coverage {group} entries must be objects.")
                    status = item.get("support_status")
                    if status not in SUPPORTED_STATUSES:
                        raise ValueError(f"Unsupported coverage status: {status}")


def write_field_support_artifacts(yaml_path: Path, markdown_path: Path, *, plan_path: Path | None = None) -> dict[str, Any]:
    plan = build_field_support_plan(plan_path)
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(yaml.safe_dump(plan, sort_keys=False, width=120), encoding="utf-8")

    lines = [
        "# Professional Services Coverage",
        "",
        "This report is generated from the checked-in runtime support plan.",
        "",
    ]
    for role in plan["roles"]:
        role_id = role.get("role_id", "unknown_role")
        lines.append(f"## {role_id}")
        lines.append("")
        for row in role["rows"]:
            modality = row.get("modality", "unknown_modality")
            lines.append(f"### {modality}")
            lines.append("")
            pre_ref = row.get("pre_source_schema_ref", "")
            post_ref = row.get("post_source_schema_ref", "")
            lines.append(f"- PRE source: `{pre_ref}`")
            lines.append(f"- POST source: `{post_ref}`")
            lines.append("")
            lines.append("| Field | Layer | Support | Notes |")
            lines.append("|---|---|---|---|")
            for item in row.get("pre_fields", []):
                lines.append(
                    f"| `{item.get('field_name', '')}` | PRE | `{item.get('support_status', '')}` | {item.get('notes', '')} |"
                )
            for item in row.get("post_fields", []):
                lines.append(
                    f"| `{item.get('field_name', '')}` | POST | `{item.get('support_status', '')}` | {item.get('notes', '')} |"
                )
            lines.append("")
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return plan
