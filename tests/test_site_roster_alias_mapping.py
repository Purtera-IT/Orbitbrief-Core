from orbitbrief_core.runtime_spine.mapping import load_approved_aliases, load_field_catalog, load_mapping_policy, resolve_alias
from orbitbrief_core.runtime_spine.mapping_models import HeaderBundle, HeaderPosition, ValueProfile


def _bundle(raw: str, samples: list[str], modality: str = "xlsx") -> HeaderBundle:
    return HeaderBundle(
        role_id="site_roster_spreadsheet",
        domain_id="professional_services",
        modality=modality,
        header_raw=raw,
        header_normalized=raw.lower().replace("/", " ").replace("#", "").strip(),
        sheet_name="Site Roster",
        neighbor_headers=["Address", "Wave"],
        sample_values=samples,
        value_profile=ValueProfile(
            dominant_type="date" if all("-" in s for s in samples) else "alphanumeric_id",
            distinct_ratio=0.9,
            null_ratio=0.0,
            looks_like_date=all("-" in s for s in samples),
            looks_like_count=all(s.isdigit() for s in samples),
        ),
        header_position=HeaderPosition(sheet_index=1, column_index=3),
    )


def test_mapping_assets_exist_and_load():
    assert load_field_catalog()["families"]
    assert load_approved_aliases()
    assert load_mapping_policy()["accept_auto_threshold"] == 0.92


def test_exact_alias_maps_go_live():
    result = resolve_alias(_bundle("Go Live", ["2026-05-01", "2026-05-05"]), pipeline_run_id="run_1", file_fingerprint="hash")
    assert result.decision.decision_type == "accepted"
    assert result.decision.target_path == "site_roster_rows[].target_go_live_date"


def test_multi_field_split_alias_is_supported():
    result = resolve_alias(_bundle("City / State / Zip", ["Austin, TX 78701"]), pipeline_run_id="run_1", file_fingerprint="hash")
    assert result.decision.target_path == "site_roster_rows[]"
    assert result.approved_alias
    assert result.approved_alias.mapping_kind == "multi_field_split"


def test_unknown_alias_creates_candidate_observation():
    result = resolve_alias(_bundle("Branch Ref", ["ATL-001", "DAL-222"]), pipeline_run_id="run_1", file_fingerprint="hash")
    assert result.decision.decision_type in {"review_required", "unmapped"}
    assert result.candidate_observation is not None
