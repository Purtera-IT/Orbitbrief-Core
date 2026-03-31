from orbitbrief_core.runtime_spine.config import allowed_business_fields, executable_pre_schema_ref, implemented_roles, post_schema_ref, supported_modalities_for_role
from orbitbrief_core.runtime_spine.coverage import SUPPORTED_STATUSES, build_field_support_plan, validate_field_support_plan


def test_every_implemented_field_is_accounted_for():
    plan = build_field_support_plan()
    validate_field_support_plan(plan)
    lookup = {
        (role["role_id"], row["modality"]): row
        for role in plan["roles"]
        for row in role["rows"]
    }
    for role_id in implemented_roles():
        for modality in supported_modalities_for_role(role_id):
            row = lookup[(role_id, modality)]
            pre_fields = {item["field_name"] for item in row["pre_fields"]}
            post_fields = {item["field_name"] for item in row["post_fields"]}
            assert pre_fields == set(allowed_business_fields(executable_pre_schema_ref(role_id, modality)))
            assert post_fields == set(allowed_business_fields(post_schema_ref(role_id, modality)))
            assert all(item["support_status"] in SUPPORTED_STATUSES for item in row["pre_fields"] + row["post_fields"])
