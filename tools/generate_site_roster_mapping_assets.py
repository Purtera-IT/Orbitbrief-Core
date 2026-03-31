from __future__ import annotations

import json
from pathlib import Path

import yaml


ROOT = Path("/Users/purtera/dev/purtera")
SCHEMA_PATH = ROOT / "Shared-contracts/contracts/orbitbrief/professional_services/source_schemas/site_roster_spreadsheet/professional_services_pre_orbitbrief_site_roster_spreadsheet_xlsx_v2.json"
OUT_DIR = ROOT / "Orbitbrief-Core/config/domains/professional_services/mapping/site_roster_spreadsheet"

META_KEYS = {
    "schema_name",
    "schema_version",
    "domain_id",
    "file_modality",
    "sheet_type",
    "description",
    "purpose",
}


def flatten(prefix: str, value):
    paths = []
    if isinstance(value, dict):
        for k, v in value.items():
            next_prefix = f"{prefix}.{k}" if prefix else k
            paths.extend(flatten(next_prefix, v))
    elif isinstance(value, list):
        if value and isinstance(value[0], dict):
            paths.extend(flatten(f"{prefix}[]", value[0]))
        else:
            paths.append(prefix + "[]")
    else:
        paths.append(prefix)
    return paths


def family_for_path(path: str) -> str:
    if path in {
        "project_type",
        "service_category",
        "project_summary",
        "program_name",
        "customer_name",
        "end_customer_name",
        "global_program_type",
        "site_count",
        "location_details[]",
        "scope_tasks_requested[]",
        "customer_provided_materials",
    }:
        return "program_rollup"
    if any(token in path for token in ["site_id", "location_id", "site_name", "site_code_or_alias", "store_number_or_branch_code"]):
        return "site_identity"
    if any(token in path for token in ["address_", ".city", ".state_or_province", ".postal_code", ".country", ".region", ".subregion", ".timezone", ".latitude", ".longitude"]):
        return "geography"
    if any(token in path for token in [".wave", ".site_status", ".target_", "program_level_schedule", "rollout_metadata"]):
        return "schedule"
    if any(token in path for token in ["access_", "badge_required", "escort_required", "background_check_required", "dock_available", "parking_constraints", "lift_required", "freight_elevator_required", "union_or_trade_rules", "photo_restrictions"]):
        return "access"
    if any(token in path for token in ["site_readiness", "readiness_status", "hardware_on_site", "configurations_ready"]):
        return "readiness"
    if any(token in path for token in ["known_quantities", "quantity", "count", "qty"]):
        return "quantities"
    if any(token in path for token in ["device_inventory_by_site", "manufacturer", "model", "serial_or_asset_reference"]):
        return "devices"
    if any(token in path for token in ["dependencies", "blockers", "open_questions"]):
        return "blockers"
    if any(token in path for token in ["commercial", "pricing", "billing", "cost", "nte"]):
        return "commercial"
    if any(token in path for token in ["assumption", "exclusion", "note", "question", "deliverables_needed", "testing_requirements"]):
        return "notes"
    if any(token in path for token in ["program_level", "rollout_metadata", "global_assumptions_and_risk_summary"]):
        return "program_rollup"
    return "site_identity" if path.startswith("site_roster_rows[]") else "program_rollup"


def expected_types(value):
    if isinstance(value, str):
        if "|" in value:
            return ["string"]
        if value.lower() == "boolean":
            return ["boolean"]
        return ["string"]
    if isinstance(value, int):
        return ["integer"]
    if isinstance(value, list):
        return ["array"]
    if isinstance(value, dict):
        return ["object"]
    return ["string"]


def sample_examples(path: str):
    defaults = {
        "site_roster_rows[].site_id": ["SITE-001", "12345"],
        "site_roster_rows[].location_id": ["LOC-001", "ATL-001"],
        "site_roster_rows[].site_name": ["Austin HQ", "Dallas Branch"],
        "site_roster_rows[].store_number_or_branch_code": ["1001", "ATL-22"],
        "site_roster_rows[].city": ["Austin"],
        "site_roster_rows[].state_or_province": ["TX"],
        "site_roster_rows[].postal_code": ["78701"],
        "site_roster_rows[].country": ["US"],
        "site_roster_rows[].region": ["South"],
        "site_roster_rows[].wave": ["Wave 1"],
        "site_roster_rows[].target_go_live_date": ["2026-04-15"],
        "site_count": ["12"],
    }
    return defaults.get(path, [])


