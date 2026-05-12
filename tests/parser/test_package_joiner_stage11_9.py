from __future__ import annotations

from orbitbrief_core.runtime_spine.package_joiner import deterministic_mixed_package_join


def _claim(
    *,
    claim_id: str,
    path: str,
    value,
    confidence: float,
    modality: str,
    artifact_path: str,
) -> dict:
    return {
        "claim_id": claim_id,
        "claim_family": "site_location_claim",
        "target_field": path.split(".")[0].replace("[]", ""),
        "target_field_path": path,
        "candidate_value": value,
        "confidence": confidence,
        "evidence_span_ids": [f"{claim_id}:span"],
        "source_claim_ids": [claim_id],
        "metadata": {
            "artifact_modality": modality,
            "artifact_path": artifact_path,
        },
    }


def test_joiner_prefers_spreadsheet_for_site_count_and_pricing() -> None:
    claims = [
        _claim(
            claim_id="docx:site_count",
            path="site_count",
            value="5",
            confidence=0.9,
            modality="docx",
            artifact_path="/tmp/sow.docx",
        ),
        _claim(
            claim_id="xlsx:site_count",
            path="site_count",
            value="5",
            confidence=0.8,
            modality="xlsx",
            artifact_path="/tmp/deal_kit.xlsx",
        ),
        _claim(
            claim_id="docx:pricing",
            path="commercial_structure.pricing_model",
            value="monthly in arrears",
            confidence=0.76,
            modality="docx",
            artifact_path="/tmp/sow.docx",
        ),
        _claim(
            claim_id="xlsx:pricing",
            path="commercial_structure.pricing_model",
            value="Fixed Fee - Monthly Billing",
            confidence=0.83,
            modality="xlsx",
            artifact_path="/tmp/deal_kit.xlsx",
        ),
    ]
    joined, review_flags, summary = deterministic_mixed_package_join(claims)
    by_path = {item["target_field_path"]: item for item in joined}
    assert by_path["site_count"]["candidate_value"] == "5"
    assert by_path["commercial_structure.pricing_model"]["candidate_value"] == "Fixed Fee - Monthly Billing"
    assert review_flags == ()
    assert summary["join_conflict_count"] == 0


def test_joiner_prefers_cad_for_drawing_fields_and_keeps_provenance() -> None:
    claims = [
        _claim(
            claim_id="docx:drawing_profile",
            path="site_profile_from_drawings",
            value="MDF-01 and IDF-02 with AP adjacency",
            confidence=0.88,
            modality="docx",
            artifact_path="/tmp/sow.docx",
        ),
        _claim(
            claim_id="cad:drawing_profile",
            path="site_profile_from_drawings",
            value="MDF-01 and IDF-02 with AP adjacency",
            confidence=0.74,
            modality="cad_sheet",
            artifact_path="/tmp/floorplan.pdf",
        ),
        _claim(
            claim_id="cad:metadata",
            path="drawing_packet_metadata",
            value="Sheet A-401 Rev B",
            confidence=0.78,
            modality="cad_sheet",
            artifact_path="/tmp/floorplan.pdf",
        ),
    ]
    joined, review_flags, summary = deterministic_mixed_package_join(claims)
    by_path = {item["target_field_path"]: item for item in joined}
    assert by_path["site_profile_from_drawings"]["candidate_value"] == "MDF-01 and IDF-02 with AP adjacency"
    assert by_path["site_profile_from_drawings"]["metadata"]["package_winner_modality"] == "cad_sheet"
    assert by_path["drawing_packet_metadata"]["metadata"]["package_winner_modality"] == "cad_sheet"
    assert review_flags == ()
    assert summary["artifact_class_counts"]["cad"] >= 2


def test_joiner_surfaces_conflicts_instead_of_silent_flattening() -> None:
    claims = [
        _claim(
            claim_id="docx:customer",
            path="customer_name",
            value="Musick, Peeler & Garrett",
            confidence=0.92,
            modality="docx",
            artifact_path="/tmp/sow.docx",
        ),
        _claim(
            claim_id="email:customer",
            path="customer_name",
            value="M. Peeler and Garrett",
            confidence=0.58,
            modality="email_export",
            artifact_path="/tmp/thread.eml",
        ),
    ]
    joined, review_flags, summary = deterministic_mixed_package_join(claims)
    assert len(joined) == 1
    assert joined[0]["candidate_value"] == "Musick, Peeler & Garrett"
    assert summary["join_conflict_count"] == 1
    assert review_flags
    assert review_flags[0]["code"] == "package_conflict"

