from __future__ import annotations

import json
from pathlib import Path

from orbitbrief_core.runtime_spine.config import shared_contracts_root
from orbitbrief_core.runtime_spine.contracts import contract_model_registry
from orbitbrief_core.runtime_spine.coverage import write_field_support_artifacts


ROOT = Path(__file__).resolve().parents[1]
SHARED = shared_contracts_root() / "contracts" / "orbitbrief"


SCHEMA_TARGETS = {
    "evidence_chunk": SHARED / "common" / "evidence" / "evidence_chunk.schema.json",
    "table_object": SHARED / "common" / "evidence" / "table_object.schema.json",
    "row_object": SHARED / "common" / "evidence" / "row_object.schema.json",
    "sheet_object": SHARED / "common" / "evidence" / "sheet_object.schema.json",
    "image_crop": SHARED / "common" / "evidence" / "image_crop.schema.json",
    "diagram_node": SHARED / "common" / "evidence" / "diagram_node.schema.json",
    "diagram_edge": SHARED / "common" / "evidence" / "diagram_edge.schema.json",
    "role_graph": SHARED / "common" / "evidence" / "role_graph.schema.json",
    "field_claim": SHARED / "common" / "evidence" / "field_claim.schema.json",
    "authority_weight": SHARED / "common" / "evidence" / "authority_weight.schema.json",
    "review_flag": SHARED / "common" / "review" / "review_flag.schema.json",
    "contradiction_flag": SHARED / "common" / "review" / "contradiction_flag.schema.json",
    "provenance_record": SHARED / "common" / "provenance" / "provenance_record.schema.json",
    "pipeline_step_event": SHARED / "common" / "provenance" / "pipeline_step_event.schema.json",
    "config_snapshot_ref": SHARED / "common" / "provenance" / "config_snapshot_ref.schema.json",
    "professional_services_pre_draft": SHARED / "professional_services" / "runtime" / "professional_services_pre_draft.schema.json",
    "planner_input": SHARED / "professional_services" / "runtime" / "planner_input.schema.json",
    "planner_output": SHARED / "professional_services" / "runtime" / "planner_output.schema.json",
}


def main() -> None:
    for name, model in contract_model_registry().items():
        target = SCHEMA_TARGETS[name]
        target.parent.mkdir(parents=True, exist_ok=True)
        schema = model.model_json_schema()
        target.write_text(json.dumps(schema, indent=2) + "\n")

    write_field_support_artifacts(
        ROOT / "src" / "orbitbrief_core" / "runtime_spine" / "coverage" / "field_support_plan.yaml",
        ROOT / "docs" / "professional_services_stage2_coverage.md",
    )


if __name__ == "__main__":
    main()