def main():
    payload = json.loads(SCHEMA_PATH.read_text())["schema_payload"]
    business = {k: v for k, v in payload.items() if k not in META_KEYS}
    flat_paths = []
    for key, value in business.items():
        flat_paths.extend(flatten(key, value))

    grouped = {}
    for path in flat_paths:
        fam = family_for_path(path)
        grouped.setdefault(fam, []).append(path)

    families = []
    for fam, paths in grouped.items():
        fields = []
        for path in sorted(paths):
            fields.append(
                {
                    "path": path,
                    "family_id": fam,
                    "level": "site_row" if path.startswith("site_roster_rows[]") else "program",
                    "value_kind": "array" if path.endswith("[]") else "scalar",
                    "expected_types": sample_examples(path) and ["string"] or ["string"],
                    "examples": sample_examples(path),
                    "mapping_kind_allowed": ["direct", "multi_field_split", "derived", "note_sink"] if "notes" not in fam else ["note_sink", "direct"],
                    "enum_values": [],
                    "parser_hints": [],
                    "review_risk": "medium",
                }
            )
        families.append({"family_id": fam, "fields": fields})

    catalog = {
        "role_id": "site_roster_spreadsheet",
        "domain_id": "professional_services",
        "version": "1.0.0",
        "generated_from": [
            {"source_schema_ref": "professional_services_pre_orbitbrief_site_roster_spreadsheet_xlsx_v2"},
            {"source_schema_ref": "professional_services_pre_orbitbrief_site_roster_spreadsheet_csv_v2"},
            {"source_schema_ref": "professional_services_pre_orbitbrief_site_roster_spreadsheet_xls_v2"},
        ],
        "families": families,
    }

    approved_aliases = {
        "role_id": "site_roster_spreadsheet",
        "domain_id": "professional_services",
        "version": "1.0.0",
        "aliases": [
            {"alias_id": "ps_sr_0001", "raw_alias": "Store #", "normalized_alias": "store", "target_path": "site_roster_rows[].store_number_or_branch_code", "family_id": "site_identity", "mapping_kind": "direct", "modality_scope": ["xlsx", "xls", "csv"], "sheet_scope": ["site_roster", "rollout_tracker", "main"], "sample_value_shapes": ["alphanumeric_id"], "confidence_policy": "exact_or_rule", "status": "approved", "created_from": "manual_seed", "notes": "Common retail roster header", "source_ref": {"generated_at": "2026-03-30T00:00:00Z"}, "version": "1.0.0"},
            {"alias_id": "ps_sr_0002", "raw_alias": "Branch Code", "normalized_alias": "branch code", "target_path": "site_roster_rows[].store_number_or_branch_code", "family_id": "site_identity", "mapping_kind": "direct", "modality_scope": ["xlsx", "xls", "csv"], "sheet_scope": [], "sample_value_shapes": ["alphanumeric_id"], "status": "approved", "created_from": "manual_seed", "notes": None, "source_ref": {"generated_at": "2026-03-30T00:00:00Z"}, "version": "1.0.0"},
            {"alias_id": "ps_sr_0003", "raw_alias": "Go Live", "normalized_alias": "go live", "target_path": "site_roster_rows[].target_go_live_date", "family_id": "schedule", "mapping_kind": "direct", "modality_scope": ["xlsx", "xls", "csv"], "sheet_scope": [], "sample_value_shapes": ["date"], "status": "approved", "created_from": "manual_seed", "notes": None, "source_ref": {"generated_at": "2026-03-30T00:00:00Z"}, "version": "1.0.0"},
            {"alias_id": "ps_sr_0004", "raw_alias": "City / State / Zip", "normalized_alias": "city state zip", "target_path": "site_roster_rows[]", "family_id": "geography", "mapping_kind": "multi_field_split", "modality_scope": ["xlsx", "xls", "csv"], "sheet_scope": [], "sample_value_shapes": ["address_bundle"], "split_targets": ["site_roster_rows[].city", "site_roster_rows[].state_or_province", "site_roster_rows[].postal_code"], "status": "approved", "created_from": "manual_seed", "notes": None, "source_ref": {"generated_at": "2026-03-30T00:00:00Z"}, "version": "1.0.0"},
            {"alias_id": "ps_sr_0005", "raw_alias": "Notes", "normalized_alias": "notes", "target_path": "__note_sink__", "family_id": "notes", "mapping_kind": "note_sink", "modality_scope": ["xlsx", "xls", "csv"], "sheet_scope": [], "sample_value_shapes": ["free_text"], "note_sink_targets": ["site_roster_rows[].site_assumptions[]", "site_roster_rows[].site_exclusions[]", "site_roster_rows[].site_open_questions[]", "site_roster_rows[].dependencies_and_blockers.known_blockers[]"], "status": "approved", "created_from": "manual_seed", "notes": None, "source_ref": {"generated_at": "2026-03-30T00:00:00Z"}, "version": "1.0.0"},
            {"alias_id": "ps_sr_0006", "raw_alias": "Total Sites", "normalized_alias": "total sites", "target_path": "site_count", "family_id": "program_rollup", "mapping_kind": "summary_only", "modality_scope": ["xlsx", "xls", "csv"], "sheet_scope": [], "sample_value_shapes": ["count"], "row_scope_required": "summary_only", "status": "approved", "created_from": "manual_seed", "notes": None, "source_ref": {"generated_at": "2026-03-30T00:00:00Z"}, "version": "1.0.0"},
            {"alias_id": "ps_sr_0007", "raw_alias": "Legend", "normalized_alias": "legend", "target_path": "__ignore__", "family_id": "ignore", "mapping_kind": "ignore", "modality_scope": ["xlsx", "xls", "csv"], "sheet_scope": [], "sample_value_shapes": [], "status": "approved", "created_from": "manual_seed", "notes": None, "source_ref": {"generated_at": "2026-03-30T00:00:00Z"}, "version": "1.0.0"},
            {"alias_id": "ps_sr_0008", "raw_alias": "Site ID", "normalized_alias": "site id", "target_path": "site_roster_rows[].site_id", "family_id": "site_identity", "mapping_kind": "direct", "modality_scope": ["xlsx", "xls", "csv"], "sheet_scope": [], "sample_value_shapes": ["alphanumeric_id"], "status": "approved", "created_from": "manual_seed", "notes": None, "source_ref": {"generated_at": "2026-03-30T00:00:00Z"}, "version": "1.0.0"},
            {"alias_id": "ps_sr_0009", "raw_alias": "Location ID", "normalized_alias": "location id", "target_path": "site_roster_rows[].location_id", "family_id": "site_identity", "mapping_kind": "direct", "modality_scope": ["xlsx", "xls", "csv"], "sheet_scope": [], "sample_value_shapes": ["alphanumeric_id"], "status": "approved", "created_from": "manual_seed", "notes": None, "source_ref": {"generated_at": "2026-03-30T00:00:00Z"}, "version": "1.0.0"},
            {"alias_id": "ps_sr_0010", "raw_alias": "Site Name", "normalized_alias": "site name", "target_path": "site_roster_rows[].site_name", "family_id": "site_identity", "mapping_kind": "direct", "modality_scope": ["xlsx", "xls", "csv"], "sheet_scope": [], "sample_value_shapes": ["text"], "status": "approved", "created_from": "manual_seed", "notes": None, "source_ref": {"generated_at": "2026-03-30T00:00:00Z"}, "version": "1.0.0"},
            {"alias_id": "ps_sr_0011", "raw_alias": "Address", "normalized_alias": "address", "target_path": "site_roster_rows[].address_line_1", "family_id": "geography", "mapping_kind": "direct", "modality_scope": ["xlsx", "xls", "csv"], "sheet_scope": [], "sample_value_shapes": ["address_line"], "status": "approved", "created_from": "manual_seed", "notes": None, "source_ref": {"generated_at": "2026-03-30T00:00:00Z"}, "version": "1.0.0"},
            {"alias_id": "ps_sr_0012", "raw_alias": "City", "normalized_alias": "city", "target_path": "site_roster_rows[].city", "family_id": "geography", "mapping_kind": "direct", "modality_scope": ["xlsx", "xls", "csv"], "sheet_scope": [], "sample_value_shapes": ["city"], "status": "approved", "created_from": "manual_seed", "notes": None, "source_ref": {"generated_at": "2026-03-30T00:00:00Z"}, "version": "1.0.0"},
            {"alias_id": "ps_sr_0013", "raw_alias": "State", "normalized_alias": "state", "target_path": "site_roster_rows[].state_or_province", "family_id": "geography", "mapping_kind": "direct", "modality_scope": ["xlsx", "xls", "csv"], "sheet_scope": [], "sample_value_shapes": ["state"], "status": "approved", "created_from": "manual_seed", "notes": None, "source_ref": {"generated_at": "2026-03-30T00:00:00Z"}, "version": "1.0.0"},
            {"alias_id": "ps_sr_0014", "raw_alias": "Zip", "normalized_alias": "zip", "target_path": "site_roster_rows[].postal_code", "family_id": "geography", "mapping_kind": "direct", "modality_scope": ["xlsx", "xls", "csv"], "sheet_scope": [], "sample_value_shapes": ["postal_code"], "status": "approved", "created_from": "manual_seed", "notes": None, "source_ref": {"generated_at": "2026-03-30T00:00:00Z"}, "version": "1.0.0"},
            {"alias_id": "ps_sr_0015", "raw_alias": "Country", "normalized_alias": "country", "target_path": "site_roster_rows[].country", "family_id": "geography", "mapping_kind": "direct", "modality_scope": ["xlsx", "xls", "csv"], "sheet_scope": [], "sample_value_shapes": ["country"], "status": "approved", "created_from": "manual_seed", "notes": None, "source_ref": {"generated_at": "2026-03-30T00:00:00Z"}, "version": "1.0.0"},
            {"alias_id": "ps_sr_0016", "raw_alias": "Region", "normalized_alias": "region", "target_path": "site_roster_rows[].region", "family_id": "geography", "mapping_kind": "direct", "modality_scope": ["xlsx", "xls", "csv"], "sheet_scope": [], "sample_value_shapes": ["region"], "status": "approved", "created_from": "manual_seed", "notes": None, "source_ref": {"generated_at": "2026-03-30T00:00:00Z"}, "version": "1.0.0"},
            {"alias_id": "ps_sr_0017", "raw_alias": "Wave", "normalized_alias": "wave", "target_path": "site_roster_rows[].wave", "family_id": "schedule", "mapping_kind": "direct", "modality_scope": ["xlsx", "xls", "csv"], "sheet_scope": [], "sample_value_shapes": ["text"], "status": "approved", "created_from": "manual_seed", "notes": None, "source_ref": {"generated_at": "2026-03-30T00:00:00Z"}, "version": "1.0.0"},
            {"alias_id": "ps_sr_0018", "raw_alias": "Status", "normalized_alias": "status", "target_path": "site_roster_rows[].site_status", "family_id": "schedule", "mapping_kind": "direct", "modality_scope": ["xlsx", "xls", "csv"], "sheet_scope": [], "sample_value_shapes": ["status"], "status": "approved", "created_from": "manual_seed", "notes": None, "source_ref": {"generated_at": "2026-03-30T00:00:00Z"}, "version": "1.0.0"},
            {"alias_id": "ps_sr_0019", "raw_alias": "Start Date", "normalized_alias": "start date", "target_path": "site_roster_rows[].target_start_date", "family_id": "schedule", "mapping_kind": "direct", "modality_scope": ["xlsx", "xls", "csv"], "sheet_scope": [], "sample_value_shapes": ["date"], "status": "approved", "created_from": "manual_seed", "notes": None, "source_ref": {"generated_at": "2026-03-30T00:00:00Z"}, "version": "1.0.0"},
            {"alias_id": "ps_sr_0020", "raw_alias": "Finish Date", "normalized_alias": "finish date", "target_path": "site_roster_rows[].target_finish_date", "family_id": "schedule", "mapping_kind": "direct", "modality_scope": ["xlsx", "xls", "csv"], "sheet_scope": [], "sample_value_shapes": ["date"], "status": "approved", "created_from": "manual_seed", "notes": None, "source_ref": {"generated_at": "2026-03-30T00:00:00Z"}, "version": "1.0.0"},
            {"alias_id": "ps_sr_0021", "raw_alias": "Access Notes", "normalized_alias": "access notes", "target_path": "site_roster_rows[].access_and_logistics.access_notes[]", "family_id": "access", "mapping_kind": "direct", "modality_scope": ["xlsx", "xls", "csv"], "sheet_scope": [], "sample_value_shapes": ["free_text"], "status": "approved", "created_from": "manual_seed", "notes": None, "source_ref": {"generated_at": "2026-03-30T00:00:00Z"}, "version": "1.0.0"},
            {"alias_id": "ps_sr_0022", "raw_alias": "Badge Req", "normalized_alias": "badge req", "target_path": "site_roster_rows[].access_and_logistics.badge_required", "family_id": "access", "mapping_kind": "direct", "modality_scope": ["xlsx", "xls", "csv"], "sheet_scope": [], "sample_value_shapes": ["boolean"], "status": "approved", "created_from": "manual_seed", "notes": None, "source_ref": {"generated_at": "2026-03-30T00:00:00Z"}, "version": "1.0.0"},
            {"alias_id": "ps_sr_0023", "raw_alias": "Escort Req", "normalized_alias": "escort req", "target_path": "site_roster_rows[].access_and_logistics.escort_required", "family_id": "access", "mapping_kind": "direct", "modality_scope": ["xlsx", "xls", "csv"], "sheet_scope": [], "sample_value_shapes": ["boolean"], "status": "approved", "created_from": "manual_seed", "notes": None, "source_ref": {"generated_at": "2026-03-30T00:00:00Z"}, "version": "1.0.0"},
            {"alias_id": "ps_sr_0024", "raw_alias": "AP Count", "normalized_alias": "ap count", "target_path": "site_roster_rows[].site_known_quantities[].quantity", "family_id": "quantities", "mapping_kind": "direct", "modality_scope": ["xlsx", "xls", "csv"], "sheet_scope": [], "sample_value_shapes": ["count"], "status": "approved", "created_from": "manual_seed", "notes": "Use with neighboring device category context.", "source_ref": {"generated_at": "2026-03-30T00:00:00Z"}, "version": "1.0.0"},
            {"alias_id": "ps_sr_0025", "raw_alias": "Blocked By", "normalized_alias": "blocked by", "target_path": "site_roster_rows[].dependencies_and_blockers.known_blockers[]", "family_id": "blockers", "mapping_kind": "note_sink", "modality_scope": ["xlsx", "xls", "csv"], "sheet_scope": [], "sample_value_shapes": ["free_text"], "note_sink_targets": ["site_roster_rows[].dependencies_and_blockers.known_blockers[]"], "status": "approved", "created_from": "manual_seed", "notes": None, "source_ref": {"generated_at": "2026-03-30T00:00:00Z"}, "version": "1.0.0"},
        ],
    }

    policy = {
        "accept_auto_threshold": 0.92,
        "review_threshold": 0.75,
        "top2_gap_min": 0.08,
        "hard_guards": [
            "schema_allowed_target_only",
            "expected_type_must_match",
            "summary_only_targets_require_summary_row",
            "site_row_targets_require_site_row",
        ],
        "family_resolution_order": [
            "exact",
            "normalized_exact",
            "rule",
            "family_retrieval",
            "field_retrieval",
            "hard_score",
        ],
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "field_catalog.generated.yaml").write_text(yaml.safe_dump(catalog, sort_keys=False, width=120))
    (OUT_DIR / "approved_aliases.yaml").write_text(yaml.safe_dump(approved_aliases, sort_keys=False, width=120))
    (OUT_DIR / "mapping_policy.yaml").write_text(yaml.safe_dump(policy, sort_keys=False, width=120))


if __name__ == "__main__":
    main()
