from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .config import shared_contracts_root
from .contracts import PlannerOutput, ProfessionalServicesPreDraft, contract_model_registry


def _schema_path_map() -> dict[str, Path]:
    base = shared_contracts_root() / "contracts" / "orbitbrief"
    return {
        "evidence_chunk": base / "common" / "evidence" / "evidence_chunk.schema.json",
        "table_object": base / "common" / "evidence" / "table_object.schema.json",
        "row_object": base / "common" / "evidence" / "row_object.schema.json",
        "sheet_object": base / "common" / "evidence" / "sheet_object.schema.json",
        "image_crop": base / "common" / "evidence" / "image_crop.schema.json",
        "diagram_node": base / "common" / "evidence" / "diagram_node.schema.json",
        "diagram_edge": base / "common" / "evidence" / "diagram_edge.schema.json",
        "role_graph": base / "common" / "evidence" / "role_graph.schema.json",
        "field_claim": base / "common" / "evidence" / "field_claim.schema.json",
        "authority_weight": base / "common" / "evidence" / "authority_weight.schema.json",
        "review_flag": base / "common" / "review" / "review_flag.schema.json",
        "contradiction_flag": base / "common" / "review" / "contradiction_flag.schema.json",
        "provenance_record": base / "common" / "provenance" / "provenance_record.schema.json",
        "pipeline_step_event": base / "common" / "provenance" / "pipeline_step_event.schema.json",
        "config_snapshot_ref": base / "common" / "provenance" / "config_snapshot_ref.schema.json",
        "professional_services_pre_draft": base / "professional_services" / "runtime" / "professional_services_pre_draft.schema.json",
        "planner_input": base / "professional_services" / "runtime" / "planner_input.schema.json",
        "planner_output": base / "professional_services" / "runtime" / "planner_output.schema.json",
    }


def load_schema(contract_name: str) -> dict[str, Any]:
    return json.loads(_schema_path_map()[contract_name].read_text())


def validate_against_schema(contract_name: str, payload: dict[str, Any]) -> None:
    Draft202012Validator(load_schema(contract_name)).validate(payload)


def pre_validator(draft: ProfessionalServicesPreDraft) -> None:
    validate_against_schema("professional_services_pre_draft", draft.model_dump(mode="json", exclude_none=True))


def runtime_output_validator(objects: list[Any]) -> None:
    registry = contract_model_registry()
    reverse = {model.__name__: name for name, model in registry.items()}
    for obj in objects:
        name = reverse.get(obj.__class__.__name__)
        if not name:
            continue
        validate_against_schema(name, obj.model_dump(mode="json", exclude_none=True))


def planner_output_validator(output: PlannerOutput) -> None:
    validate_against_schema("planner_output", output.model_dump(mode="json", exclude_none=True))
