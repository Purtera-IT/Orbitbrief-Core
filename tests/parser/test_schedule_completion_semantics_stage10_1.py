from __future__ import annotations

from pathlib import Path

from orbitbrief_core.compiler.packs.professional_services_text.load_compiled_pack import load_compiled_pack
from orbitbrief_core.runtime_spine.compiled_pack_runtime import load_compiled_pack_runtime_policy
from orbitbrief_core.runtime_spine.extractors.narrative_extractor import run_narrative_extractor
from orbitbrief_core.runtime_spine.extractors.packet_to_claims import PacketExtractionContext, extract_claims_from_packet


def _runtime_policy():
    compiled_pack = load_compiled_pack(
        "professional_services_text",
        compiled_root=Path(__file__).resolve().parents[2] / "compiled_artifacts",
    )
    return load_compiled_pack_runtime_policy(compiled_pack=compiled_pack)


def _packet(packet_id: str, text: str, *, packet_family: str = "schedule_packet", cues: tuple[str, ...] = ("schedule",)) -> dict:
    return {
        "packet_id": packet_id,
        "span_ids": (f"{packet_id}:span",),
        "primary_span_id": f"{packet_id}:span",
        "confidence": 0.76,
        "evidence_rows": [
            {
                "span_id": f"{packet_id}:span",
                "text": text,
                "normalized_text": text.lower(),
                "parser_cues": list(cues),
                "packet_families": [packet_family],
                "authority_score": 0.82,
                "section_path": ["Timeline & Milestones"] if packet_family == "schedule_packet" else ["Constraints"],
                "metadata": {"kind": "bullet"},
            }
        ],
        "metadata": {
            "packet_family": packet_family,
            "uncertainty_markers": [],
            "packet_diagnostic": {"included": [{"span_id": f"{packet_id}:span"}]},
        },
    }


def test_true_schedule_commitment_projects_to_schedule_and_completion_criteria() -> None:
    policy = _runtime_policy()
    packet = _packet(
        "packet:schedule:true:0001",
        "Planned service commencement: ASAP following SOW approval, resource onboarding, and completion of required access provisioning.",
    )
    result = run_narrative_extractor(
        role_id="transcript_or_notes",
        modality="docx",
        packet_candidates=[packet],
        compiled_runtime_policy=policy,
    )

    internal_claims = result["internal_claims"]
    assert len(internal_claims) == 1
    assert internal_claims[0]["claim_family"] == "schedule_claim"
    assert internal_claims[0]["metadata"]["schedule_semantic_class"] == "true_schedule_commitment"
    assert internal_claims[0]["metadata"]["completion_criteria_projection_allowed"] is True

    field_paths = {claim["field_path"] for claim in result["field_claims"]}
    assert "completion_criteria[]" in field_paths


def test_coverage_window_stays_in_schedule_but_not_completion_criteria() -> None:
    policy = _runtime_policy()
    packet = _packet(
        "packet:schedule:coverage:0001",
        "Services shall be delivered during the Customer's scheduled weekday support coverage window.",
    )
    result = run_narrative_extractor(
        role_id="transcript_or_notes",
        modality="docx",
        packet_candidates=[packet],
        compiled_runtime_policy=policy,
    )

    internal_claims = result["internal_claims"]
    assert len(internal_claims) == 1
    assert internal_claims[0]["metadata"]["schedule_semantic_class"] == "coverage_window"
    assert internal_claims[0]["metadata"]["completion_criteria_projection_allowed"] is False

    field_paths = {claim["field_path"] for claim in result["field_claims"]}
    assert field_paths == set()


def test_operational_schedule_noise_is_suppressed() -> None:
    packet = _packet(
        "packet:schedule:operational:0001",
        "Because the Customer operates in a legal services environment with occasional continuous operational demands, emergency requests outside the standard support schedule may arise and shall be addressed on a reasonable-efforts basis, subject to resource availability, unless a separate coverage model is established in writing.",
    )
    claims, diagnostics = extract_claims_from_packet(packet, PacketExtractionContext(role_id="transcript_or_notes", modality="docx"))

    assert claims == ()
    assert any(item.code == "schedule_semantic_suppressed" for item in diagnostics)


def test_monthly_billing_cadence_prefers_commercial_claim_over_schedule() -> None:
    policy = _runtime_policy()
    packet = _packet(
        "packet:schedule:commercial:0001",
        "Customer shall be invoiced monthly in arrears for the dedicated resource allocation established under this SOW.",
        cues=("schedule",),
    )
    result = run_narrative_extractor(
        role_id="transcript_or_notes",
        modality="docx",
        packet_candidates=[packet],
        compiled_runtime_policy=policy,
    )

    internal_families = {claim["claim_family"] for claim in result["internal_claims"]}
    assert "schedule_claim" not in internal_families
    assert "commercial_structure_claim" in internal_families

    field_paths = {claim["field_path"] for claim in result["field_claims"]}
    assert "commercial_structure.pricing_model" in field_paths
    assert "completion_criteria[]" not in field_paths
