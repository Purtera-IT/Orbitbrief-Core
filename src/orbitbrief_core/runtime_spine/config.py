from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


_PLAN_PATH = Path(__file__).resolve().parent / "coverage" / "field_support_plan.yaml"


@lru_cache(maxsize=1)
def _plan() -> dict[str, Any]:
    return yaml.safe_load(_PLAN_PATH.read_text(encoding="utf-8"))


def _normalize_modality_key(modality: str) -> str:
    raw = str(modality).strip()
    lowered = raw.lower().replace("_", " ")
    if lowered == "email_export":
        return "email export"
    if lowered == "pasted_notes":
        return "pasted notes"
    if lowered == "pdf_text":
        return "PDF"
    if lowered == "pdf_ocr":
        return "PDF"
    if lowered == "dwg_export_pdf":
        return "DWG export PDF"
    if lowered == "image_pdf":
        return "image PDF"
    if raw.upper() in {"TXT", "MD", "DOCX", "CSV", "XLSX", "XLS", "PDF"}:
        return raw.upper()
    return raw


@lru_cache(maxsize=1)
def _rows_by_role() -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {}
    for role in _plan().get("roles", []):
        role_id = role["role_id"]
        rows[role_id] = list(role.get("rows", []))
    return rows


@lru_cache(maxsize=1)
def _schema_field_lookup() -> dict[str, list[str]]:
    lookup: dict[str, list[str]] = {}
    for role_rows in _rows_by_role().values():
        for row in role_rows:
            pre_ref = row.get("pre_source_schema_ref")
            post_ref = row.get("post_source_schema_ref")
            if isinstance(pre_ref, str):
                lookup[pre_ref] = [item["field_name"] for item in row.get("pre_fields", [])]
            if isinstance(post_ref, str):
                lookup[post_ref] = [item["field_name"] for item in row.get("post_fields", [])]
    lookup["professional_services_post_orbitbrief_pasted_notes_v3"] = lookup.get("transcript_or_notes.docx.post.alias", [])
    return lookup


_ROLE_REGISTRY = {
    "transcript_or_notes": {"role_id": "transcript_or_notes", "runtime_status": "implemented"},
    "site_roster_spreadsheet": {"role_id": "site_roster_spreadsheet", "runtime_status": "implemented"},
    "drawing_packet": {"role_id": "drawing_packet", "runtime_status": "implemented"},
    "door_schedule_access_control": {"role_id": "door_schedule_access_control", "runtime_status": "parked"},
}

_INJECTION_REGISTRY = {
    "transcript_or_notes": {"role_id": "transcript_or_notes", "entrypoint": "runtime_spine.ingestors:ingest_transcript_or_notes"},
    "site_roster_spreadsheet": {"role_id": "site_roster_spreadsheet", "entrypoint": "runtime_spine.ingestors:ingest_site_roster_spreadsheet"},
    "drawing_packet": {"role_id": "drawing_packet", "entrypoint": "runtime_spine.ingestors:ingest_drawing_packet"},
}

_SCHEMA_REGISTRY = {
    "transcript_or_notes.docx.post.alias": {
        "schema_ref": "transcript_or_notes.docx.post.alias",
        "aliased_to": "professional_services_post_orbitbrief_pasted_notes_v3",
    }
}


def load_role_registry() -> dict[str, dict[str, Any]]:
    return {k: dict(v) for k, v in _ROLE_REGISTRY.items()}


def load_injection_registry() -> dict[str, dict[str, Any]]:
    return {k: dict(v) for k, v in _INJECTION_REGISTRY.items()}


def matrix_rows_for_role(role_id: str) -> list[dict[str, Any]]:
    rows = []
    for row in _rows_by_role().get(role_id, []):
        rows.append(
            {
                "modality": row.get("modality"),
                "pre_source_ref": row.get("pre_source_schema_ref"),
                "post_source_ref": row.get("post_source_schema_ref"),
                "pre_fields": list(row.get("pre_fields", [])),
                "post_fields": list(row.get("post_fields", [])),
            }
        )
    return rows


def role_runtime_status(role_id: str) -> str:
    return _ROLE_REGISTRY.get(role_id, {}).get("runtime_status", "unknown")


def schema_entry(schema_ref: str) -> dict[str, Any]:
    return dict(_SCHEMA_REGISTRY.get(schema_ref, {"schema_ref": schema_ref}))


def executable_pre_schema_ref(role_id: str, modality: str) -> str:
    wanted = _normalize_modality_key(modality)
    for row in _rows_by_role().get(role_id, []):
        if row.get("modality") == wanted:
            return str(row["pre_source_schema_ref"])
    raise KeyError(f"Unknown pre schema for {role_id}:{modality}")


def post_schema_ref(role_id: str, modality: str) -> str:
    wanted = _normalize_modality_key(modality)
    for row in _rows_by_role().get(role_id, []):
        if row.get("modality") == wanted:
            return str(row["post_source_schema_ref"])
    raise KeyError(f"Unknown post schema for {role_id}:{modality}")


def allowed_business_fields(schema_ref: str) -> list[str]:
    lookup = _schema_field_lookup()
    if schema_ref in _SCHEMA_REGISTRY:
        aliased = _SCHEMA_REGISTRY[schema_ref].get("aliased_to")
        if isinstance(aliased, str) and aliased in lookup:
            return list(lookup[aliased])
    if schema_ref not in lookup:
        raise KeyError(f"Unknown schema ref: {schema_ref}")
    return list(lookup[schema_ref])


def implemented_roles() -> tuple[str, ...]:
    return tuple(role_id for role_id, row in _ROLE_REGISTRY.items() if row["runtime_status"] == "implemented")


def supported_modalities_for_role(role_id: str) -> tuple[str, ...]:
    return tuple(row.get("modality") for row in _rows_by_role().get(role_id, []))


__all__ = [
    "allowed_business_fields",
    "executable_pre_schema_ref",
    "implemented_roles",
    "load_injection_registry",
    "load_role_registry",
    "matrix_rows_for_role",
    "post_schema_ref",
    "role_runtime_status",
    "schema_entry",
    "supported_modalities_for_role",
]
