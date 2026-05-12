from __future__ import annotations

from typing import Any

from jsonschema import validate as jsonschema_validate


_SCHEMAS: dict[str, dict[str, Any]] = {
    "evidence_chunk": {
        "type": "object",
        "required": [
            "id",
            "domain_id",
            "role_id",
            "modality",
            "content_kind",
            "raw_text",
            "normalized_text",
            "source_ref",
            "token_estimate",
            "confidence",
            "created_at",
        ],
        "properties": {
            "id": {"type": "string"},
            "domain_id": {"type": "string"},
            "role_id": {"type": "string"},
            "modality": {"type": "string"},
            "content_kind": {"type": "string"},
            "raw_text": {"type": "string"},
            "normalized_text": {"type": "string"},
            "source_ref": {"type": "object"},
            "token_estimate": {"type": "integer"},
            "confidence": {"type": "number"},
            "created_at": {"type": "string"},
        },
        "additionalProperties": True,
    },
    "planner_input": {
        "type": "object",
        "required": ["domain_id", "config_snapshot_ref", "role_graphs", "field_claims"],
        "properties": {
            "domain_id": {"type": "string"},
            "config_snapshot_ref": {"type": "object"},
            "role_graphs": {"type": "array"},
            "field_claims": {"type": "array"},
            "authority_weights": {"type": "array"},
            "review_flags": {"type": "array"},
            "contradiction_flags": {"type": "array"},
            "planner_notes": {"type": "array"},
        },
        "additionalProperties": True,
    },
    "planner_output": {
        "type": "object",
        "required": ["domain_id", "config_snapshot_ref", "canonical_pre_draft", "planner_summary", "confidence"],
        "properties": {
            "domain_id": {"type": "string"},
            "config_snapshot_ref": {"type": "object"},
            "canonical_pre_draft": {"type": "object"},
            "contradiction_flags": {"type": "array"},
            "review_flags": {"type": "array"},
            "planner_summary": {"type": "string"},
            "confidence": {"type": "number"},
        },
        "additionalProperties": True,
    },
}


def validate_against_schema(schema_name: str, payload: dict[str, Any]) -> None:
    schema = _SCHEMAS.get(schema_name)
    if schema is None:
        raise KeyError(f"Unknown schema: {schema_name}")
    jsonschema_validate(payload, schema)


__all__ = ["validate_against_schema"]
